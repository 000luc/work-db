# work-db 实施计划

> **子技能要求:** 使用 superpowers:subagent-driven-development 分发任务。
> 步骤使用复选框 (`- [ ]`) 跟踪进度。

**目标:** 将本机所有 Codex 和 Claude Code 会话记录导入 SQLite，提供 CLI 查询和分析能力。

**架构:** Python CLI + SQLite (FTS5)，纯本地运行，支持通过 MCP 挂载为 agent 工具。

**技术栈:** Python 3 + sqlite3 (内置模块)

---

### 任务 1: 项目框架 + db.py

**文件:**
- 创建: `work-db/db.py`
- 创建: `work-db/config.json`

- [ ] **步骤 1: 创建 config.json**

```json
{
  "codex_sessions_path": "C:\\Users\\lucheng\\.codex\\sessions",
  "codex_archived_path": "C:\\Users\\lucheng\\.codex\\archived_sessions",
  "claude_projects_path": "C:\\Users\\lucheng\\.claude\\projects",
  "db_path": "work.db",
  "ai_label_enabled": true
}
```

- [ ] **步骤 2: 创建 db.py**

包含:
- `get_connection()` — 获取数据库连接，自动创建目录
- `init_db()` — 建表（sessions, messages, topics）+ FTS5 全文搜索虚拟表 + 索引
- `import_timestamp()` / `save_import_timestamp()` / `get_import_timestamp()` — 增量导入时间戳管理
- 使用 `contextlib.contextmanager` 实现连接管理

SQLite 表:
```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    project TEXT,
    model TEXT,
    started_at TEXT,
    ended_at TEXT,
    message_count INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    topic TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content=messages, content_rowid=id
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_topics_session ON topics(session_id);
CREATE INDEX IF NOT EXISTS idx_topics_topic ON topics(topic);
```

- [ ] **步骤 3: 测试并验证建表**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py -c "from db import init_db, get_connection; init_db(); print('OK')"
```

预期输出: `OK`
之后 `py -c "import sqlite3; c=sqlite3.connect('work.db'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"`
预期输出包含 `sessions`, `messages`, `topics`, `messages_fts`

- [ ] **步骤 4: 提交**

---

### 任务 2: Codex 会话导入模块

**文件:**
- 创建: `work-db/import_codex.py`

- [ ] **步骤 1: 实现 Codex JSONL 解析**

解析逻辑:
- Codex 文件路径格式: `<codex_sessions_path>/YYYY/MM/DD/rollout-<uuid>.jsonl`
- 第一行是 `session_meta` 类型，包含 `payload.id`、`payload.timestamp`、`payload.cwd`、`payload.model_provider`
- 后续行类型: `user`（用户消息）、`assistant`（AI回复）、`tool`（工具调用）、`result`（工具结果）
- 只提取 `user` 和 `assistant` 类型的消息，从 `payload.content` 中提取文本
- 会话 ID = `payload.id`
- 开始时间 = 第一条消息的时间
- 结束时间 = 最后一条消息的时间
- 项目名 = 从 `payload.cwd` 中提取最后一级目录名
- 消息数 = 统计提取到的消息条数

函数:
- `parse_codex_file(filepath)` — 解析单个文件，返回 dict
- `import_codex_sessions(conn, codex_path, archive_path, since_timestamp)` — 遍历目录导入

- [ ] **步骤 2: 处理纯文本提取**

消息内容可能为：
- 字符串 → 直接使用
- 列表（包含 `type: "text"` 元素）→ 拼接所有 text 元素

- [ ] **步骤 3: 增量导入支持**

记录每个文件的 mtime，只处理 mtime > `since_timestamp` 的文件

- [ ] **步骤 4: 测试导入一个小文件**

找 Codex 目录下一个小的 JSONL 文件测试解析

```bash
cd d:/BaiduSyncdisk/claude/work-db
py -c "from import_codex import parse_codex_file; import glob; files = glob.glob('C:/Users/lucheng/.codex/sessions/2026/05/29/*.jsonl'); r=parse_codex_file(files[0]); print(r['id'], r['message_count'])"
```

预期输出: 打印会话 ID 和消息数

- [ ] **步骤 5: 提交**

---

### 任务 3: Claude Code 会话导入模块

**文件:**
- 创建: `work-db/import_claude.py`

- [ ] **步骤 1: 实现 Claude Code JSONL 解析**

解析逻辑:
- Claude 文件路径格式: `<claude_projects_path>/<project>/<uuid>.jsonl`
- 每条 JSON 包含 `type` 字段
- 类型 `user`: `message.role == "user"`，内容在 `message.content`（字符串或列表）
- 类型 `user` 同时也携带 `sessionId`、`timestamp`、`cwd`（第一条用户消息有完整信息）
- 类型 `assistant`: 需要从后续的非用户行中寻找 assistant 回复

实际上 Claude JSONL 的每个顶层内容是:
```
{"type":"ai-title","aiTitle":"...","sessionId":"..."}
{"type":"queue-operation",...}
{"type":"user","message":{"role":"user","content":"..."},"sessionId":"...","timestamp":"...","cwd":"..."}
{"type":"user","message":{"role":"user","content":[...]},...}  // system injected
{"type":"assistant", "message":{"role":"assistant","content":"..."},"sessionId":"..."}
{"type":"tool","message":...,"sessionId":"..."}
{"type":"result","message":...,"sessionId":"..."}
```

会话元数据（sessionId, cwd, 时间）从第一个 `type=user` 且 `userType="external"` 的消息中提取。

函数:
- `parse_claude_file(filepath)` — 解析单个文件
- `import_claude_sessions(conn, claude_path, since_timestamp)` — 遍历导入

- [ ] **步骤 2: 文件扫描逻辑**

遍历 `claude_projects_path` 下的所有子目录，在每个目录中查找 `*.jsonl` 文件（排除 subagents 目录）

- [ ] **步骤 3: 测试导入一个小文件**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py -c "from import_claude import parse_claude_file; r=parse_claude_file('C:/Users/lucheng/.claude/projects/D--BaiduSyncdisk-claude/64a3f820-fafd-43a2-9aac-f5a6af26b8fc.jsonl'); print(r['id'], r['message_count'])"
```

