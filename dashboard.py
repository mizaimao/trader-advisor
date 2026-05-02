"""Trading Dashboard — three-tab layout.

Tab 1: 🎯 Overview      — 90-second view (compact hero + master table + featured runs)
Tab 2: 🔍 Run Explorer  — drill into one historical run
Tab 3: ⚙️ About & Setup — technical details + clone instructions + operational controls

Demo banner stays above the tabs (app-level context that applies everywhere).
Set TRADER_ADVISOR_DEMO_MODE=true for demo/portfolio mode.
"""
import os
import sys

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from db import init_db, get_runs, get_status
from ui import (
    status_banner,
    overview_tab,
    run_explorer_tab,
    about_tab,
)
from ui.demo import DEMO_MODE, DEMO_TICKERS


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON_BIN = sys.executable
RUNNER_PATH = os.path.join(PROJECT_ROOT, "runner.py")
TICKERS_FILE = os.path.expanduser("~/.tradingagents/tickers.txt")


def load_tickers():
    if not os.path.exists(TICKERS_FILE):
        return ["NVDA"]
    with open(TICKERS_FILE) as f:
        return [t.strip().upper() for t in f.readlines() if t.strip()]


def save_tickers(tickers):
    os.makedirs(os.path.dirname(TICKERS_FILE), exist_ok=True)
    with open(TICKERS_FILE, "w") as f:
        f.write("\n".join(tickers))


# ── Bootstrap ────────────────────────────────────────────────────────────────
if DEMO_MODE:
    from ui.demo_session import bootstrap as _bootstrap_demo_session
    _bootstrap_demo_session()
else:
    os.makedirs(os.path.dirname(TICKERS_FILE), exist_ok=True)

init_db()

st.set_page_config(
    page_title="trader-advisor" if DEMO_MODE else "Trading Dashboard",
    layout="wide",
)

# ── App-level banner (above all tabs in demo) ───────────────────────────────
if DEMO_MODE:
    st.warning(
        "🔒 **Demo Mode — Live runs are disabled here for two reasons:** "
        "(1) the system requires multiple API keys (Finnhub, Alpha Vantage, "
        "plus an LLM provider) which makes BYOK impractical for browser "
        "visitors, and (2) Streamlit's rerun-on-interaction model conflicts "
        "with the live BYOK input flow. The full UI is intentionally visible "
        "so you can see the system's capabilities. Pre-loaded analyses below "
        "are fully browseable. To run this yourself, see the "
        "[GitHub repo](https://github.com/mizaimao/trader-advisor) — clone, "
        "drop your keys in `.env`, and `streamlit run dashboard.py`."
    )

# ── Data ─────────────────────────────────────────────────────────────────────
managed_tickers = DEMO_TICKERS if DEMO_MODE else load_tickers()
all_runs = get_runs(limit=1000)
df = pd.DataFrame(all_runs) if all_runs else pd.DataFrame()
status = get_status()

if status["status"] == "running":
    st_autorefresh(interval=3000, key="job_poll")

# Status banner sits above the tabs (running/idle is global app state).
status_banner.render(status, demo_mode=DEMO_MODE)

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_runs, tab_about = st.tabs([
    "🎯 Overview",
    "🔍 Run Explorer",
    "⚙️ About & Setup",
])

with tab_overview:
    overview_tab.render(managed_tickers, df, status)

with tab_runs:
    run_explorer_tab.render(managed_tickers, df, status)

with tab_about:
    about_tab.render(
        managed_tickers, df, save_tickers, status,
        PROJECT_ROOT, PYTHON_BIN, RUNNER_PATH,
    )
