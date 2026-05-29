import argparse
import json
import os
import sys

from db import set_db_path, init_db, get_connection, ensure_import_meta_table, save_import_timestamp, get_import_timestamp
from topics import apply_all_topics

# ── 配置 ────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── 命令: import ──────────────────────────────────────
def cmd_import(args):
    config = load_config()
    set_db_path(config.get("db_path", "work.db"))
    init_db()

    codex_path = config.get("codex_sessions_path")
    codex_archived = config.get("codex_archived_path")
    claude_path = config.get("claude_projects_path")

    total_codex = 0
    total_claude = 0

    with get_connection() as conn:
        ensure_import_meta_table(conn)
        since = get_import_timestamp(conn)

        if codex_path and os.path.isdir(codex_path):
            from import_codex import import_codex_sessions
            total_codex = import_codex_sessions(conn, codex_path, codex_archived, since)

        if claude_path and os.path.isdir(claude_path):
            from import_claude import import_claude_sessions
            total_claude = import_claude_sessions(conn, claude_path, since)

        # 打标签 - 对还没有标签的会话
        untagged = conn.execute(
            "SELECT s.id FROM sessions s WHERE NOT EXISTS (SELECT 1 FROM topics t WHERE t.session_id = s.id)"
        ).fetchall()
        tagged = 0
        for row in untagged:
            sid = row["id"]
            first_msgs = conn.execute(
                "SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY timestamp LIMIT 10",
                (sid,)
            ).fetchall()
            proj = conn.execute("SELECT project FROM sessions WHERE id=?", (sid,)).fetchone()

            # 跳过系统注入的消息（skill模板、AGENTS.md等）
            user_queries = []
            for m in first_msgs:
                content = (m["content"] or "").strip()
                if (content.startswith("Base directory for this skill:")
                    or content.startswith("# AGENTS.md instructions")
                    or content.startswith("<INSTRUCTIONS>")
                    or content.startswith("<permissions instructions>")
                    or content.startswith("You are Claude Code")
                    or content.startswith("You are Codex")
                    or content.startswith("CLAUDE.md instructions")
                    or "Base directory for this skill:" in content[:100]):
                    continue
                user_queries.append(content[:800])
                if len(user_queries) >= 3:
                    break

            combined = " ".join(user_queries) if user_queries else ""
            session_data = {
                "project": proj["project"] if proj else None,
                "first_user_content": combined,
            }
            for topic, source in apply_all_topics(session_data):
                conn.execute("INSERT INTO topics (session_id, topic, source) VALUES (?, ?, ?)",
                             (sid, topic, source))
            tagged += 1

        save_import_timestamp(conn)
        total = total_codex + total_claude

    print(f"\n导入完成: 新增 {total} 会话, 打标签 {tagged} 会话")
    print(f"  Codex: {total_codex}  |  Claude: {total_claude}")


