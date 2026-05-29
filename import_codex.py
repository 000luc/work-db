import json
import os
import glob


def _extract_text(content_blocks):
    """从 Codex 内容块列表中提取纯文本。"""
    texts = []
    if isinstance(content_blocks, str):
        return content_blocks
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if isinstance(block, dict):
                if block.get("type") in ("input_text", "output_text", "text"):
                    texts.append(block.get("text", ""))
    return "\n".join(texts).strip()


def parse_codex_file(filepath):
    """解析单个 Codex JSONL 文件，返回会话数据 dict。"""
    meta = {}
    messages = []
    session_id = None

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
            if t == "session_meta":
                p = entry.get("payload", {})
                session_id = p.get("id")
                meta = {
                    "id": session_id,
                    "timestamp": p.get("timestamp"),
                    "cwd": p.get("cwd"),
                    "model": p.get("model_provider"),
                    "source": "codex",
                    "cli_version": p.get("cli_version"),
                }

            elif t == "response_item":
                p = entry.get("payload", {})
                item_type = p.get("type")
                if item_type == "message":
                    role = p.get("role", "")
                    content = _extract_text(p.get("content", []))
                    if content and role in ("user", "assistant"):
                        messages.append({
                            "role": role,
                            "content": content,
                            "timestamp": entry.get("timestamp", meta.get("timestamp")),
                        })

    if not session_id and meta:
        session_id = meta.get("id")

    if not messages:
        return None

    cwd = meta.get("cwd", "")
    project = os.path.basename(cwd) if cwd else None
    started = meta.get("timestamp")
    ended = messages[-1]["timestamp"] if messages else started
    model = meta.get("model")

    user_msgs = [m for m in messages if m["role"] == "user"]

    return {
        "id": session_id,
        "source": "codex",
        "project": project,
        "model": model,
        "started_at": started,
        "ended_at": ended,
        "message_count": len(messages),
        "messages": messages,
        "first_user_content": user_msgs[0]["content"][:500] if user_msgs else "",
    }


def scan_codex_files(codex_path, archived_path=None):
    """扫描所有 Codex JSONL 会话文件。"""
    files = []
    pattern = os.path.join(codex_path, "**", "**", "**", "*.jsonl")
    files.extend(glob.glob(pattern, recursive=True))

    if archived_path and os.path.isdir(archived_path):
        pattern = os.path.join(archived_path, "**", "**", "**", "*.jsonl")
        files.extend(glob.glob(pattern, recursive=True))

    return sorted(set(files))


def import_codex_sessions(conn, codex_path, archived_path=None, since_timestamp=None):
    """遍历导入 Codex 会话。"""
    files = scan_codex_files(codex_path, archived_path)
    count = 0
    total = len(files)

    print(f"扫描到 {total} 个 Codex 会话文件")

    for i, fpath in enumerate(files):
        try:
            data = parse_codex_file(fpath)
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
            if count % 20 == 0:
                print(f"  Codex 导入进度: {count}/{total}")

        except Exception as e:
            print(f"  Codex 导入失败 [{os.path.basename(fpath)}]: {e}")
            continue

    print(f"Codex 导入完成: 新增 {count} 会话（跳过 {total - count} 个已存在/无效文件）")
    return count
