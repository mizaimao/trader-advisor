"""About & Setup tab — technical details + operational controls.

Top half (informational):
1. What this is — one paragraph
2. Mode comparison table — 4 rows
3. Architecture diagrams — mermaid, moved from hero

"Run it yourself" divider separates the operational half:
5. Setup — clone/install commands
6. BYOK panel — provider/key/Ollama-URL form (read-only in demo)
7. Run Queue — multiselect + mode + Run button (disabled in demo)
8. Manage Tickers — add/remove (read-only in demo)
9. Data Sources — toggle panel (read-only in demo)

Footer with GitHub / NOTES / spec links + license.
"""
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

    # ── 2. Mode comparison table ──────────────────────────────────────────
    st.markdown("### Mode comparison")
    st.markdown(
        "| Mode | Avg latency | Avg tokens | When to use |\n"
        "|------|-------------|------------|-------------|\n"
        "| **solo** | ~30s | ~18K | Quick gut check, single LLM call. Workflow. |\n"
        "| **core** | ~60s | ~55K | Default. Three-agent adversarial panel. Workflow. |\n"
        "| **full** | ~5–15min | ~400K | Most thorough; expensive. Multi-agent. |\n"
        "| **agent** | ~60–120s | variable | Autonomous tool selection. Genuinely agentic. |"
    )
    st.caption(
        "Numbers from observed demo runs (current commit hardcoded; next commit "
        "will compute live averages from the runs DB)."
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
