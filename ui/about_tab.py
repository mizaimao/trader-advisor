"""About & Setup tab — technical details + operational controls.

Top half (informational):
1. What this is — one paragraph
2. Mode comparison table — 4 rows, averages computed live from runs DB
3. Architecture diagrams — mermaid, moved from hero

"Run it yourself" divider separates the operational half:
5. Setup — clone/install commands
6. BYOK panel — provider/key/Ollama-URL form (read-only in demo)
7. Run Queue — multiselect + mode + Run button (disabled in demo)
8. Manage Tickers — add/remove (read-only in demo)
9. Data Sources — toggle panel (read-only in demo)

Footer with GitHub / NOTES / spec links + license.
"""
import pandas as pd
import streamlit as st

from . import (
    hero,
    ticker_management,
    data_sources,
    run_queue,
)
from .demo import DEMO_MODE


def render(
    managed_tickers, df, save_tickers, status,
    project_root, python_bin, runner_path,
):
    # ── 1. What this is ───────────────────────────────────────────────────
    st.markdown(
        "## About\n\n"
        "Personal short-term-trading dashboard with multi-mode LLM-driven "
        "analysis. Four pipelines, ten data sources, one toolbox the LLM "
        "can drive itself."
    )

    # ── 2. Mode comparison table (live averages from runs DB) ────────────
    st.markdown("### Mode comparison")
    st.markdown(_mode_comparison_md(df))
    st.caption(
        "Latency and token figures averaged across this DB's runs per mode. "
        "Rows with no data show '—'. The 'When to use' column is editorial."
    )

    # ── 3. Architecture diagrams ──────────────────────────────────────────
    st.markdown("### Architecture")
    hero.render_architecture()

    # ── 4. "Run it yourself" divider ─────────────────────────────────────
    st.divider()
    st.markdown("## Run it yourself")
    st.caption(
        "These are the operational controls — fire runs, manage tickers, "
        "toggle data sources. Read-only in demo mode (see top banner)."
    )

    # ── 5. Setup ──────────────────────────────────────────────────────────
    st.markdown("### Setup")
    st.code(
        "git clone https://github.com/mizaimao/trader-advisor\n"
        "cd trader-advisor\n"
        "cp .env.example .env       # then add your API keys\n"
        "pip install -r requirements.txt\n"
        "streamlit run dashboard.py",
        language="bash",
    )

    # ── 6. BYOK panel ─────────────────────────────────────────────────────
    hero.render_byok()

    # ── 7. Run Queue ──────────────────────────────────────────────────────
    st.divider()
    run_queue.render(
        managed_tickers, status, project_root, python_bin, runner_path,
    )

    # ── 8. Manage Tickers ─────────────────────────────────────────────────
    st.divider()
    ticker_management.render(managed_tickers, save_tickers, demo_mode=DEMO_MODE)

    # ── 9. Data Sources ───────────────────────────────────────────────────
    st.divider()
    data_sources.render()

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        "[GitHub](https://github.com/mizaimao/trader-advisor) · "
        "[NOTES.md](https://github.com/mizaimao/trader-advisor/blob/main/NOTES.md) · "
        "[Phase 1 spec](https://github.com/mizaimao/trader-advisor/blob/main/docs/agent_phase1_spec.md) · "
        "MIT License"
    )


# ── Mode comparison helpers ──────────────────────────────────────────────────
_MODE_DESCRIPTIONS = [
    ("solo",  "Quick gut check, single LLM call. Workflow."),
    ("core",  "Default. Three-agent adversarial panel. Workflow."),
    ("full",  "Most thorough; expensive. Multi-agent."),
    ("agent", "Autonomous tool selection. Genuinely agentic."),
]


def _mode_comparison_md(df):
    """Build the markdown table with live-computed averages from the runs DB."""
    header = (
        "| Mode | Avg latency | Avg tokens | When to use |\n"
        "|------|-------------|------------|-------------|"
    )
    rows = []
    for mode, when_to_use in _MODE_DESCRIPTIONS:
        avg_lat, avg_tokens, n = _averages_for(df, mode)
        latency_cell = _format_latency(avg_lat) if n else "—"
        tokens_cell = _format_tokens(avg_tokens) if n else "—"
        if n and n < 3:
            latency_cell += f" (n={n})"
            tokens_cell += f" (n={n})"
        rows.append(f"| **{mode}** | {latency_cell} | {tokens_cell} | {when_to_use} |")
    return header + "\n" + "\n".join(rows)


def _averages_for(df, mode):
    """Returns (avg_runtime_seconds, avg_total_tokens, count) for mode."""
    if df.empty or "mode" not in df.columns:
        return None, None, 0
    subset = df[df["mode"] == mode]
    if subset.empty:
        return None, None, 0
    avg_lat = subset["runtime_seconds"].mean() if "runtime_seconds" in subset else None
    avg_tok = subset["total_tokens"].mean() if "total_tokens" in subset else None
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
