"""Run Explorer tab — drill into one historical run.

Sections (top to bottom):
1. Run selector strip (ticker + run dropdown)
2. Run header strip (verdict pill + mode + model + runtime + tokens + cost)
3. Metadata + price chart side-by-side
4. Mode-conditional analysis:
     - solo/core/full: dd_analysis (handles core's panel internally)
     - agent: dd_agent_trace timeline first, then dd_analysis
5. Universal data panels (insider, options, sentiment, news) — all collapsed
   by default per spec ("Each panel collapsed-by-default except Price chart")
6. Earnings calendar (deprioritized to bottom expander)

Cross-tab nav: reads `st.session_state["target_ticker"]`, ["target_mode"],
and ["target_run_id"] hints set by Overview tab clicks (master_table cells
or featured_runs cards). The hints are popped immediately on read so they
don't sticky on later natural navigation; if present, they force-set the
selectbox state BEFORE the widgets render.
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

    # ── Consume cross-tab nav hints (set in Overview by master_table or
    # featured_runs). Pop so they don't persist past one render. Force the
    # selectbox session_state values BEFORE the widgets are created — that's
    # the only point where session_state[key] takes priority over the widget's
    # `index=` parameter on first render.
    target_ticker = st.session_state.pop("target_ticker", None)
    target_mode = st.session_state.pop("target_mode", None)
    target_run_id = st.session_state.pop("target_run_id", None)

    if target_ticker and target_ticker in managed_tickers:
        st.session_state["explorer_ticker"] = target_ticker

    # ── 1. Run selector strip ──────────────────────────────────────────────
    col_ticker, col_run = st.columns([1, 3])

    with col_ticker:
        try:
            default_ticker_idx = (
                managed_tickers.index(st.session_state.get("explorer_ticker", managed_tickers[0]))
                if managed_tickers else 0
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

    # If a specific run was hinted, force-select it (matches by id). Else if
    # a mode hint is set, pick the first run with that mode. Else default to
    # most recent.
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
        # If session_state has a stale label (e.g., user switched tickers),
        # default index falls back to 0.
        labels = ticker_runs["run_label"].tolist()
        current_label = st.session_state.get("explorer_run")
        default_run_idx = labels.index(current_label) if current_label in labels else 0
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
    # Price chart is the only panel NOT collapsed (it's the visual anchor).
    col_meta, col_chart = st.columns([1, 4])
    with col_meta:
        dd_metadata.render(row)
    with col_chart:
        dd_price_chart.render(ticker_pick)

    st.divider()

    # ── 4. Mode-conditional analysis ──────────────────────────────────────
    # Agent: trace timeline first (the journey), analysis paragraph below.
    # Solo/Core/Full: dd_analysis owns the layout (core renders its panel).
    if run_mode == "agent":
        dd_agent_trace.render(row)
        st.divider()
    dd_analysis.render(row)

    # ── 5. Universal data panels (collapsed by default) ───────────────────
    st.divider()
    with st.expander("📊 Insider Activity (last 90 days)", expanded=False):
        dd_insider.render(ticker_pick)

    with st.expander("📈 Options Snapshot", expanded=False):
        dd_options.render(ticker_pick)

    # Sentiment merge — StockTwits + Reddit sit in one panel (saves vertical
    # space vs separate sections).
    with st.expander("💬 Social Sentiment (StockTwits + Reddit)", expanded=False):
        dd_sentiment.render(ticker_pick)
        st.markdown("---")
        dd_reddit.render(ticker_pick)

    # News owns its own expander internally (kept for the days-back slider
    # placement). Just call it; don't double-wrap.
    dd_news.render(ticker_pick)

    # ── 6. Earnings calendar (deprioritized) ──────────────────────────────
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
