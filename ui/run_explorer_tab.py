"""Run Explorer tab — drill into one historical run.

Sections (top to bottom):
1. Run selector strip (ticker + run dropdown)
2. Run header strip (verdict pill + mode + model + runtime + tokens + cost)
3. Mode-conditional main content:
     - solo/core/full: dd_analysis (handles core's panel internally)
     - agent: dd_agent_trace timeline first, then dd_analysis
4. Universal data panels (price chart, insider, options, sentiment, reddit, news)
5. Earnings calendar (deprioritized to bottom expander)

Cross-tab nav: reads `st.session_state["target_ticker"]` and ["target_mode"]
set by Overview tab clicks. Pre-populates the selectors. Hints are consumed
(popped) on read so they don't sticky on subsequent natural navigation.
"""
import streamlit as st

from . import (
    dd_metadata, dd_price_chart, dd_analysis, dd_agent_trace,
    dd_insider, dd_options, dd_sentiment, dd_reddit, dd_news,
    earnings_calendar,
)
from .formatters import color_decision


def render(managed_tickers, df, status):
    if df.empty or not managed_tickers:
        st.info(
            "No runs to explore yet. Fire a run from the **About & Setup** tab "
            "to populate the explorer."
        )
        return

    # ── 1. Run selector strip ──────────────────────────────────────────────
    target_ticker = st.session_state.pop("target_ticker", None)
    target_mode = st.session_state.pop("target_mode", None)

    col_ticker, col_run = st.columns([1, 3])

    with col_ticker:
        try:
            default_ticker_idx = (
                managed_tickers.index(target_ticker)
                if target_ticker in managed_tickers
                else 0
            )
        except ValueError:
            default_ticker_idx = 0
        ticker_pick = st.selectbox(
            "Ticker",
            managed_tickers,
            index=default_ticker_idx,
            key="explorer_ticker",
        )

    ticker_runs = (
        df[df["ticker"] == ticker_pick]
        .sort_values("id", ascending=False)
        .reset_index(drop=True)
    )
    if ticker_runs.empty:
        st.info(f"No runs yet for {ticker_pick}.")
        return

    ticker_runs["run_label"] = ticker_runs.apply(
        lambda r: (
            f"#{r['id']} | {r['run_date']} | {r['mode']} | {r.get('decision') or '—'}"
        ),
        axis=1,
    )

    with col_run:
        # Default to most recent run, OR a run matching target_mode if set.
        default_run_idx = 0
        if target_mode:
            for i, mode in enumerate(ticker_runs["mode"]):
                if mode == target_mode:
                    default_run_idx = i
                    break
        run_label_pick = st.selectbox(
            "Run",
            ticker_runs["run_label"].tolist(),
            index=default_run_idx,
            key="explorer_run",
        )
    row = ticker_runs[ticker_runs["run_label"] == run_label_pick].iloc[0]
    run_mode = (row.get("mode") or "").lower()

    st.divider()

    # ── 2. Run header strip ────────────────────────────────────────────────
    _render_run_header(row)

    st.divider()

    # ── 3. Metadata + price chart side-by-side ────────────────────────────
    col_meta, col_chart = st.columns([1, 4])
    with col_meta:
        dd_metadata.render(row)
    with col_chart:
        dd_price_chart.render(ticker_pick)

    st.divider()

    # ── 4. Mode-conditional analysis ──────────────────────────────────────
    # For agent: trace at top (the journey), analysis below (the verdict).
    # For solo/core/full: dd_analysis handles the panel/single-block split.
    if run_mode == "agent":
        dd_agent_trace.render(row)
        st.divider()
    dd_analysis.render(row)

    # ── 5. Universal data panels ──────────────────────────────────────────
    st.divider()
    dd_insider.render(ticker_pick)

    st.divider()
    dd_options.render(ticker_pick)

    st.divider()
    # Sentiment merge (StockTwits + Reddit) lands in Commit 2. Keep both
    # panels stacked for now so no signal is lost in the skeleton.
    dd_sentiment.render(ticker_pick)
    dd_reddit.render(ticker_pick)

    st.divider()
    dd_news.render(ticker_pick)

    # ── 6. Earnings calendar (deprioritized) ──────────────────────────────
    st.divider()
    earnings_calendar.render([ticker_pick] if ticker_pick else [])


def _render_run_header(row):
    decision = str(row.get("decision") or "—")
    mode = (row.get("mode") or "—").upper()
    model = row.get("model") or "—"
    runtime = row.get("runtime_seconds") or 0
    tokens = row.get("total_tokens") or 0
    cost = row.get("cost_sonnet") or 0

    cols = st.columns([2, 1, 2, 1, 1, 1])
    cols[0].markdown(
        f'<div style="{color_decision(decision)};padding:8px 14px;border-radius:6px;'
        f'font-size:18px;font-weight:600;display:inline-block">{decision}</div>',
        unsafe_allow_html=True,
    )
    cols[1].markdown(f"**Mode**\n\n`{mode.lower()}`")
    cols[2].markdown(f"**Model**\n\n`{model}`")
    cols[3].markdown(f"**Runtime**\n\n{runtime:.1f}s")
    cols[4].markdown(f"**Tokens**\n\n{tokens:,}")
    cols[5].markdown(f"**Cost (Sonnet)**\n\n${cost:.4f}")
