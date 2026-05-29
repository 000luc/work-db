# work-db

将 Codex 和 Claude Code 的全部历史会话记录结构化入库，支持 CLI 和 MCP 查询。

## 快速命令

```bash
# 增量导入（日常用）
cd d:/BaiduSyncdisk/claude/work-db && py main.py import --incremental

# 全量导入（首次或重建）
cd d:/BaiduSyncdisk/claude/work-db && py main.py import

# 查询历史
py main.py query "租赁合同"
py main.py query --topic "审计复核"
py main.py query --project "audit-report-review" --detail

# 分析与统计
py main.py analyze
py main.py stats
```

## 架构

- `main.py` — CLI 入口 + MCP Server
- `db.py` — SQLite 连接管理、建表、导入时间戳
- `topics.py` — 分类引擎（项目名规则 + 内容关键词 + AI 术语加权）
- `import_codex.py` / `import_claude.py` — 各自源格式的解析器
- `config.json` — 数据源路径配置
- `work.db` — SQLite 数据库（FTS5 全文索引）

## 表结构

- `sessions` — 会话元数据（来源、项目、模型、时间、摘要）
- `messages` — 每条消息，含 FTS5 全文索引
- `topics` — 分类标签（rule/AI 双来源）
- `import_meta` — 增量导入时间戳

## 数据源位置

| 来源 | 路径 |
|------|------|
| Codex | `~/.codex/sessions/` + `~/.codex/archived_sessions/` |
| Claude Code | `~/.claude/projects/` |

## MCP Server

`py main.py mcp` 启动 MCP 模式，通过 stdio 通信，暴露三个 tool：

- `query_work_history` — 关键词/标签/项目/时间范围查询
- `analyze_work_patterns` — 工作模式分析
- `get_work_stats` — 数据库概览
