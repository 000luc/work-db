import json
import os
import glob


def _extract_claude_content(content_field):
    """从 Claude 消息的 content 字段提取纯文本。"""
    if isinstance(content_field, str):
        return content_field
    if isinstance(content_field, list):
        texts = []
        for block in content_field:
            if isinstance(block, dict):
                t = block.get("type", "")
                if t == "text":
                    texts.append(block.get("text", ""))
                elif t == "tool_use":
                    texts.append(json.dumps({"tool_use": block.get("name", ""), "input": block.get("input", {})}, ensure_ascii=False))
                elif t == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, list):
                        for sub in content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                texts.append(sub.get("text", ""))
                    elif isinstance(content, str):
                        texts.append(content)
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts).strip()
    return ""


def parse_claude_file(filepath, project_name=None):
    """解析单个 Claude Code JSONL 文件。"""
    session_id = None
    cwd = None
    messages = []
    first_external_ts = None
    last_ts = None

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = entry.get("type")

            if t in ("user", "assistant"):
                msg = entry.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                content = _extract_claude_content(msg.get("content", ""))

                # 提取 content 中的纯文本（可能有嵌套的 type: text 结构）
                if not content:
                    continue

                ts = entry.get("timestamp")
                sid = entry.get("sessionId")
                if sid:
                    session_id = sid

                if t == "user":
                    user_type = entry.get("userType", "")
                    if user_type == "external" and not cwd:
                        cwd = entry.get("cwd", "")
                    if not first_external_ts and user_type == "external":
                        first_external_ts = ts

                messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": ts,
                })
                last_ts = ts

    if not messages or not session_id:
        return None

    return {
        "id": session_id,
        "source": "claude",
        "project": project_name or os.path.basename(cwd) if cwd else None,
        "model": None,
        "started_at": first_external_ts or messages[0]["timestamp"],
        "ended_at": last_ts or messages[-1]["timestamp"],
        "message_count": len(messages),
        "messages": messages,
        "first_user_content": messages[0]["content"][:500] if messages and messages[0]["role"] == "user" else "",
    }


def scan_claude_files(claude_path):
    """扫描所有 Claude Code JSONL 会话文件，排除 subagents 目录。返回 [(path, project_name)]"""
    files = []
    for root, dirs, fnames in os.walk(claude_path):
        if "subagents" in dirs:
            dirs.remove("subagents")
        # 项目名来自根目录下的一级子目录名
        rel = os.path.relpath(root, claude_path)
        project_name = rel.split(os.sep)[0] if rel != "." else None
        for fname in fnames:
            if fname.endswith(".jsonl"):
                files.append((os.path.join(root, fname), project_name))
    return sorted(files, key=lambda x: x[0])


def import_claude_sessions(conn, claude_path, since_timestamp=None):
    """遍历导入 Claude 会话。"""
    files = scan_claude_files(claude_path)
    count = 0
    total = len(files)

    print(f"扫描到 {total} 个 Claude 会话文件")

    for i, (fpath, proj_name) in enumerate(files):
        try:
            data = parse_claude_file(fpath, project_name=proj_name)
            if data is None:
                continue

            sid = data["id"]
            existing = conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, source, project, model, started_at, ended_at, message_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, data["source"], data["project"], data["model"],
                 data["started_at"], data["ended_at"], data["message_count"])
            )

            for msg in data["messages"]:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                    (sid, msg["role"], msg["content"], msg["timestamp"])
                )

            count += 1
            if count % 30 == 0:
                print(f"  Claude 导入进度: {count}/{total}")

        except Exception as e:
            print(f"  Claude 导入失败 [{os.path.basename(fpath)}]: {e}")
            continue

    print(f"Claude 导入完成: 新增 {count} 会话（跳过 {total - count} 个已存在/无效文件）")
    return count
