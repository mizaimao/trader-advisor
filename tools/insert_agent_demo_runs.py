"""Import recent agent-mode runs from local trading.db into demo_template.db.

Usage:
    python tools/insert_agent_demo_runs.py                # default: last 10 agent runs
    python tools/insert_agent_demo_runs.py --limit 15     # custom limit
    python tools/insert_agent_demo_runs.py --dry-run      # preview without writing

What it does:
- Reads `mode='agent'` rows from ~/.tradingagents/trading.db (newest first)
- Idempotent: deletes any existing agent rows in demo_template.db first
- Inserts the source rows with `host='demo'` + `is_demo_template=1`
- Vacuums the dest DB to keep file size sane

Goal: every demo ticker that has core/full demo runs also gets at least
one agent run, so the master table's Agent column isn't all "—".

Re-runnable: safe to invoke repeatedly. Each invocation replaces the demo
agent runs with whatever's currently in your local DB. Commit
demo_template.db after the script reports success.
"""
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = os.path.expanduser("~/.tradingagents/trading.db")
DST = REPO / "demo_template.db"

DEFAULT_LIMIT = 10


def main():
    limit = DEFAULT_LIMIT
    dry_run = False
    args = sys.argv[1:]
    if "--dry-run" in args:
        dry_run = True
        args.remove("--dry-run")
    if "--limit" in args:
        idx = args.index("--limit")
        try:
            limit = int(args[idx + 1])
        except (IndexError, ValueError):
            print("ERROR: --limit needs an integer argument", file=sys.stderr)
            sys.exit(1)

    if not os.path.exists(SRC):
        print(f"Source DB not found: {SRC}", file=sys.stderr)
        sys.exit(1)
    if not DST.exists():
        print(f"Dest DB not found: {DST}", file=sys.stderr)
        sys.exit(1)

    # Read source agent runs (newest first). Skip:
    #   - rows without a trace (would render as empty trace cards)
    #   - rows where decision parsed as UNKNOWN (model didn't emit a clean
    #     "FINAL DECISION:" line — usually a forced-finalize artifact under
    #     a too-tight token cap; results in "UNKNOWN" badge in the demo)
    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT * FROM runs "
        "WHERE mode='agent' "
        "  AND extra IS NOT NULL "
        "  AND decision IS NOT NULL "
        "  AND decision != '' "
        "  AND decision != 'UNKNOWN' "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    src.close()

    if not rows:
        print(f"No agent runs found in {SRC}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(rows)} agent run(s) to import:")
    for r in rows:
        runtime = r["runtime_seconds"] or 0
        decision = r["decision"] or "—"
        print(
            f"  {r['ticker']:6} | {r['run_date']} | {decision:11} "
            f"| {runtime:5.1f}s | {r['model']}"
        )

    if dry_run:
        print("\n--dry-run: would import the above into demo_template.db")
        return

    dst = sqlite3.connect(DST)
    cur = dst.cursor()

    # Make sure dest has the columns we need (idempotent migrations matching db.py)
    cols = {r[1] for r in cur.execute("PRAGMA table_info(runs)").fetchall()}
    for col, decl in [
        ("extra", "TEXT"),
        ("cost_openai", "REAL"),
        ("is_demo_template", "INTEGER DEFAULT 0"),
    ]:
        if col not in cols:
            cur.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")

    # Idempotent: clear existing demo agent rows before inserting fresh ones
    deleted = cur.execute(
        "DELETE FROM runs WHERE mode='agent' AND is_demo_template=1"
    ).rowcount
    if deleted:
        print(f"\nDeleted {deleted} existing demo agent run(s) (idempotent re-run)")

    inserted = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO runs (
                ticker, run_date, decision, analysis,
                prompt_tokens, completion_tokens, total_tokens,
                cost_sonnet, cost_opus, cost_gemini, cost_openai,
                mode, runtime_seconds, model, host, extra,
                created_at, is_demo_template
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["ticker"], r["run_date"], r["decision"], r["analysis"],
                r["prompt_tokens"], r["completion_tokens"], r["total_tokens"],
                r["cost_sonnet"], r["cost_opus"], r["cost_gemini"],
                r["cost_openai"],
                r["mode"], r["runtime_seconds"], r["model"], "demo",
                r["extra"], r["created_at"], 1,
            ),
        )
        inserted += 1

    dst.commit()
    dst.execute("VACUUM")
    dst.close()

    size_kb = DST.stat().st_size / 1024
    print(f"\n✓ Inserted {inserted} agent run(s) into {DST} ({size_kb:.1f} KB)")
    print("\nNext: commit demo_template.db. If JPM / PFE / ONDS aren't in")
    print("ui/demo.py:DEMO_TICKERS, they won't show in the master table —")
    print("expand DEMO_TICKERS if you want them visible.")


if __name__ == "__main__":
    main()