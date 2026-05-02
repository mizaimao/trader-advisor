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
from ui.run_modal import run_analysis_modal
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

# Custom CSS for the dashboard:
#  - Tabs styled as clear primary navigation (was nearly invisible on default).
#    Tabs now look like pill-buttons with strong active-state contrast and
#    a hover background so visitors actually see they're clickable.
#  - Dividers and expanders get halved vertical margins so foldables stack
#    tightly instead of leaving big white gaps.
st.markdown(
    """<style>
    /* Tabs — make them look like clickable navigation */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 2px solid rgba(255,255,255,0.10);
        margin-bottom: 14px;
    }
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 20px;
        font-weight: 500;
        letter-spacing: 0.6px;
        padding: 14px 26px;
        background: rgba(255,255,255,0.03);
        border-radius: 8px 8px 0 0;
        border-bottom: 3px solid transparent !important;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
    }
    .stTabs [data-baseweb="tab-list"] button:hover {
        background: rgba(255,255,255,0.08);
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        font-weight: 600;
        background: rgba(122,184,245,0.14);
        color: #7ab8f5 !important;
        border-bottom-color: #7ab8f5 !important;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] p {
        color: #7ab8f5 !important;
    }

    /* Halve divider gap (default ~16px each side → 8px) */
    hr {
        margin-top: 8px !important;
        margin-bottom: 8px !important;
    }

    /* Tighter expander spacing — Streamlit renders expanders as <details> */
    details {
        margin-bottom: 6px !important;
    }
    </style>""",
    unsafe_allow_html=True,
)

# ── Data (computed before the top strip so the modal can reuse it) ─────────
managed_tickers = DEMO_TICKERS if DEMO_MODE else load_tickers()
all_runs = get_runs(limit=1000)
df = pd.DataFrame(all_runs) if all_runs else pd.DataFrame()
status = get_status()

if status["status"] == "running":
    st_autorefresh(interval=3000, key="job_poll")

# ── App-level top strip: banner (left) + Run Analysis button (right) ───────
# The button is persistent across all tabs (rendered above the st.tabs call).
# Clicking it opens the run-config modal regardless of which tab is active.
banner_col, action_col = st.columns([5, 1])

with banner_col:
    if DEMO_MODE:
        st.info(
            "🔒 **Demo mode** — runs are pre-loaded. The full UI is shown so "
            "you can see what the system does; live runs are disabled because "
            "the agent needs Finnhub, Alpha Vantage, and an LLM key (browser "
            "BYOK won't fit). To run live, clone the "
            "[GitHub repo](https://github.com/mizaimao/trader-advisor) and add "
            "your keys to `.env`."
        )

with action_col:
    # Vertical spacer so the button visually aligns with the banner content.
    if DEMO_MODE:
        st.write("")
    if st.button(
        "⚡ Run Analysis",
        type="primary",
        use_container_width=True,
        key="open_run_modal",
    ):
        run_analysis_modal(
            managed_tickers, df, status,
            PROJECT_ROOT, PYTHON_BIN, RUNNER_PATH,
        )

# Status banner sits above the tabs (running/idle is global app state).
status_banner.render(status, demo_mode=DEMO_MODE)

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_runs, tab_about = st.tabs([
    "OVERVIEW",
    "RUN EXPLORER",
    "ABOUT & SETUP",
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

# ── Programmatic tab navigation ─────────────────────────────────────────────
# Streamlit's tabs API has no native "switch to tab N" call. Workaround:
# inject a tiny iframe that runs JS in the parent window, finds the target
# tab button via ARIA role (stable across versions), and clicks it. The
# session_state flag is set by Overview-tab click handlers (master_table
# verdict cells, featured_runs cards) and consumed here on the same rerun.
_TAB_INDEX = {"overview": 0, "run_explorer": 1, "about": 2}
_nav_target = st.session_state.pop("nav_to_tab", None)
if _nav_target in _TAB_INDEX:
    import streamlit.components.v1 as components
    components.html(
        f"""<script>
        const idx = {_TAB_INDEX[_nav_target]};
        const sel = '[role="tab"]';
        function switchTab() {{
            const tabs = window.parent.document.querySelectorAll(sel);
            if (tabs && tabs[idx]) {{
                tabs[idx].click();
                return true;
            }}
            return false;
        }}
        if (!switchTab()) {{
            // Tab list not in DOM yet — retry briefly.
            const t = setInterval(() => {{ if (switchTab()) clearInterval(t); }}, 50);
            setTimeout(() => clearInterval(t), 1000);
        }}
        </script>""",
        height=0,
    )