# ── 命令: query ──────────────────────────────────────
def cmd_query(args):
    config = load_config()
    set_db_path(config.get("db_path", "work.db"))

    with get_connection() as conn:
        conditions = []
        params = []

        if args.query:
            # FTS5 全文搜索
            try:
                rows = conn.execute(
                    "SELECT DISTINCT session_id FROM messages_fts WHERE content MATCH ? ORDER BY rank LIMIT 200",
                    (args.query,)
                ).fetchall()
                sids = tuple(r["session_id"] for r in rows)
                if sids:
                    conditions.append(f"s.id IN ({','.join('?' * len(sids))})")
                    params.extend(sids)
                else:
                    # 降级到 LIKE 搜索
                    conditions.append("m.content LIKE ?")
                    params.append(f"%{args.query}%")
                    rows = conn.execute(
                        "SELECT DISTINCT m.session_id FROM messages m WHERE m.content LIKE ? LIMIT 200",
                        (f"%{args.query}%",)
                    ).fetchall()
                    sids = tuple(r["session_id"] for r in rows)
                    if sids:
                        conditions[-1] = f"s.id IN ({','.join('?' * len(sids))})"
                        params = params[:-1] + list(sids)

            except Exception:
                conditions.append("m.content LIKE ?")
                params.append(f"%{args.query}%")

        if args.topic:
            conditions.append("EXISTS (SELECT 1 FROM topics t WHERE t.session_id = s.id AND t.topic = ?)")
            params.append(args.topic)

        if args.project:
            conditions.append("s.project LIKE ?")
            params.append(f"%{args.project}%")

        if args.from_date:
            conditions.append("s.started_at >= ?")
            params.append(args.from_date)

        if args.to_date:
            conditions.append("s.started_at <= ?")
            params.append(args.to_date)

        where = " AND ".join(conditions) if conditions else "1=1"
        limit = args.limit or 20

        rows = conn.execute(
            f"SELECT DISTINCT s.id, s.source, s.project, s.model, s.started_at, s.ended_at, s.message_count, s.summary "
            f"FROM sessions s "
            f"LEFT JOIN messages m ON m.session_id = s.id "
            f"WHERE {where} "
            f"ORDER BY s.started_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()

        if not rows:
            print("未找到匹配的会话")
            return

        print(f"找到 {len(rows)} 个会话:\n")

        for r in rows:
            topics = conn.execute(
                "SELECT topic FROM topics WHERE session_id=?", (r["id"],)
            ).fetchall()
            topic_str = ", ".join(t["topic"] for t in topics) if topics else "无标签"
            sid_short = r["id"][:12] + "..." if len(r["id"]) > 12 else r["id"]

            print(f"[{sid_short}] {r['source']} | {r['project'] or '?'} | {r['started_at'][:10] if r['started_at'] else '?'}")
            print(f"       标签: {topic_str} | 消息: {r['message_count']}")
            if r["summary"]:
                print(f"       摘要: {r['summary']}")
            print()

            if args.detail:
                msgs = conn.execute(
                    "SELECT role, content, timestamp FROM messages WHERE session_id=? ORDER BY timestamp LIMIT 30",
                    (r["id"],)
                ).fetchall()
                for m in msgs:
                    content_preview = m["content"][:300].replace("\n", " ")
                    print(f"       [{m['role']}] {content_preview}")
                print()


# ── 命令: analyze ────────────────────────────────────
def cmd_analyze(args):
    config = load_config()
    set_db_path(config.get("db_path", "work.db"))

    with get_connection() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

        print("=" * 50)
        print("work-db 分析报告")
        print("=" * 50)
        print(f"总会话数: {total_sessions}")
        print(f"总消息数: {total_messages}")

        # 数据跨度
        row = conn.execute("SELECT MIN(started_at) first, MAX(ended_at) last FROM sessions").fetchone()
        print(f"数据跨度: {row['first'][:10] if row['first'] else '?'} ~ {row['last'][:10] if row['last'] else '?'}")

        # 来源分布
        print("\n--- 来源分布 ---")
        for r in conn.execute("SELECT source, COUNT(*) cnt FROM sessions GROUP BY source ORDER BY cnt DESC").fetchall():
            print(f"  {r['source']}: {r['cnt']} 会话")

        # 高频项目 TOP15
        print("\n--- 高频项目 TOP15 ---")
        for i, r in enumerate(conn.execute(
            "SELECT project, COUNT(*) cnt FROM sessions WHERE project IS NOT NULL GROUP BY project ORDER BY cnt DESC LIMIT 15"
        ).fetchall(), 1):
            print(f"  {i:2d}. {r['project']}: {r['cnt']} 会话")

        # 标签分布
        print("\n--- 标签分布 ---")
        for r in conn.execute(
            "SELECT topic, COUNT(*) cnt FROM topics GROUP BY topic ORDER BY cnt DESC"
        ).fetchall():
            print(f"  {r['topic']}: {r['cnt']} 会话")

        # 月度趋势
        print("\n--- 月度趋势 ---")
        for r in conn.execute(
            "SELECT substr(started_at, 1, 7) month, COUNT(*) cnt FROM sessions WHERE started_at IS NOT NULL GROUP BY month ORDER BY month DESC LIMIT 12"
        ).fetchall():
            print(f"  {r['month']}: {r['cnt']} 会话")

        # CLAUDE.md 规则建议
        print("\n--- 写入 CLAUDE.md 的建议 ---")
        suggestions = []

        # 检查高频项目
        projects = conn.execute(
            "SELECT project, COUNT(*) cnt FROM sessions WHERE project IS NOT NULL GROUP BY project ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        if projects:
            top = projects[0]
            suggestions.append(f"高频项目 '{top['project']}' 有 {top['cnt']} 个会话")

        # 检查高频标签
        topics = conn.execute(
            "SELECT topic, COUNT(*) cnt FROM topics GROUP BY topic ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        if topics:
            top_topics = [f"{t['topic']}({t['cnt']})" for t in topics]
            suggestions.append(f"主要工作领域: {', '.join(top_topics)}")

        if suggestions:
            for s in suggestions:
                print(f"  - {s}")
        else:
            print("  (数据不足，暂无法生成建议)")

        print()


# ── 命令: stats ──────────────────────────────────────
def cmd_stats(args):
    config = load_config()
    set_db_path(config.get("db_path", "work.db"))

    with get_connection() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_topics = conn.execute("SELECT COUNT(DISTINCT topic) FROM topics").fetchone()[0]
        project_count = conn.execute("SELECT COUNT(DISTINCT project) FROM sessions WHERE project IS NOT NULL").fetchone()[0]
        row = conn.execute("SELECT MIN(started_at) first, MAX(ended_at) last FROM sessions").fetchone()

        codex_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='codex'").fetchone()[0]
        claude_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='claude'").fetchone()[0]

        print("work-db 概览")
        print("=" * 40)
        print(f"总会话: {total_sessions}")
        print(f"总消息: {total_messages}")
        print(f"数据跨度: {row['first'][:10] if row['first'] else '?'} ~ {row['last'][:10] if row['last'] else '?'}")
        print(f"来源: Codex {codex_count}  |  Claude {claude_count}")
        print(f"项目数: {project_count}")
        print(f"标签数: {total_topics}")


# ── MCP 模式 ──────────────────────────────────────────
def cmd_mcp(args):
    """MCP Server 模式，通过 stdio 通信。"""
    import sys

    def respond(msg):
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    # 读取初始化请求
    init_msg = json.loads(sys.stdin.readline())
    respond({
        "jsonrpc": "2.0",
        "id": init_msg.get("id"),
        "result": {
            "serverInfo": {"name": "work-db", "version": "1.0.0"},
            "capabilities": {"tools": {}}
        }
    })

    config = load_config()
    set_db_path(config.get("db_path", "work.db"))

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        req_id = req.get("id")

        if method == "tools/list":
            respond({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "query_work_history",
                            "description": "查询历史工作记录，支持关键词、项目、标签、时间范围过滤",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "搜索关键词"},
                                    "topic": {"type": "string", "description": "按标签筛选"},
                                    "project": {"type": "string", "description": "按项目筛选"},
                                    "from_date": {"type": "string", "description": "开始日期"},
                                    "to_date": {"type": "string", "description": "结束日期"},
                                    "detail": {"type": "boolean", "description": "是否显示消息详情"},
                                    "limit": {"type": "integer", "description": "返回数量"},
                                }
                            }
                        },
                        {
                            "name": "analyze_work_patterns",
                            "description": "分析工作模式，返回项目分布、标签统计、月度趋势、CLAUDE.md规则建议",
                            "inputSchema": {
                                "type": "object",
                                "properties": {}
                            }
                        },
                        {
                            "name": "get_work_stats",
                            "description": "获取工作数据库概览统计",
                            "inputSchema": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                    ]
                }
            })

        elif method == "tools/call":
            tool_name = req.get("params", {}).get("name", "")
            tool_args = req.get("params", {}).get("arguments", {})

            try:
                if tool_name == "query_work_history":
                    import io
                    from contextlib import redirect_stdout
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        cmd_query(argparse.Namespace(
                            query=tool_args.get("query", ""),
                            topic=tool_args.get("topic", None),
                            project=tool_args.get("project", None),
                            from_date=tool_args.get("from_date", None),
                            to_date=tool_args.get("to_date", None),
                            detail=tool_args.get("detail", False),
                            limit=tool_args.get("limit", 20),
                        ))
                    respond({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": buf.getvalue()}]}})

                elif tool_name == "analyze_work_patterns":
                    import io
                    from contextlib import redirect_stdout
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        cmd_analyze(argparse.Namespace())
                    respond({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": buf.getvalue()}]}})

                elif tool_name == "get_work_stats":
                    import io
                    from contextlib import redirect_stdout
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        cmd_stats(argparse.Namespace())
                    respond({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": buf.getvalue()}]}})

                else:
                    respond({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})

            except Exception as e:
                respond({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}})


# ── 主入口 ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="work-db 工作记录数据库")
    sub = parser.add_subparsers(dest="command")

    p_import = sub.add_parser("import", help="导入会话数据")
    p_import.add_argument("--incremental", action="store_true", help="仅增量导入")

    p_query = sub.add_parser("query", help="查询工作记录")
    p_query.add_argument("query", nargs="?", default="", help="搜索关键词")
    p_query.add_argument("--topic", help="按标签筛选")
    p_query.add_argument("--project", help="按项目筛选")
    p_query.add_argument("--from", dest="from_date", help="开始日期")
    p_query.add_argument("--to", dest="to_date", help="结束日期")
    p_query.add_argument("--detail", action="store_true", help="显示消息详情")
    p_query.add_argument("--limit", type=int, default=20, help="返回数量")

    sub.add_parser("analyze", help="分析工作模式")

    sub.add_parser("stats", help="数据库概览")

    sub.add_parser("mcp", help="MCP Server 模式")

    args = parser.parse_args()

    if args.command == "import":
        cmd_import(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
