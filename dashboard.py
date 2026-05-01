"""
Trading Dashboard — Streamlit orchestrator.

Composes the UI from the `ui/` package. Each ui/* module owns one section.
Set TRADER_ADVISOR_DEMO_MODE=true to enable demo/portfolio mode (hero, BYOK, hidden internals).
"""
import os
import sys
import pandas as pd
import streamlit as st

from db import init_db, get_runs, get_status

from ui import (
    status_banner,
    ticker_management,
    data_sources,
    master_table,
    run_queue,
    earnings_calendar,
    dd_header,
    dd_metadata,
    dd_price_chart,
    dd_analysis,
    dd_insider,
    dd_options,
    dd_sentiment,
    dd_reddit,
    dd_news,
    hero,
)
from ui.demo import DEMO_MODE, DEMO_TICKERS

from streamlit_autorefresh import st_autorefresh


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


# Demo mode: bind a per-session ephemeral DB before the first DB call.
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

if DEMO_MODE:
    hero.render()
else:
    st.title("📈 Trading Analysis Dashboard")


managed_tickers = DEMO_TICKERS if DEMO_MODE else load_tickers()
all_runs = get_runs(limit=1000)
df = pd.DataFrame(all_runs) if all_runs else pd.DataFrame()
status = get_status()

if status["status"] == "running":
    st_autorefresh(interval=3000, key="job_poll")


if st.session_state.get("clear_queue"):
    for t in managed_tickers:
        st.session_state[f"chk_{t}"] = False
    st.session_state["clear_queue"] = False

if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = managed_tickers[0] if managed_tickers else None

status_banner.render(status, demo_mode=DEMO_MODE)

if not DEMO_MODE:
    st.divider()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickers Tracked", len(managed_tickers))
    if not df.empty:
        col2.metric("Total Runs", len(df))
        col3.metric("Total Tokens", f"{df['total_tokens'].sum():,}")
        col4.metric("Est. Cost (Sonnet)", f"${df['cost_sonnet'].sum():.4f}")
    else:
        col2.metric("Total Runs", 0)
        col3.metric("Total Tokens", 0)
        col4.metric("Est. Cost (Sonnet)", "$0.00")

    st.divider()

ticker_management.render(managed_tickers, save_tickers, demo_mode=DEMO_MODE)

st.divider()

data_sources.render()

st.divider()

master_table.render(managed_tickers, df, status)

if not DEMO_MODE:
    st.divider()
    run_queue.render(managed_tickers, status, PROJECT_ROOT, PYTHON_BIN, RUNNER_PATH)

st.divider()

earnings_calendar.render(managed_tickers)


ticker_pick = st.session_state.selected_ticker

if ticker_pick and not df.empty:
    dd_header.maybe_scroll()
    st.subheader(f"Deep Dive — {ticker_pick}")

    ticker_runs_all = df[df["ticker"] == ticker_pick].sort_values("id", ascending=False)
    if ticker_runs_all.empty:
        st.info(f"No runs yet for {ticker_pick}.")
    else:
        row, ticker_runs = dd_header.select_run(ticker_runs_all)
        if row is not None:
            from ui.formatters import color_decision
            st.markdown("**Run History**")
            history_cols = ["run_date", "mode", "decision", "total_tokens",
                            "cost_sonnet", "runtime_seconds", "model"]
            if DEMO_MODE and "is_demo_template" in ticker_runs.columns:
                ticker_runs = ticker_runs.copy()
                ticker_runs["source"] = ticker_runs["is_demo_template"].apply(
                    lambda v: "📦 Demo" if v else "🟢 Yours"
                )
                history_cols = ["source"] + history_cols
            history = ticker_runs[history_cols]
            st.dataframe(
                history.style.map(color_decision, subset=["decision"]),
                width="stretch",
                hide_index=True,
            )

            st.divider()

            col_left, col_right = st.columns([1, 4])
            with col_left:
                dd_metadata.render(row)
            with col_right:
                dd_price_chart.render(ticker_pick)

            st.divider()
            dd_analysis.render(row)

            dd_insider.render(ticker_pick)

            st.divider()
            dd_options.render(ticker_pick)

            st.divider()
            dd_sentiment.render(ticker_pick)

            st.divider()
            dd_reddit.render(ticker_pick)

            st.divider()
            dd_news.render(ticker_pick)
