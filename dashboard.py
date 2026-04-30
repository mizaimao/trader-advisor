"""
Trading Dashboard — Streamlit orchestrator.

Composes the UI from the `ui/` package. Each ui/* module owns one section.
"""
import os
import pandas as pd
import streamlit as st

from db import init_db, get_runs, get_status

from ui import (
    status_banner,
    ticker_management,
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
    dd_news,
)


# ── PATHS ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.expanduser("~/moose-trader")
PYTHON_BIN = os.path.join(PROJECT_ROOT, ".venv/bin/python")
RUNNER_PATH = os.path.join(PROJECT_ROOT, "runner.py")

TICKERS_FILE = os.path.expanduser("~/.tradingagents/tickers.txt")
os.makedirs(os.path.dirname(TICKERS_FILE), exist_ok=True)


def load_tickers():
    if not os.path.exists(TICKERS_FILE):
        return ["NVDA"]
    with open(TICKERS_FILE) as f:
        return [t.strip().upper() for t in f.readlines() if t.strip()]


def save_tickers(tickers):
    with open(TICKERS_FILE, "w") as f:
        f.write("\n".join(tickers))


# ── PAGE SETUP ────────────────────────────────────────────────────────────────
init_db()
st.set_page_config(page_title="Trading Dashboard", layout="wide")
st.title("📈 Trading Analysis Dashboard")


# ── DATA LOAD ─────────────────────────────────────────────────────────────────
managed_tickers = load_tickers()
all_runs = get_runs(limit=1000)
df = pd.DataFrame(all_runs) if all_runs else pd.DataFrame()
status = get_status()


# ── SESSION STATE ─────────────────────────────────────────────────────────────
# Clear queue flag must run before widgets render
if st.session_state.get("clear_queue"):
    for t in managed_tickers:
        st.session_state[f"chk_{t}"] = False
    st.session_state["clear_queue"] = False

if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = managed_tickers[0] if managed_tickers else None


# ── TOP SECTIONS ──────────────────────────────────────────────────────────────
status_banner.render(status)

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

ticker_management.render(managed_tickers, save_tickers)

st.divider()

master_table.render(managed_tickers, df, status)

st.divider()

run_queue.render(managed_tickers, status, PROJECT_ROOT, PYTHON_BIN, RUNNER_PATH)

st.divider()

earnings_calendar.render(managed_tickers)


# ── DEEP DIVE ─────────────────────────────────────────────────────────────────
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
            history = ticker_runs[["run_date", "mode", "decision", "total_tokens",
                                   "cost_sonnet", "runtime_seconds", "model"]]
            st.dataframe(
                history.style.map(color_decision, subset=["decision"]),
                use_container_width=True,
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
            dd_news.render(ticker_pick)
