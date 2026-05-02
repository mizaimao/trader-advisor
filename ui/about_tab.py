"""About & Setup tab — operational controls + clone instructions.

Slimmer than before: mode comparison and architecture moved to the Overview tab
so they're visible without scrolling into here. This tab is now just the
"how do I run it / configure it" surface.

Sections:
1. About — one-line tagline
2. Setup — clone/install CLI block
3. BYOK panel (read-only in demo)
4. Run Queue (disabled in demo)
5. Manage Tickers (read-only in demo)
6. Data Sources (read-only in demo)

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
    # ── 1. About ──────────────────────────────────────────────────────────
    st.markdown(
        "## About\n\n"
        "A personal dashboard for viewing and controlling LLM-driven trading "
        "analysis. Four modes, ten data sources, and a loop-based agent mode "
        "that drives its own toolbox."
    )

    # ── 2. Setup ──────────────────────────────────────────────────────────
    st.markdown("### Run it yourself")
    st.code(
        "git clone https://github.com/mizaimao/trader-advisor\n"
        "cd trader-advisor\n"
        "cp .env.example .env       # then add your API keys\n"
        "pip install -r requirements.txt\n"
        "streamlit run dashboard.py",
        language="bash",
    )

    # ── 3. BYOK panel ─────────────────────────────────────────────────────
    hero.render_byok()

    # ── 4. Run Queue ──────────────────────────────────────────────────────
    st.divider()
    run_queue.render(
        managed_tickers, status, project_root, python_bin, runner_path,
    )

    # ── 5. Manage Tickers ─────────────────────────────────────────────────
    st.divider()
    ticker_management.render(managed_tickers, save_tickers, demo_mode=DEMO_MODE)

    # ── 6. Data Sources ───────────────────────────────────────────────────
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
