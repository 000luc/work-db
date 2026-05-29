import sqlite3
import os
import json
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = None


def set_db_path(path):
    global DB_PATH
    DB_PATH = path


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)) or ".", exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
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

            CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
            CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
            CREATE INDEX IF NOT EXISTS idx_topics_session ON topics(session_id);
            CREATE INDEX IF NOT EXISTS idx_topics_topic ON topics(topic);

            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        """)

        try:
            conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, content=messages, content_rowid=id
                );
            """)
        except sqlite3.OperationalError:
            pass


def save_import_timestamp(conn, source=None):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO import_meta (key, value) VALUES (?, ?)",
        (f"last_import_{source}" if source else "last_import", now)
    )


def get_import_timestamp(conn, source=None):
    row = conn.execute(
        "SELECT value FROM import_meta WHERE key=?",
        (f"last_import_{source}" if source else "last_import",)
    ).fetchone()
    return row["value"] if row else None


def ensure_import_meta_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
