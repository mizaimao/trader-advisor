"""Render the LLM analysis text — solo/full as a single block, core as a panel."""
import json
import re
import streamlit as st

from .formatters import escape_dollars


_SECTION_NAMES = [
    "Technical Outlook",
    "Fundamental Snapshot",
    "Catalysts",
    "News Sentiment",
    "Insider Activity",
    "Sector & Macro Context",
    "Counter-Thesis",
    "Strongest Counter-Evidence",
    "What the Initial Analyst Got Wrong",
    "Key Disagreement",
    "Final Decision",
]

_SECTION_PATTERN = (
    r"(?:^|\n)\s*\**\s*("
    + "|".join(re.escape(s) for s in _SECTION_NAMES)
    + r")\s*:?\**"
)

_STYLE = """
<style>
.analysis-section {
    background: #1a1a2e;
    border-left: 4px solid #4a90d9;
    padding: 16px 20px;
    margin: 12px 0;
    border-radius: 6px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 16px;
    line-height: 1.75;
    color: #e8e8e8;
}
.analysis-section h3 {
    color: #7ab8f5;
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 10px 0;
    border-bottom: 1px solid #2a4a6a;
    padding-bottom: 6px;
}
.analysis-section ul { margin: 8px 0; padding-left: 22px; }
.analysis-section li { margin: 4px 0; }
.analysis-section strong { color: #ffd966; }
</style>
"""


def render_analysis(text):
    if not text:
        return

    st.markdown(_STYLE, unsafe_allow_html=True)
    parts = re.split(_SECTION_PATTERN, text)

    if len(parts) < 3:
        clean = escape_dollars(text.replace("**", "").strip())
        st.markdown(f'<div class="analysis-section">{clean}</div>', unsafe_allow_html=True)
        return

    i = 1 if not parts[0].strip() else 0
    if i == 0 and parts[0].strip():
        preamble = escape_dollars(parts[0].strip())
        st.markdown(f'<div class="analysis-section">{preamble}</div>', unsafe_allow_html=True)
        i = 1

    while i < len(parts) - 1:
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        body_html = _format_body(body)
        st.markdown(
            f'<div class="analysis-section"><h3>{heading}</h3>{body_html}</div>',
            unsafe_allow_html=True,
        )
        i += 2


def _format_body(body):
    """Convert markdown-ish body text to HTML with bullets and bold."""
    body = body.replace("$", "&#36;")
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = body.replace("**", "").replace("__", "")

    lines = body.split("\n")
    out = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[\*\-•]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = re.sub(r"^[\*\-•]\s+", "", stripped)
            item = re.sub(r"^\d+\.\s+", "", item)
            out.append(f"<li>{item}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if stripped:
                out.append(f"<p style='margin: 8px 0'>{stripped}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def render_panel(extra_json):
    """Render the 3-section breakdown for core mode runs.
    extra_json is the JSON string from the runs.extra column."""
    if not extra_json:
        st.info("No panel breakdown available for this run.")
        return
    try:
        extra = json.loads(extra_json)
    except (json.JSONDecodeError, TypeError):
        st.warning("Could not parse panel breakdown.")
        return

    initial_decision = extra.get("initial_decision") or "—"
    synthesis_decision = extra.get("synthesis_decision") or "—"

    if initial_decision != synthesis_decision:
        st.markdown(
            f"<div style='padding:10px 14px;background:#2a2a3e;border-left:4px solid #ffd966;"
            f"border-radius:4px;margin-bottom:14px'>"
            f"⚖️ <b>Panel changed its mind:</b> "
            f"<span style='color:#888'>Initial: {initial_decision}</span> → "
            f"<span style='color:#ffd966'>Synthesis: {synthesis_decision}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding:10px 14px;background:#1a2a1a;border-left:4px solid #00ff00;"
            f"border-radius:4px;margin-bottom:14px'>"
            f"✅ <b>Panel agreed:</b> {synthesis_decision}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with st.expander(f"🎯 Synthesis (final) — {synthesis_decision}", expanded=True):
        render_analysis(extra.get("synthesis_analysis") or "")

    with st.expander(f"📋 Initial Analyst — {initial_decision}", expanded=False):
        render_analysis(extra.get("initial_analysis") or "")

    with st.expander("😈 Devil's Advocate", expanded=False):
        render_analysis(extra.get("advocate_analysis") or "")
