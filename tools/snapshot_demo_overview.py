"""Snapshot the live Overview-tab data sources into a static JSON file.

The HF Space demo runs without a Finnhub API key, so live calls return None
and the master table renders as "—" / "$0". This script captures the live
state on a workstation that *does* have FINNHUB_API_KEY and writes it to
demo_data/overview_snapshot.json. The cached wrappers in ui/cache.py read
from that snapshot when DEMO_MODE=true.

Run before each demo deployment:
    python tools/snapshot_demo_overview.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news import days_until_earnings, get_earnings_calendar_finnhub, insider_summary_text
from ui.demo import DEMO_TICKERS

OUT = ROOT / "demo_data" / "overview_snapshot.json"


def main():
    if not os.environ.get("FINNHUB_API_KEY"):
        print("FINNHUB_API_KEY not set — aborting (snapshot would be empty).")
        sys.exit(1)

    snap = {"earnings_days": {}, "earnings_event": {}, "insider": {}}
    for ticker in DEMO_TICKERS:
        try:
            snap["earnings_days"][ticker] = days_until_earnings(ticker)
        except Exception as e:
            print(f"  ! {ticker} earnings_days failed: {e}")
            snap["earnings_days"][ticker] = None
        try:
            snap["earnings_event"][ticker] = get_earnings_calendar_finnhub(ticker)
        except Exception as e:
            print(f"  ! {ticker} earnings_event failed: {e}")
            snap["earnings_event"][ticker] = None
        try:
            snap["insider"][ticker] = insider_summary_text(ticker)
        except Exception as e:
            print(f"  ! {ticker} insider failed: {e}")
            snap["insider"][ticker] = None
        print(
            f"  {ticker:6s} earn={snap['earnings_days'][ticker]} "
            f"insider={snap['insider'][ticker]!r}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(snap, f, indent=2)
    print(f"\nWrote {OUT} ({len(DEMO_TICKERS)} tickers).")


if __name__ == "__main__":
    main()
