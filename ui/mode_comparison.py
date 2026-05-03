"""Mode comparison table — averaged latency / tokens per mode + plain-language
descriptions of when each mode is the right pick.

Lives on the Overview tab (visible without scrolling into About). The
"When to use" copy is editorial, the latency / tokens columns are
computed from the runs DB.
"""
import pandas as pd
import streamlit as st


_MODES = [
    (
        "agent",
        "Autonomous tool-calling loop. Picks its own data sources to query "
        "and when, at its own discretion.",
    ),
    (
        "core",
        "Three LLM calls with adversarial debate, which usually flips ~30% "
        "of solo's verdicts.",
    ),
    (
        "full",
        "Wrapper for TradingAgents (not installed by default). Seven-agent "
        "debate. Slowest.",
    ),
    (
        "solo",
        "Single LLM call with all data sources. Baseline.",
    ),
]


def render(df):
    st.markdown("### Mode comparison")
    st.markdown(_table_md(df))
    st.caption("Averaged across all runs in the database.")


def _table_md(df):
    header = (
        "| Mode | Avg latency | Avg tokens | Usage |\n"
        "|------|-------------|------------|-------|"
    )
    rows = []
    for mode, when_to_use in _MODES:
        avg_lat, avg_tok, n = _averages_for(df, mode)
        latency_cell = _format_latency(avg_lat) if n else "—"
        tokens_cell = _format_tokens(avg_tok) if n else "—"
        rows.append(
            f"| **{mode}** | {latency_cell} | {tokens_cell} | {when_to_use} |"
        )
    return header + "\n" + "\n".join(rows)


def _averages_for(df, mode):
    if df.empty or "mode" not in df.columns:
        return None, None, 0
    subset = df[df["mode"] == mode]
    if subset.empty:
        return None, None, 0
    avg_lat = (
        subset["runtime_seconds"].mean()
        if "runtime_seconds" in subset
        else None
    )
    avg_tok = (
        subset["total_tokens"].mean()
        if "total_tokens" in subset
        else None
    )
    return avg_lat, avg_tok, len(subset)


def _format_latency(seconds):
    if seconds is None or pd.isna(seconds):
        return "—"
    if seconds < 90:
        return f"~{int(round(seconds))}s"
    minutes = seconds / 60
    return f"~{minutes:.1f}m"


def _format_tokens(n):
    if n is None or pd.isna(n):
        return "—"
    if n >= 1000:
        return f"~{n / 1000:.0f}K"
    return f"~{int(round(n))}"
