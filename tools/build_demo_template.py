"""Build demo_template.db from your local trading.db.

Usage:
    python tools/build_demo_template.py

What it does:
- Reads ~/.tradingagents/trading.db (your local journal).
- For each demo ticker keeps at most ONE run per (mode, run_date).
- When a (mode, run_date) has multiple candidates, prefers Gemini-powered
  runs (model LIKE '%gemini%') over anything else; ties go to the latest id.
- Tags every kept row with is_demo_template=1 and host='demo' (strips
  machine-specific host info that could leak into the UI).
- Writes demo_template.db at the repo root.

Commit demo_template.db to ship pre-populated content to the HF Space.
The dashboard copies this file into each new visitor's session DB so the
UI is full of content on first paint.
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = os.path.expanduser("~/.tradingagents/trading.db")
DST = REPO / "demo_template.db"

# Keep these in sync with ui/demo.py::DEMO_TICKERS
DEMO_TICKERS = ["NVDA", "MSFT", "AAPL", "GOOGL", "TSLA", "AMD", "AMZN", "META"]


def main():
    if not os.path.exists(SRC):
        print(f"Source DB not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    if DST.exists():
        DST.unlink()

    shutil.copy(SRC, DST)

    conn = sqlite3.connect(DST)
    cur = conn.cursor()

    cols = [r[1] for r in cur.execute("PRAGMA table_info(runs)").fetchall()]
    if "is_demo_template" not in cols:
        cur.execute("ALTER TABLE runs ADD COLUMN is_demo_template INTEGER DEFAULT 0")

    placeholders = ",".join("?" * len(DEMO_TICKERS))
    # Keep the "best" run per (ticker, mode, run_date):
    #   - rank 0: model contains 'gemini' (case-insensitive)
    #   - rank 1: anything else
    #   - tie-break by latest id
    # SQLite has had window functions since 3.25 (2018).
    cur.execute(
        f"""
        DELETE FROM runs
        WHERE ticker NOT IN ({placeholders})
           OR id NOT IN (
               SELECT id FROM (
                   SELECT id, ROW_NUMBER() OVER (
                       PARTITION BY ticker, mode, run_date
                       ORDER BY
                           CASE
                               WHEN LOWER(COALESCE(model, '')) LIKE '%gemini%' THEN 0
                               ELSE 1
                           END,
                           id DESC
                   ) AS rn
                   FROM runs
                   WHERE ticker IN ({placeholders})
               )
               WHERE rn = 1
           )
        """,
        DEMO_TICKERS + DEMO_TICKERS,
    )

    cur.execute("UPDATE runs SET is_demo_template = 1, host = 'demo'")

    conn.commit()
    kept = cur.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.execute("VACUUM")
    conn.close()

    size_kb = DST.stat().st_size / 1024
    print(f"Wrote {DST} ({kept} rows, {size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
