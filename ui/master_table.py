"""The master ticker overview table — checkbox + ticker + earn + insider + 3 mode columns.

Solo runs are hidden from this overview to reduce visual clutter — they're still
queryable via the deep-dive run picker, runnable from the Run Queue, and stored
in the same DB. The three modes shown here are the more "interesting" ones for
quick comparison: core (adversarial panel), agent (tool-use loop), full (7-agent
debate). Order: core → agent → full, roughly by typical runtime.
"""
import pandas as pd
import streamlit as st

from .cache import days_until_earnings_cached, insider_summary_cached
from .formatters import (
    color_decision,
    earnings_color,
    earnings_label,
    insider_color,
    insider_label,
    relative_time,
    time_color,
)


TABLE_MODES = ["core", "agent", "full"]

# Layout: [check, ticker, earn, insider, {core,last,time}, {agent,last,time}, {full,last,time}, →]
# Back to the wider 1.5/1.3/0.8 per triple now that we're at 3 modes.
COL_WEIGHTS = [
    0.4, 1.1, 0.8, 1.4,
    1.5, 1.3, 0.8,
    1.5, 1.3, 0.8,
    1.5, 1.3, 0.8,
    0.5,
]
HEADERS = [
    "☐", "Ticker", "Earn", "Insider",
    "Core", "Last", "Time",
    "Agent", "Last", "Time",
    "Full", "Last", "Time",
    "→",
]


def build_master_df(managed_tickers, df):
    """Build the per-ticker summary DataFrame: latest run per mode + earnings + insider."""
    rows = []
    for ticker in managed_tickers:
        row = {"ticker": ticker}
        try:
            row["earnings_days"] = days_until_earnings_cached(ticker)
        except Exception:
            row["earnings_days"] = None
        try:
            row["insider"] = insider_summary_cached(ticker)
        except Exception:
            row["insider"] = None

        for mode in TABLE_MODES:
            if not df.empty:
                match = df[(df["ticker"] == ticker) & (df["mode"] == mode)]
                if not match.empty:
                    latest = match.sort_values("run_date").iloc[-1]
                    row[f"{mode}_decision"] = latest["decision"]
                    row[f"{mode}_date"] = latest["run_date"]
                    row[f"{mode}_runtime"] = latest.get("runtime_seconds", 0)
                    row[f"{mode}_model"] = latest.get("model", "—")
                    continue
            row[f"{mode}_decision"] = "—"
            row[f"{mode}_date"] = None
            row[f"{mode}_runtime"] = 0
            row[f"{mode}_model"] = "—"
        rows.append(row)

    return pd.DataFrame(rows)


def render(managed_tickers, df, status):
    st.subheader("Ticker Overview")

    col_selall, col_clrall, _ = st.columns([1, 1, 6])
    if col_selall.button("☑ Select All"):
        for t in managed_tickers:
            st.session_state[f"chk_{t}"] = True
        st.rerun()
    if col_clrall.button("☐ Clear All"):
        for t in managed_tickers:
            st.session_state[f"chk_{t}"] = False
        st.rerun()

    master_df = build_master_df(managed_tickers, df)

    header_cols = st.columns(COL_WEIGHTS)
    for col, label in zip(header_cols, HEADERS):
        col.markdown(f"**{label}**")

    for _, row in master_df.iterrows():
        ticker = row["ticker"]
        is_running = status["status"] == "running" and status["current"] == ticker
        cols = st.columns(COL_WEIGHTS)

        cols[0].checkbox("q", key=f"chk_{ticker}", label_visibility="hidden")

        label = f"⚙️ {ticker}" if is_running else ticker
        if cols[1].button(label, key=f"tk_{ticker}", width="stretch"):
            st.session_state.selected_ticker = ticker
            st.session_state["scroll_to_deep_dive"] = True
            st.rerun()

        edays = row.get("earnings_days")
        cols[2].markdown(
            f'<span style="{earnings_color(edays)}">{earnings_label(edays)}</span>',
            unsafe_allow_html=True,
        )

        insider = row.get("insider")
        cols[3].markdown(
            f'<span style="{insider_color(insider)}" title="{insider or "no recent activity"}">{insider_label(insider)}</span>',
            unsafe_allow_html=True,
        )

        # Core / Agent / Full triples (solo intentionally omitted; reachable
        # via deep-dive run picker, still runnable via the Run Queue.)
        for offset, mode in zip((4, 7, 10), TABLE_MODES):
            decision = row[f"{mode}_decision"]
            date_val = row[f"{mode}_date"]
            runtime = row[f"{mode}_runtime"]
            cols[offset].markdown(
                f'<span style="{color_decision(decision)};padding:2px 6px;border-radius:4px">{decision}</span>',
                unsafe_allow_html=True,
            )
            cols[offset + 1].markdown(
                f'<span style="{time_color(date_val)}">{relative_time(date_val)}</span>',
                unsafe_allow_html=True,
            )
            runtime_str = f"{runtime}s" if runtime else "—"
            cols[offset + 2].markdown(
                f'<span style="color:#888">{runtime_str}</span>',
                unsafe_allow_html=True,
            )

        if cols[13].button("→", key=f"view_{ticker}"):
            st.session_state.selected_ticker = ticker
            st.session_state["scroll_to_deep_dive"] = True
            st.rerun()
