"""Deep-dive analysis section — mode-aware: panel for core, single block otherwise."""
import streamlit as st

from .render_analysis import render_analysis, render_panel


def render(row):
    st.subheader("Analysis")
    run_mode = (row.get("mode") or "").lower()
    extra_payload = row.get("extra")

    if run_mode == "core" and extra_payload:
        render_panel(extra_payload)
    else:
        render_analysis(row.get("analysis"))
