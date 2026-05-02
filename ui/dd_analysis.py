"""Deep-dive analysis section — mode-aware: panel for core, single block otherwise.

The caller (run_explorer_tab) wraps this in an expander labeled "Analysis",
so this module no longer renders its own subheader (would be duplicative).
"""
from .render_analysis import render_analysis, render_panel


def render(row):
    run_mode = (row.get("mode") or "").lower()
    extra_payload = row.get("extra")

    if run_mode == "core" and extra_payload:
        render_panel(extra_payload)
    else:
        render_analysis(row.get("analysis"))
