"""Run Explorer tab — drill into one historical run.

Sections (top to bottom):
1. Run selector strip (ticker + run dropdown)
2. Run header strip (verdict pill + mode + model + runtime + tokens + cost)
3. Metadata + price chart side-by-side (price chart is the only non-collapsed panel)
4. Insider Activity + Options Snapshot side-by-side (both foldable, collapsed)
5. Agent trace (only for agent runs — folded by default per dd_agent_trace)
6. Analysis (foldable, expanded by default)
7. Social Sentiment combined panel (foldable, collapsed)
8. Latest News (foldable, collapsed via dd_news)
9. Earnings Calendar (foldable, collapsed)

Cross-tab nav: reads `target_ticker`, `target_mode`, `target_run_id` hints set
by Overview tab clicks. The hints are popped on read; if present, they
force-set the selectbox session_state BEFORE the widgets render.
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

    # ── Consume cross-tab nav hints ────────────────────────────────────────
    target_ticker = st.session_state.pop("target_ticker", None)
    target_mode = st.session_state.pop("target_mode", None)
    target_run_id = st.session_state.pop("target_run_id", None)

    if target_ticker and target_ticker in managed_tickers:
        st.session_state["explorer_ticker"] = target_ticker

    # ── 1. Run selector strip ──────────────────────────────────────────────
    col_ticker, col_run = st.columns([1, 3])

    with col_ticker:
        try:
            default_ticker_idx = managed_tickers.index(
                st.session_state.get("explorer_ticker", managed_tickers[0])
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
            f"#{r['id']} | {r['run_date']} | {r['mode']} | "
            f"{r.get('decision') or '—'}"
        ),
        axis=1,
    )

    # Force-select target run if one was requested by the Overview click.
    if target_run_id is not None:
        match = ticker_runs[ticker_runs["id"] == target_run_id]
        if not match.empty:
            st.session_state["explorer_run"] = match.iloc[0]["run_label"]
    elif target_mode:
        for _, r in ticker_runs.iterrows():
            if r["mode"] == target_mode:
                st.session_state["explorer_run"] = r["run_label"]
                break

    with col_run:
        labels = ticker_runs["run_label"].tolist()
        current_label = st.session_state.get("explorer_run")
        default_run_idx = (
            labels.index(current_label) if current_label in labels else 0
        )
        run_label_pick = st.selectbox(
            "Run",
            labels,
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
    # Price chart is the visual anchor — the only panel NOT collapsed by default.
    # Earnings calendar lives INSIDE the chart column (under the RSI subplot)
    # rather than spanning the full width below — keeps it associated with the
    # chart visually and frees the row below for analysis-related content.
    col_meta, col_chart = st.columns([1, 4])
    with col_meta:
        dd_metadata.render(row)
    with col_chart:
        dd_price_chart.render(ticker_pick)
        earnings_calendar.render(
            [ticker_pick] if ticker_pick else [], wrap_in_expander=False,
        )

    st.divider()

    # ── 5. Insider + Options under one foldable, side by side ─────────────
    with st.expander(
        "📊 Insider Activity (last 90 days) and Options Snapshot",
        expanded=False,
    ):
        col_insider, col_options = st.columns(2)
        with col_insider:
            dd_insider.render(ticker_pick)
        with col_options:
            dd_options.render(ticker_pick)

    # ── 6. Agent trace (agent runs only — own expander internally) ────────
    if run_mode == "agent":
        dd_agent_trace.render(row)

    # ── 7. Analysis (foldable, expanded by default) ───────────────────────
    with st.expander("📝 Analysis", expanded=True):
        dd_analysis.render(row)

    # ── 8. Social Sentiment combined ──────────────────────────────────────
    with st.expander("💬 Social Sentiment (StockTwits + Reddit)", expanded=False):
        dd_sentiment.render(ticker_pick)
        st.markdown("---")
        dd_reddit.render(ticker_pick)

    # ── 9. Latest News (own expander, collapsed) ──────────────────────────
    dd_news.render(ticker_pick)


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
