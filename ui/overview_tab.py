"""Overview tab — 90-second recruiter view.

Three sections:
1. Compact hero metric strip (4 capsule cards)
2. Master ticker × mode table (clickable verdict cells)
3. Featured agent runs strip (placeholder; populated in Commit 2)
"""
import streamlit as st

from . import hero, master_table


def render(managed_tickers, df, status):
    hero.render_compact()
    st.divider()
    master_table.render(managed_tickers, df, status)
    st.divider()
    _featured_runs_placeholder(df)


def _featured_runs_placeholder(df):
    st.markdown("### ⭐ Featured Agent Runs")
    st.caption(
        "Coming next commit — auto-curated by verdict diversity (one BUY, one HOLD, "
        "one SELL/UNDERWEIGHT) with tool-count tie-break and ticker-variety tie-break."
    )
