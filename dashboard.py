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

# Tab styling — bump tab labels so they read as primary navigation, not
# secondary clutter. Streamlit's default tab font-size hovers around 14px;
# 17px feels like proper nav. Active-tab gets a thicker bottom-border accent
# and slightly bolder text.
st.markdown(
    """<style>
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 17px;
        padding: 10px 18px;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        font-weight: 600;
        border-bottom-width: 3px;
    }
    .stTabs [data-baseweb="tab-list"] button:hover {
        background: rgba(255,255,255,0.05);
    }
    </style>""",
    unsafe_allow_html=True,
)

# ── App-level banner (above all tabs in demo) ───────────────────────────────
# st.info (blue) reads as informational; st.warning (yellow) was reading as
# apologetic. Demo state isn't a problem to warn about — it's just a fact.
if DEMO_MODE:
    st.info(
        "🔒 **Demo mode** — runs are pre-loaded. The full UI is shown so you "
        "can see what the system does; live runs are disabled because the "
        "agent needs Finnhub, Alpha Vantage, and an LLM key (browser BYOK "
        "won't fit). To run live, clone the "
        "[GitHub repo](https://github.com/mizaimao/trader-advisor) and add "
        "your keys to `.env`."
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
