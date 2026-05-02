"""Master ticker × mode overview table — the central element of the Overview tab.

7 columns: Ticker | Earn | Insider | Solo | Core | Full | Agent

Each verdict cell is a clickable button. Clicking sets session_state hints
(`target_ticker`, `target_mode`) and fires `st.toast` to cue the user to
switch to the Run Explorer tab. Streamlit's tabs API doesn't support
programmatic switching — pre-population + manual switch is the agreed
fallback (per Phase 1 demo refactor spec).

What was dropped vs the prior version:
- Per-row checkboxes (the run queue now uses its own multiselect)
- "Last" / "Time" columns (that detail belongs in Run Explorer)
- "→" arrow button (verdict cells are themselves the nav action)
"""
import pandas as pd
import streamlit as st

from .cache import days_until_earnings_cached, insider_summary_cached
from .formatters import (
    earnings_color,
    earnings_label,
    insider_color,
    insider_label,
)


TABLE_MODES = ["solo", "core", "full", "agent"]

# 7 columns — Ticker (button), Earn, Insider, then 4 mode cells.
COL_WEIGHTS = [1.2, 0.9, 1.5, 1.3, 1.3, 1.3, 1.3]
HEADERS = ["Ticker", "Earn", "Insider", "Solo", "Core", "Full", "Agent"]


def build_master_df(managed_tickers, df):
    """Per-ticker latest-decision-per-mode + earnings + insider summary."""
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
            row[f"{mode}_decision"] = "—"
            if not df.empty:
                match = df[(df["ticker"] == ticker) & (df["mode"] == mode)]
                if not match.empty:
                    latest = match.sort_values("run_date").iloc[-1]
                    row[f"{mode}_decision"] = latest["decision"] or "—"
        rows.append(row)
    return pd.DataFrame(rows)


def _decision_emoji_label(val):
    """Emoji + abbreviated label. Streamlit buttons can't carry pill-style
    background colors cleanly, so the emoji preserves the at-a-glance color
    signal that the prior styled span had."""
    v = str(val).upper().strip()
    if v in ("—", "UNKNOWN", "NAN", "", "NONE"):
        return "—"
    if v == "BUY":
        return "🟢 BUY"
    if v == "OVERWEIGHT":
        return "🟢 OVER"
    if v == "SELL":
        return "🔴 SELL"
    if v == "UNDERWEIGHT":
        return "🔴 UNDER"
    if v == "HOLD":
        return "🟡 HOLD"
    return v[:10]


def render(managed_tickers, df, status):
    st.subheader("Ticker Overview")
    st.caption(
        "Click any cell to open that run in the Run Explorer. "
        "Empty cells (—) are disabled."
    )

    master_df = build_master_df(managed_tickers, df)

    header_cols = st.columns(COL_WEIGHTS)
    for col, label in zip(header_cols, HEADERS):
        col.markdown(f"**{label}**")

    for _, row in master_df.iterrows():
        ticker = row["ticker"]
        is_running = status["status"] == "running" and status["current"] == ticker
        cols = st.columns(COL_WEIGHTS)

        # Ticker — clickable button (sets target_ticker + triggers tab nav)
        ticker_label = f"⚙️ {ticker}" if is_running else ticker
        if cols[0].button(
            ticker_label,
            key=f"tk_{ticker}",
            use_container_width=True,
            help=f"Open {ticker} in the Run Explorer tab",
        ):
            st.session_state["target_ticker"] = ticker
            st.session_state["nav_to_tab"] = "run_explorer"

        # Earn (days to earnings)
        edays = row.get("earnings_days")
        cols[1].markdown(
            f'<span style="{earnings_color(edays)}">{earnings_label(edays)}</span>',
            unsafe_allow_html=True,
        )

        # Insider summary (color-coded)
        insider = row.get("insider")
        cols[2].markdown(
            f'<span style="{insider_color(insider)}" '
            f'title="{insider or "no recent activity"}">'
            f'{insider_label(insider)}</span>',
            unsafe_allow_html=True,
        )

        # 4 mode cells (Solo, Core, Full, Agent) — clickable for nav
        for offset, mode in zip((3, 4, 5, 6), TABLE_MODES):
            decision = row[f"{mode}_decision"]
            label = _decision_emoji_label(decision)
            disabled = label == "—"
            if cols[offset].button(
                label,
                key=f"pill_{ticker}_{mode}",
                help=str(decision),
                use_container_width=True,
                disabled=disabled,
            ):
                st.session_state["target_ticker"] = ticker
                st.session_state["target_mode"] = mode
                st.session_state["nav_to_tab"] = "run_explorer"
