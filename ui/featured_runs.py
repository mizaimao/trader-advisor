"""Featured agent runs strip — auto-curated 3-card row on the Overview tab.

Selection algorithm (per Phase 1 demo refactor spec):
1. One agent run per verdict bucket — bull (BUY/OVERWEIGHT), hold (HOLD),
   bear (SELL/UNDERWEIGHT).
2. Within each bucket, prefer the run with the most distinct tools called
   (richer trace → more interesting demo).
3. Across buckets, avoid ticker repetition.
4. If a verdict bucket is empty in the data, fall back to picking the
   highest-tool-count remaining run from any bucket.

Each card click sets `target_ticker`, `target_mode='agent'`, and
`target_run_id` in session_state, then fires a toast. Run Explorer reads
those hints on its next render to pre-select the exact run.
"""
import json

import streamlit as st

from .formatters import color_decision


def render(df):
    st.markdown("### ⭐ Featured Agent Runs")
    picks = _select_three(df)
    if not picks:
        st.info(
            "No agent runs to feature yet. Run `python runner.py --tickers NVDA --agent` "
            "to populate this strip."
        )
        return

    st.caption(
        "Auto-curated by verdict diversity (one BUY-ish, one HOLD, one SELL-ish "
        "where available) with tool-count tie-break and ticker variety. Click "
        "any card to load that run in the **🔍 Run Explorer** tab."
    )

    cols = st.columns(len(picks))
    for col, pick in zip(cols, picks):
        with col:
            _render_card(pick)


# ── Algorithm ────────────────────────────────────────────────────────────────
_BUCKET_ORDER = ("bull", "hold", "bear")


def _bucket_for(decision):
    v = str(decision or "").upper().strip()
    if v in ("BUY", "OVERWEIGHT"):
        return "bull"
    if v == "HOLD":
        return "hold"
    if v in ("SELL", "UNDERWEIGHT"):
        return "bear"
    return "other"


def _parse_extra(extra):
    if not extra:
        return {}
    if isinstance(extra, dict):
        return extra
    try:
        return json.loads(extra)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _distinct_tool_count(meta):
    """Number of distinct tool names called across the trace."""
    trace = meta.get("trace", []) or []
    names = set()
    for step in trace:
        for call in step.get("tool_calls") or []:
            name = call.get("name")
            if name:
                names.add(name)
    return len(names)


def _enrich(df):
    """Build a list of dicts annotated with bucket, distinct_tools, tool_calls."""
    if df.empty or "mode" not in df.columns:
        return []
    agent_df = df[df["mode"] == "agent"]
    if agent_df.empty:
        return []

    rows = []
    for _, r in agent_df.iterrows():
        meta = _parse_extra(r.get("extra"))
        rows.append({
            "row": r.to_dict(),
            "id": int(r["id"]),
            "ticker": r["ticker"],
            "decision": r.get("decision") or "",
            "bucket": _bucket_for(r.get("decision")),
            "tool_calls": int(meta.get("tool_calls_used") or 0),
            "distinct_tools": _distinct_tool_count(meta),
        })
    return rows


def _select_three(df):
    """Pick up to 3 runs by the verdict-diversity rules."""
    rows = _enrich(df)
    if not rows:
        return []

    # Bucket and sort within each by (distinct_tools desc, tool_calls desc).
    buckets = {b: [] for b in _BUCKET_ORDER}
    for r in rows:
        if r["bucket"] in buckets:
            buckets[r["bucket"]].append(r)
    for b in buckets:
        buckets[b].sort(
            key=lambda x: (x["distinct_tools"], x["tool_calls"]),
            reverse=True,
        )

    # Pick one per bucket, avoiding ticker repetition across picks.
    picked = []
    used_tickers = set()
    for b in _BUCKET_ORDER:
        for candidate in buckets[b]:
            if candidate["ticker"] not in used_tickers:
                picked.append(candidate)
                used_tickers.add(candidate["ticker"])
                break

    # Fallback for empty buckets: highest tool-count remaining from any bucket.
    if len(picked) < 3:
        picked_ids = {p["id"] for p in picked}
        remaining = [r for r in rows if r["id"] not in picked_ids]
        remaining.sort(
            key=lambda x: (x["tool_calls"], x["distinct_tools"]),
            reverse=True,
        )
        for candidate in remaining:
            if candidate["ticker"] in used_tickers:
                continue
            picked.append(candidate)
            used_tickers.add(candidate["ticker"])
            if len(picked) >= 3:
                break

    return picked[:3]


# ── Rendering ────────────────────────────────────────────────────────────────
def _render_card(pick):
    row = pick["row"]
    ticker = pick["ticker"]
    decision = pick["decision"] or "—"
    tool_calls = pick["tool_calls"]
    distinct = pick["distinct_tools"]
    model = row.get("model") or "?"
    runtime = row.get("runtime_seconds") or 0

    color_style = color_decision(decision)

    st.markdown(
        f'<div style="background:#1a1a2e;border:1px solid #2a4a6a;'
        f'border-radius:8px;padding:14px 18px;margin-bottom:6px;height:140px;'
        f'display:flex;flex-direction:column;justify-content:space-between">'
        f'<div>'
        f'<div style="font-size:11px;color:#888;text-transform:uppercase;'
        f'letter-spacing:0.5px">🤖 agent · <b style="color:#e8e8e8">{ticker}</b></div>'
        f'<div style="margin-top:8px">'
        f'<span style="{color_style};padding:4px 10px;border-radius:4px;'
        f'font-weight:600">{decision}</span>'
        f'</div>'
        f'</div>'
        f'<div style="font-size:12px;color:#cbd5e0">'
        f'{tool_calls} tool calls · {distinct} distinct sources<br>'
        f'<span style="color:#888">{model} · {runtime:.0f}s</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if st.button("View trace →", key=f"feat_{row['id']}", use_container_width=True):
        st.session_state["target_ticker"] = ticker
        st.session_state["target_mode"] = "agent"
        st.session_state["target_run_id"] = int(row["id"])
        st.toast(
            f"Loading run #{row['id']} ({ticker}). "
            f"Open the **🔍 Run Explorer** tab →"
        )
