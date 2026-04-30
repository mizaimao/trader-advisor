"""Demo-mode landing/hero section."""
import streamlit as st

from .mermaid import render as render_mermaid
from .providers import PROVIDERS, PROVIDER_LABELS, get_by_label


# ── architecture diagrams ─────────────────────────────────────────────────────
DATA_FLOW_DIAGRAM = """flowchart LR
    Sources["9 Data Sources<br/>price · earnings · insider · options<br/>sector · stocktwits · reddit · news · fundamentals"] --> Context[fetch_context]

    Context --> Solo[solo · 1 call · ~30s]
    Context --> Core[core · 3 calls · ~60s]
    Context --> Full[full · 7 agents · 5-15min]

    Solo --> DB[(SQLite)]
    Core --> DB
    Full --> DB

    DB --> UI[Streamlit Dashboard]
    DB --> Bot[Telegram Bot]
"""


CORE_PIPELINE_DIAGRAM = """flowchart LR
    Context([Context]) --> Initial[Initial Analyst]
    Initial --> Advocate[Devil's Advocate<br/>argue against]
    Initial --> Synth[Synthesizer<br/>weigh both sides]
    Advocate --> Synth
    Synth --> Decision([Final Decision<br/>~30% flipped])
"""


# ── styling ───────────────────────────────────────────────────────────────────
_STYLE = """<style>
.hero-box {
    background: linear-gradient(135deg, #1a1a2e 0%, #232342 100%);
    padding: 32px 40px;
    border-radius: 12px;
    margin-bottom: 16px;
    border: 1px solid #2a4a6a;
}
.hero-title { font-size: 36px; font-weight: 700; color: #ffffff; margin-bottom: 8px; }
.hero-tagline { font-size: 17px; color: #cbd5e0; margin-bottom: 22px; line-height: 1.6; }
.hero-features { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 26px; }
.hero-feature {
    background: rgba(255,255,255,0.04); padding: 10px 16px; border-radius: 6px;
    border-left: 3px solid #4a90d9; min-width: 130px;
}
.hero-feature-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.hero-feature-value { font-size: 22px; color: #e8e8e8; margin-top: 2px; font-weight: 600; }
.hero-feature-sub { font-size: 11px; color: #888; margin-top: 2px; }
.hero-section-heading {
    font-size: 12px; font-weight: 700; color: #7ab8f5;
    text-transform: uppercase; letter-spacing: 1.2px; margin: 18px 0 10px 0;
}
.hero-bullets { color: #cbd5e0; font-size: 14px; line-height: 1.65; margin: 0 0 6px 0; padding-left: 22px; }
.hero-bullets li { margin-bottom: 8px; }
.hero-bullets b { color: #ffd966; font-weight: 600; }
.hero-bullets code {
    background: rgba(255,255,255,0.06); padding: 1px 6px;
    border-radius: 3px; font-size: 12px; color: #ffd966;
}
.hero-bullets .meta { color: #888; font-size: 12px; }
.hero-links { margin-top: 18px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.08); }
.hero-links a { color: #7ab8f5; text-decoration: none; font-size: 14px; margin-right: 18px; }
.hero-links a:hover { text-decoration: underline; }
</style>"""


