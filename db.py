import sqlite3
import os
import json
import threading
from datetime import datetime

DEFAULT_DB_PATH = "~/.tradingagents/trading.db"
DEFAULT_STATUS_FILE = "~/.tradingagents/run_status.json"

_local = threading.local()


def set_session_paths(db_path, status_file):
    """Bind per-thread DB and status paths.

    Used by the Streamlit dashboard in demo mode so each browser session
    gets its own ephemeral DB without clobbering siblings via os.environ.
    Streamlit serves each session in its own thread, so threading.local
    is the right scope.
    """
    _local.db_path = db_path
    _local.status_file = status_file


def db_path():
    """Effective DB path. Thread-local override > env var > default."""
    p = getattr(_local, "db_path", None)
    if p:
        return p
    return os.path.expanduser(os.getenv("MOOSE_DB_PATH", DEFAULT_DB_PATH))


def status_file():
    """Effective run-status file. Thread-local override > env var > default."""
    p = getattr(_local, "status_file", None)
    if p:
        return p
    return os.path.expanduser(os.getenv("MOOSE_STATUS_FILE", DEFAULT_STATUS_FILE))


# Back-compat aliases (some external scripts may import these)
DB_PATH = os.path.expanduser(DEFAULT_DB_PATH)
STATUS_FILE = os.path.expanduser(DEFAULT_STATUS_FILE)


def init_db():
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            run_date TEXT NOT NULL,
            decision TEXT,
            analysis TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            cost_sonnet REAL,
            cost_opus REAL,
            cost_gemini REAL,
            cost_openai REAL,
            mode TEXT DEFAULT 'core',
            runtime_seconds REAL,
            model TEXT,
            host TEXT,
            extra TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ticker_date ON runs(ticker, run_date)")

    # Add `extra` column if upgrading from older schema
    cols = [r[1] for r in cur.execute("PRAGMA table_info(runs)").fetchall()]
    if "extra" not in cols:
        cur.execute("ALTER TABLE runs ADD COLUMN extra TEXT")
    if "cost_openai" not in cols:
        cur.execute("ALTER TABLE runs ADD COLUMN cost_openai REAL")
    if "is_demo_template" not in cols:
        cur.execute("ALTER TABLE runs ADD COLUMN is_demo_template INTEGER DEFAULT 0")

    # Migrate simple → solo
    cur.execute("UPDATE runs SET mode='solo' WHERE mode='simple'")

    conn.commit()
    conn.close()


def save_run(ticker, run_date, decision, analysis, prompt_tokens, completion_tokens,
             mode="core", runtime_seconds=0, model="unknown", host="unknown", extra=None,
             is_demo_template=False):
    total = prompt_tokens + completion_tokens
    cost_sonnet = prompt_tokens / 1e6 * 3 + completion_tokens / 1e6 * 15        # Sonnet 4.6
    cost_opus = prompt_tokens / 1e6 * 5 + completion_tokens / 1e6 * 25          # Opus 4.6
    cost_gemini = prompt_tokens / 1e6 * 2 + completion_tokens / 1e6 * 12        # Gemini 3.1 Pro
    cost_openai = prompt_tokens / 1e6 * 2.5 + completion_tokens / 1e6 * 15      # GPT-5.4
    extra_json = json.dumps(extra) if extra else None

    conn = sqlite3.connect(db_path())
    conn.execute("""
        INSERT INTO runs (
            ticker, run_date, decision, analysis,
            prompt_tokens, completion_tokens, total_tokens,
            cost_sonnet, cost_opus, cost_gemini, cost_openai,
            mode, runtime_seconds, model, host, extra, is_demo_template
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker, run_date, decision, analysis,
        prompt_tokens, completion_tokens, total,
        cost_sonnet, cost_opus, cost_gemini, cost_openai,
        mode, runtime_seconds, model, host, extra_json,
        1 if is_demo_template else 0,
    ))
    conn.commit()
    conn.close()


def get_runs(ticker=None, limit=50):
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    if ticker:
        rows = conn.execute(
            "SELECT * FROM runs WHERE ticker=? ORDER BY run_date DESC LIMIT ?",
            (ticker, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY run_date DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest(ticker):
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM runs WHERE ticker=? ORDER BY run_date DESC LIMIT 1",
        (ticker,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_status(status: str, tickers: list = None, current: str = None,
               mode: str = None, completed: int = 0, pid: int = None):
    existing = get_status()
    started_at = existing.get("started_at") if status == "running" and existing.get("status") == "running" else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(tickers) if tickers else 0
    data = {
        "status": status,
        "tickers": tickers or [],
        "current": current or "",
        "mode": mode or "",
        "completed": completed,
        "total": total,
        "pid": pid or existing.get("pid"),
        "started_at": started_at
    }
    path = status_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def get_status():
    path = status_file()
    if not os.path.exists(path):
        return {"status": "idle", "tickers": [], "current": "", "mode": ""}
    try:
        with open(path) as f:
            data = json.load(f)
    except:
        return {"status": "idle", "tickers": [], "current": "", "mode": ""}

    # Self-heal: if status says running but PID is dead, mark idle
    if data.get("status") == "running":
        pid = data.get("pid")
        if pid and not _pid_alive(pid):
            data["status"] = "idle"
            with open(path, "w") as f:
                json.dump(data, f)
    return data


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False