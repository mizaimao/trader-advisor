"""Overview tab — 90-second view.

Five sections (top to bottom):
1. Hero — title + subtitle + 4 capsules (no outer box)
2. Master ticker × mode table — clickable verdict cells
3. Mode comparison — averaged latency / tokens + plain-language descriptions
4. Architecture (collapsed expander) — mermaid data-flow + core-mode diagrams
5. Featured agent runs — auto-curated by verdict diversity
"""
import streamlit as st

from . import hero, master_table, mode_comparison, featured_runs


def render(managed_tickers, df, status):
    hero.render_compact()
    st.divider()
    master_table.render(managed_tickers, df, status)
    st.divider()
    mode_comparison.render(df)
    st.divider()
    with st.expander("🏗 Architecture", expanded=False):
        hero.render_architecture()
    st.divider()
    featured_runs.render(df)
