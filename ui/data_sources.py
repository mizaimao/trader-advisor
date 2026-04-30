"""Per-source toggle panel for the dashboard.

Three sources are locked always-on (price, technical indicators, fundamentals)
because the model needs them to do anything useful. The other seven can be
toggled per-session; toggle state lives in st.session_state and is passed
to the runner subprocess via TRADER_ADVISOR_DISABLED_SOURCES (JSON list).

In demo mode all toggles are disabled — visible as documentation of what
feeds the model, not interactive controls.
"""
import streamlit as st

from .demo import DEMO_MODE


# Source rows: (id, label, brief description, sub_label of components)
LOCKED = [
    ("price", "Price",
     "Multi-timeframe candles + 5-year high/low context",
     "daily · weekly · monthly"),
    ("indicators", "Technical Indicators",
     "Computed from price data",
     "MACD · RSI · 50 SMA · 10 EMA"),
    ("fundamentals", "Fundamentals",
     "Per-company snapshot from yfinance",
     "PE · EPS · margins · debt · 52w range"),
]

TOGGLEABLE = [
    ("earnings", "Upcoming Earnings",
     "Next earnings calendar from Finnhub",
     "EPS / revenue estimates · days-to-event"),
    ("insider", "Insider Activity",
     "Form-4 transactions, last 30–90 days",
     "buys vs sells · net dollar flow"),
    ("options", "Options Activity",
     "Option chain snapshot from yfinance",
     "P/C ratio · ATM IV · unusual volume"),
    ("sector", "Sector & Macro Context",
     "Ticker vs sector ETF vs SPY/QQQ",
     "1d · 5d · 1mo relative performance"),
    ("stocktwits", "Social Sentiment",
     "Last 30 messages from StockTwits",
     "bullish/bearish tagged %"),
    ("reddit", "Reddit Activity",
     "ApeWisdom mention counts across stock subs",
     "rank · 24h delta · sentiment score"),
    ("news", "Recent News",
     "Last 7 days of company news from Finnhub",
     "headlines + summaries"),
]


def _key(src_id):
    return f"src_{src_id}"


def init_defaults():
    """Set toggleable sources to ON if not already in session state."""
    for src_id, *_ in TOGGLEABLE:
        st.session_state.setdefault(_key(src_id), True)


def disabled_sources():
    """Return the set of toggleable source ids that are currently OFF."""
    init_defaults()
    return {sid for sid, *_ in TOGGLEABLE if not st.session_state.get(_key(sid), True)}


def _row(src_id, label, brief, sub, *, locked):
    cols = st.columns([2.2, 5])
    with cols[0]:
        if locked:
            st.checkbox(label, value=True, disabled=True, key=_key(src_id))
        else:
            st.checkbox(label, disabled=DEMO_MODE, key=_key(src_id))
    with cols[1]:
        st.markdown(
            "<div style='padding-top:6px'>"
            f"<span style='color:#bbb'>{brief}</span>  "
            f"<span style='color:#888;font-size:11px'>· {sub}</span>"
            "</div>",
            unsafe_allow_html=True,
        )


def render():
    init_defaults()

    label = "📡 Data Sources — what feeds the model"
    if DEMO_MODE:
        label += "  (demo: read-only)"

    with st.expander(label, expanded=False):
        st.caption(
            "Three sources are always on. The other seven can be toggled — "
            "the runner skips the fetch entirely when off, so this is also "
            "a way to save quota."
        )

        st.markdown("**Always on**")
        for row in LOCKED:
            _row(*row, locked=True)

        st.markdown("**Optional**")
        for row in TOGGLEABLE:
            _row(*row, locked=False)

        on_count = sum(
            1 for sid, *_ in TOGGLEABLE
            if st.session_state.get(_key(sid), True)
        )
        if on_count < 3:
            st.warning(
                f"⚠️ Reduced context — analysis quality will degrade "
                f"({on_count} of 7 optional sources on)."
            )