预期输出: 打印会话 ID 和消息数

- [ ] **步骤 4: 提交**

---

### 任务 4: 主题标签模块

**文件:**
- 创建: `work-db/topics.py`

- [ ] **步骤 1: 实现规则打标签**

```python
RULE_TOPICS = {
    "audit-report-review": "审计复核",
    "contract-approval": "合同审核",
    "contract-sentinel": "合同审核",
    "gdjl-report": "财报分析",
    "finance-review": "财报分析",
    "share-based-payment": "股权激励",
    "tax-report": "税务申报",
    "租赁": "租赁准则",
    "股份支付": "股权激励",
    "所得税": "税务申报",
    "OCR": "OCR识别",
    "brainstorming": "方案设计",
    "writing-plans": "实施计划",
}

def apply_rule_topics(session_data):
    """根据项目名和会话内容关键词打标签"""
```

- [ ] **步骤 2: 实现 AI 打标签**

使用一个简单的关键词频率分析算法（不需要调用 AI API，纯本地）：
1. 提取会话中所有 user 消息内容
2. 统计术语频率（从预定义词库中匹配）
3. 频率最高的 1-3 个类别作为 AI 标签

预定义词库涵盖: 审计、财务、合同、租赁、税务、股权、报表、审核、OCR、自动化等

- [ ] **步骤 3: 提交**

---

### 任务 5: 主导入命令

**文件:**
- 修改: `work-db/main.py`（本次任务只实现 import 命令）

- [ ] **步骤 1: 实现 import 命令入口**

```python
# main.py - import 子命令
def cmd_import(args):
    conn = get_connection()
    init_db()
    since = get_import_timestamp(conn)
    
    codex_count = import_codex_sessions(conn, config["codex_sessions_path"], config.get("codex_archived_path"), since)
    claude_count = import_claude_sessions(conn, config["claude_projects_path"], since)
    
    save_import_timestamp(conn)
    print(f"导入完成: Codex {codex_count} 会话, Claude {claude_count} 会话")
```

命令行入口:
```
python main.py import              # 全量导入（首次）
python main.py import --incremental  # 增量导入
```

- [ ] **步骤 2: 进度显示**

导入过程中每处理 20 个文件打印一次进度

- [ ] **步骤 3: 测试全量导入**

先试用增量模式（只导入近期会话），验证入库数据正确

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py import --incremental
```

预期输出: 导入进度和完成统计

- [ ] **步骤 4: 验证入库数据**

```bash
py -c "import sqlite3; c=sqlite3.connect('work.db'); print('sessions:', c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]); print('messages:', c.execute('SELECT COUNT(*) FROM messages').fetchone()[0]); print('topics:', c.execute('SELECT COUNT(*) FROM topics').fetchone()[0])"
```

预期输出: 三条计数

- [ ] **步骤 5: 提交**

---

### 任务 6: 查询模块

**文件:**
- 创建: `work-db/query.py`

- [ ] **步骤 1: 实现全文搜索**

使用 FTS5 全文索引搜索 messages 表：

```python
def search_sessions(conn, keyword, project=None, topic=None, from_date=None, to_date=None, limit=20):
    """自然语言查询会话，支持多种过滤条件组合"""