def render():
    st.markdown(_STYLE, unsafe_allow_html=True)

    html = (
'<div class="hero-box">'
'<div class="hero-title">📈 moose-trader</div>'
'<div class="hero-tagline">'
'A multi-mode LLM-driven stock analysis dashboard. '
'Three agentic pipelines — solo analyst, adversarial panel, multi-agent debate — '
'fed by nine independent tools, with persisted decision history.'
'</div>'
'<div class="hero-features">'
'<div class="hero-feature"><div class="hero-feature-label">Modes</div><div class="hero-feature-value">3</div><div class="hero-feature-sub">solo · core · full</div></div>'
'<div class="hero-feature"><div class="hero-feature-label">Tools</div><div class="hero-feature-value">9</div><div class="hero-feature-sub">price, options, sentiment...</div></div>'
'<div class="hero-feature"><div class="hero-feature-label">Stack</div><div class="hero-feature-value">4</div><div class="hero-feature-sub">Streamlit · LangChain · SQLite · Plotly</div></div>'
'<div class="hero-feature"><div class="hero-feature-label">LLMs</div><div class="hero-feature-value">5+</div><div class="hero-feature-sub">Gemma · Gemini · Claude · GPT...</div></div>'
'</div>'
'<div class="hero-section-heading">Analysis Modes</div>'
'<ul class="hero-bullets">'
'<li><b>solo</b> — single LLM call with full context. <span class="meta">~30s · ~18K tokens</span></li>'
'<li><b>core</b> <span class="meta">(default)</span> — three-agent adversarial panel. Initial Analyst forms a thesis, Devil\'s Advocate argues against it, Synthesizer weighs both sides. Flips ~30% of decisions. <span class="meta">~60s · ~55K tokens</span></li>'
'<li><b>full</b> — 7-agent debate via TradingAgents. Most thorough, expensive, not available in this demo. <span class="meta">5–15 min · ~400K tokens</span></li>'
'</ul>'
'<div class="hero-section-heading">Highlights</div>'
'<ul class="hero-bullets">'
'<li><b>Multi-agent pipeline built from scratch</b> — no LangGraph, no CrewAI. Plain Python orchestration of LangChain calls, every prompt and branch visible.</li>'
'<li><b>Nine tools the agents reason over</b> — price, fundamentals, options flow, insider activity, earnings, sector context, news, StockTwits, Reddit. Each toggleable in the Data Sources panel below.</li>'
'<li><b>Provider-agnostic LLM layer</b> — runs on cloud or locally. Supports <code>ollama</code> (local), <code>gemini</code>, <code>anthropic</code>, <code>openai</code>. One config switch, no prompt rewrites.</li>'
'<li><b>Persistent decision history</b> — every run stored with full context, prompts, token cost, and runtime. A journal of how the agents have reasoned over time.</li>'
'</ul>'
'<div class="hero-links">'
'<a href="https://github.com/mizaimao/moose-trader" target="_blank">GitHub →</a>'
'</div>'
'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)

    # Architecture
    with st.expander("🏗 Architecture", expanded=False):
        st.markdown("**Data flow — all three modes share a common context-fetching pipeline:**")
        render_mermaid(DATA_FLOW_DIAGRAM, height=420)
        st.markdown("**Core mode pipeline — adversarial 3-call panel:**")
        render_mermaid(CORE_PIPELINE_DIAGRAM, height=240)
        st.markdown(
            "**Why core mode is the default and the most interesting** — three sequential LLM calls "
            "play different roles. The devil's advocate is forced to argue *against* the initial analyst, "
            "and the synthesizer weighs both sides. In practice this flips ~30% of decisions, usually "
            "from over-bullish initial reads to more cautious final calls."
        )

    # Try it yourself — provider dropdown + key
    with st.expander("🔑 Try it yourself (bring your own key)", expanded=False):
        st.markdown(
            "This demo is read-only by default. To run a fresh analysis, pick a provider and paste your key.\n\n"
            "🔒 **Privacy:** keys live only in your browser session — never stored, logged, or sent anywhere "
            "except the LLM provider you select. They're gone the moment you close this tab. "
            "Each user's session is independent; your key is never shared with other visitors."
        )

        chosen_label = st.selectbox(
            "Provider",
            PROVIDER_LABELS,
            key="byok_provider_label",
            index=0,
        )
        entry = get_by_label(chosen_label)

        if entry["needs_key"]:
            st.text_input(
                f"{entry['label']} API key",
                type="password",
                key="byok_api_key",
                placeholder=entry["key_placeholder"],
                help=f"Get a key at: {entry['key_help_url']}",
            )
            if st.session_state.get("byok_api_key"):
                st.success(f"✓ Key loaded for {entry['label']}. Scroll down to the Run Queue.")
        else:
            # Local provider (Ollama) — URL field instead of key field
            st.text_input(
                f"{entry['label']} server URL",
                key="byok_ollama_url",
                placeholder=entry["url_placeholder"],
                help="If you run your own Ollama server, paste the URL here. Otherwise leave blank.",
            )
            st.info(
                "Note: this demo's runtime cannot reach a localhost Ollama server on your machine. "
                "This option is mainly useful if you have a publicly-reachable Ollama endpoint."
            )
