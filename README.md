# Work Database (work-db)

将 **Codex** 和 **Claude Code** 的全部历史会话记录结构化入库，支持通过 CLI 或 agent 查询、分析和提炼工作规则。

Import all **Codex** and **Claude Code** session transcripts into a local SQLite database, with CLI + MCP interfaces for querying, analyzing, and extracting work patterns.

---

## 功能 / Features

- **全量导入** — 一次性将本地所有历史会话（JSONL）解析入库
- **增量更新** — 只处理新增/修改的文件，几秒完成
- **智能标签** — 基于项目名 + 内容关键词双引擎自动分类
- **全文搜索** — SQLite FTS5 全文索引，毫秒级响应
- **工作分析** — 按项目/标签/时间统计工作分布，输出 CLAUDE.md 规则建议
- **CLI + MCP** — 命令行直查，也支持 MCP 协议供 agent 调用

## 快速开始 / Quick Start

```bash
# 1. 首次全量导入（扫描本地所有会话文件）
cd work-db
py main.py import

# 2. 查询历史工作
py main.py query "租赁合同审核"
py main.py query --topic "审计复核"
py main.py query "股权激励" --detail

# 3. 查看工作统计
py main.py stats
py main.py analyze

# 4. 增量更新（日常使用）
py main.py import --incremental
```

## 数据来源 / Data Sources

| 来源 | 会话数 | 位置 |
|------|--------|------|
| Codex | ~120+ | `~/.codex/sessions/` |
| Claude Code | ~220+ | `~/.claude/projects/` |

导入过程只读取文件，不修改任何原始数据。

## 数据模型 / Schema

```sql
sessions (id, source, project, model, started_at, ended_at, message_count, summary)
messages (id, session_id, role, content, timestamp)
topics   (id, session_id, topic, source)
```

- `sessions` — 每个会话的元数据
- `messages` — 每条消息的完整内容，含 FTS5 全文索引
- `topics` — 按规则和关键词自动生成的分类标签

## 配置 / Configuration

编辑 `config.json` 指定数据源路径：

```json
{
  "codex_sessions_path": "C:\\Users\\xxx\\.codex\\sessions",
  "claude_projects_path": "C:\\Users\\xxx\\.claude\\projects",
  "db_path": "work.db"
}
```

## 许可证 / License

MIT