```

- [ ] **步骤 2: 实现查询结果格式化**

返回格式:
```
会话: <session_id>
来源: <source> | 项目: <project> | 模型: <model>
时间: <started_at> → <ended_at>
消息数: <count> | 标签: <topic1>, <topic2>
摘要: <summary>
---
```

加 `--detail` 则显示每条消息内容（截取前 500 字符）

- [ ] **步骤 3: 注册查询命令**

```python
# main.py 中添加
def cmd_query(args):
    results = search_sessions(conn, args.query, ...)
    for r in results:
        print(format_session(r))
```

命令行用法:
```
python main.py query "租赁审核"
python main.py query "2025年合同" --detail
python main.py query --topic "审计复核"
```

- [ ] **步骤 4: 测试查询**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py query "合同"
```

预期输出: 匹配的会话列表

- [ ] **步骤 5: 提交**

---

### 任务 7: 分析模块

**文件:**
- 创建: `work-db/analyze.py`

- [ ] **步骤 1: 高频项目和任务分析**

```python
def analyze_projects(conn):
    """按会话量统计项目排名"""

def analyze_topics(conn):
    """统计各类标签的会话分布"""

def analyze_often(conn):
    """按月份统计会话量趋势"""
```

- [ ] **步骤 2: 规则提炼**

搜索会话内容中跟 `CLAUDE.md` 配置相关的高频模式，输出建议。

```python
def analyze_rules(conn):
    """
    输出分类:
    1. 高频项目 TOP10
    2. 主题分布（各类标签占比）
    3. 月度趋势
    4. 建议写入 CLAUDE.md 的规则（如适用）
    """
```

- [ ] **步骤 3: 注册分析命令**

```python
# main.py 中添加
def cmd_analyze(args):
    print(analyze_projects(conn))
    print(analyze_topics(conn))
    print(analyze_rules(conn))
```

命令行用法:
```
python main.py analyze
```

- [ ] **步骤 4: 测试分析**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py analyze
```

预期输出: 结构化的分析报告

- [ ] **步骤 5: 提交**

---

### 任务 8: 完整 CLI 入口 + MCP 配置

**文件:**
- 创建: `work-db/main.py`（完整版，整合所有子命令）

- [ ] **步骤 1: 完善 main.py**

整合 argparse 子命令，支持:
```
python main.py import [--incremental]
python main.py query <关键词> [--topic <标签>] [--project <项目>] [--from <日期>] [--to <日期>] [--detail]
python main.py analyze
python main.py stats               # 数据库概览
```

`stats` 命令输出数据库概览:
```
work-db 概览
================
总计会话: XXX
总计消息: XXX
数据跨度: 2025-01-01 ~ 2026-05-29
来源分布: Codex XX 会话 | Claude XX 会话
项目数量: XX
标签数量: XX
```

- [ ] **步骤 2: 配置 MCP 工具**

添加到 `d:\BaiduSyncdisk\claude\.claude\settings.local.json`:

```json
{
  "mcpServers": {
    "work-db": {
      "type": "command",
      "command": "py",
      "args": ["d:\\BaiduSyncdisk\\claude\\work-db\\main.py", "mcp"],
      "description": "工作记录数据库，查询和分析历史工作记录"
    }
  }
}
```

- [ ] **步骤 3: 实现 MCP 模式**

在 main.py 中增加 mcp 子命令，输出 MCP 协议格式的 JSON，暴露两个工具:
- `query_work_history` — 查询历史工作记录
- `analyze_work_patterns` — 分析工作模式

- [ ] **步骤 4: 测试 MCP 模式**

验证 MCP 模式输出正确

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py mcp --list-tools
```

预期输出: 列出 MCP 工具及参数

- [ ] **步骤 5: 全量导入**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py import
```

预期输出: 导入进度 + Codex 和 Claude 会话数统计

- [ ] **步骤 6: 提交**

---

### 任务 9: 验证与收尾

- [ ] **步骤 1: 执行查询测试**

```bash
cd d:/BaiduSyncdisk/claude/work-db
py main.py query "合同审核"
py main.py query "租赁"
py main.py stats
py main.py analyze
```

所有命令正常输出。

- [ ] **步骤 2: 清理测试临时文件**

删除测试过程中产生的临时 db 文件，只保留 `work.db`
