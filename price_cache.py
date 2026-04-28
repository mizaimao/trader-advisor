"""
SQLite-based cache for yfinance price data.

Separate from trading.db so schema migrations to the runs table
don't blow away cached price history. Stored at ~/.tradingagents/price_cache.db.
"""
import os
import sqlite3
import json
import pickle
import base64
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/.tradingagents/price_cache.db")

# TTL by granularity (in hours)
TTL_HOURS = {
    "daily": 24,
    "weekly": 24 * 7,
    "monthly": 24 * 30,
}


def _init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            ticker TEXT NOT NULL,
            granularity TEXT NOT NULL,
            cached_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (ticker, granularity)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_at ON price_cache(cached_at)")
    conn.commit()
    conn.close()


def get(ticker, granularity):
    """Returns cached DataFrame or None if missing/expired."""
    _init()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT cached_at, payload FROM price_cache WHERE ticker=? AND granularity=?",
        (ticker, granularity),
    ).fetchone()
    conn.close()
    if not row:
        return None

    cached_at_str, payload = row
    cached_at = datetime.fromisoformat(cached_at_str)
    ttl = TTL_HOURS.get(granularity, 24)
    if datetime.now() - cached_at > timedelta(hours=ttl):
        return None

    try:
        df = pickle.loads(base64.b64decode(payload.encode()))
        return df
    except Exception:
        return None


def put(ticker, granularity, df):
    """Store DataFrame in cache."""
    _init()
    payload = base64.b64encode(pickle.dumps(df)).decode()
    cached_at = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO price_cache (ticker, granularity, cached_at, payload) VALUES (?, ?, ?, ?)",
        (ticker, granularity, cached_at, payload),
    )
    conn.commit()
    conn.close()


def stats():
    """Quick summary of what's cached."""
    _init()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ticker, granularity, cached_at FROM price_cache ORDER BY cached_at DESC"
    ).fetchall()
    conn.close()
    return rows


def clear(ticker=None):
    """Clear cache for one ticker or all."""
    _init()
    conn = sqlite3.connect(DB_PATH)
    if ticker:
        conn.execute("DELETE FROM price_cache WHERE ticker=?", (ticker,))
    else:
        conn.execute("DELETE FROM price_cache")
    conn.commit()
    conn.close()