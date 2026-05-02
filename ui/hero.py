"""Hero / landing components.

Three exported entry points used by the new tab structure:

- `render_compact()`      — small capsule strip for the Overview tab
- `render_architecture()` — mermaid architecture diagrams for the About tab
- `render_byok()`         — provider/key/Ollama-URL form for the About tab
                            (visible-but-disabled in demo per the top banner)

The previous monolithic `render()` is gone — the tab orchestrators
(`overview_tab.py`, `about_tab.py`) compose the right pieces in the right places.
"""
import streamlit as st

from .mermaid import render as render_mermaid
from .providers import PROVIDER_LABELS, get_by_label


# ── architecture diagrams ────────────────────────────────────────────────────
DATA_FLOW_DIAGRAM = """flowchart LR
    Sources["10 Data Sources<br/>price · indicators · fundamentals<br/>earnings · insider · options<br/>sector · stocktwits · reddit · news"] --> Context[fetch_context]

    Context --> Solo[solo · 1 call · ~30s]
    Context --> Core[core · 3 calls · ~60s]
    Context --> Full[full · 7 agents · 5-15min]

    Sources -.tools.-> Agent[agent · tool-use loop · ~60-120s]

    Solo --> DB[(SQLite)]
    Core --> DB
    Full --> DB
    Agent --> DB

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


# ── compact hero (Overview tab) ──────────────────────────────────────────────
_COMPACT_STYLE = """<style>
.hero-compact {
    background: linear-gradient(135deg, #1a1a2e 0%, #232342 100%);
    padding: 18px 28px;
    border-radius: 10px;
    margin-bottom: 12px;
    border: 1px solid #2a4a6a;
}
.hero-compact-title { font-size: 22px; font-weight: 700; color: #ffffff; margin-bottom: 4px; }
.hero-compact-tagline { font-size: 13px; color: #cbd5e0; margin-bottom: 14px; }
.hero-compact-features { display: flex; gap: 16px; flex-wrap: wrap; }
.hero-compact-feature {
    background: rgba(255,255,255,0.04); padding: 8px 14px; border-radius: 6px;
    border-left: 3px solid #4a90d9; min-width: 110px;
}
.hero-compact-label { font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.hero-compact-value { font-size: 20px; color: #e8e8e8; margin-top: 2px; font-weight: 600; }
.hero-compact-sub { font-size: 11px; color: #888; margin-top: 1px; }
</style>"""


def render_compact():
    """Compact 4-capsule metric strip for the Overview tab."""
    st.markdown(_COMPACT_STYLE, unsafe_allow_html=True)
    html = (
        '<div class="hero-compact">'
        '<div class="hero-compact-title">📈 Multi-mode stock analysis pipeline</div>'
        '<div class="hero-compact-tagline">'
        'Three workflow modes plus an autonomous tool-use agent. '
        '<a href="https://github.com/mizaimao/trader-advisor" target="_blank" '
        'style="color:#7ab8f5;text-decoration:none;">repo →</a>'
        '</div>'
        '<div class="hero-compact-features">'
        '<div class="hero-compact-feature"><div class="hero-compact-label">Modes</div>'
        '<div class="hero-compact-value">4</div>'
        '<div class="hero-compact-sub">solo · core · full · agent</div></div>'
        '<div class="hero-compact-feature"><div class="hero-compact-label">Data sources</div>'
        '<div class="hero-compact-value">10</div>'
        '<div class="hero-compact-sub">price, options, sentiment...</div></div>'
        '<div class="hero-compact-feature"><div class="hero-compact-label">Stack</div>'
        '<div class="hero-compact-value">4</div>'
        '<div class="hero-compact-sub">Streamlit · LangChain · SQLite · Plotly</div></div>'
        '<div class="hero-compact-feature"><div class="hero-compact-label">LLMs</div>'
        '<div class="hero-compact-value">5+</div>'
        '<div class="hero-compact-sub">Gemma · Gemini · Claude · GPT...</div></div>'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ── architecture (About tab) ─────────────────────────────────────────────────
def render_architecture():
    """Mermaid architecture diagrams for the About tab. No expander — caller
    decides whether to wrap (the About tab renders these inline since the
    tab itself is the 'details' view)."""
    st.markdown(
        "**Data flow** — all four modes share data sources, but only the "
        "agent drives them itself (the dashed arrow):"
    )
    render_mermaid(DATA_FLOW_DIAGRAM, height=420)

    st.markdown("**Core-mode pipeline** — three-call adversarial panel:")
    render_mermaid(CORE_PIPELINE_DIAGRAM, height=240)

    st.markdown(
        "**Why core is the default** — three sequential LLM calls play different "
        "roles. The devil's advocate is forced to argue *against* the initial "
        "analyst, and the synthesizer weighs both sides. In practice this flips "
        "~30% of decisions, usually from over-bullish initial reads to more "
        "cautious final calls."
    )


# ── BYOK form (About tab) ────────────────────────────────────────────────────
def render_byok():
    """Provider/key/Ollama-URL form for the About tab. Read-only in demo."""
    with st.expander("🔑 Try it yourself (bring your own key)", expanded=False):
        st.caption("BYOK inputs are read-only in demo. See top banner for why.")
        st.markdown(
            "🔒 **Sandbox & privacy:** your session runs in an isolated database "
            "that disappears when you close this tab. Your API key lives only in "
            "browser session memory — never logged, stored, or sent anywhere "
            "except your chosen LLM provider."
        )

        chosen_label = st.selectbox(
            "Provider",
            PROVIDER_LABELS,
            key="byok_provider_label",
            index=0,
            disabled=True,
        )
        entry = get_by_label(chosen_label)

        if entry["needs_key"]:
            st.text_input(
                f"{entry['label']} API key",
                type="password",
                key="byok_api_key",
                placeholder=entry["key_placeholder"],
                help=f"Get a key at: {entry['key_help_url']}",
                disabled=True,
            )
        else:
            st.text_input(
                f"{entry['label']} server URL",
                key="byok_ollama_url",
                placeholder=entry["url_placeholder"],
                help=(
                    "If you run your own Ollama server, paste the URL here. "
                    "Otherwise leave blank."
                ),
                disabled=True,
            )
