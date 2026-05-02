"""About & Setup tab — pure documentation (no interactive run controls).

Run config (BYOK + Run Queue) lives in the top-right "⚡ Run Analysis" modal
now. This tab is just docs and operational data-management surfaces:

1. About paragraph
2. Setup CLI block (clone, .env, pip install, streamlit run)
3. Data Sources panel (read-only in demo)
4. Manage Tickers panel (read-only in demo) — data management, not run config
5. Footer (GitHub / NOTES.md / Phase 1 spec / license)
"""
import streamlit as st

from . import ticker_management, data_sources
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

    # ── 3. Data Sources panel ─────────────────────────────────────────────
    st.divider()
    data_sources.render()

    # ── 4. Manage Tickers panel ───────────────────────────────────────────
    st.divider()
    ticker_management.render(managed_tickers, save_tickers, demo_mode=DEMO_MODE)

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        "[GitHub](https://github.com/mizaimao/trader-advisor) · "
        "[NOTES.md](https://github.com/mizaimao/trader-advisor/blob/main/NOTES.md) · "
        "[Phase 1 spec](https://github.com/mizaimao/trader-advisor/blob/main/docs/agent_phase1_spec.md) · "
        "MIT License"
    )
