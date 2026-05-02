"""Overview tab — 90-second recruiter view.

Three sections:
1. Compact hero metric strip (4 capsule cards)
2. Master ticker × mode table (clickable verdict cells)
3. Featured agent runs strip (auto-curated by verdict diversity)
"""
import streamlit as st

from . import hero, master_table, featured_runs


def render(managed_tickers, df, status):
    hero.render_compact()
    st.divider()
    master_table.render(managed_tickers, df, status)
    st.divider()
    featured_runs.render(df)
