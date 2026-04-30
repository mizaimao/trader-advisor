"""Deep-dive social sentiment (StockTwits): 4 metric cards + recent messages."""
import streamlit as st

from .cache import stocktwits_cached


def render(ticker_pick):
    st.markdown("**Social Sentiment (StockTwits)**")
    sent = stocktwits_cached(ticker_pick)
    if sent.get("error"):
        st.info(f"Sentiment unavailable: {sent['error']}")
        return

    bull = sent.get("bullish_pct", 0)
    bear = sent.get("bearish_pct", 0)
    total = sent.get("total", 0)
    tagged = sent.get("bullish", 0) + sent.get("bearish", 0)

    if tagged == 0:
        label, color = "no tagged sentiment", "#888"
    elif bull > bear * 2:
        label, color = "strongly bullish", "#00ff00"
    elif bull > bear:
        label, color = "leaning bullish", "#88cc88"
    elif bear > bull * 2:
        label, color = "strongly bearish", "#ff4444"
    elif bear > bull:
        label, color = "leaning bearish", "#cc8888"
    else:
        label, color = "mixed", "#ffff00"

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Sentiment</div>"
        f"<div style='font-size:18px;color:{color};font-weight:600'>{label}</div>"
        f"<div style='font-size:11px;color:#888'>last {total} msgs</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    c2.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Bullish</div>"
        f"<div style='font-size:18px;color:#00ff00;font-weight:600'>{bull}%</div>"
        f"<div style='font-size:11px;color:#888'>{sent.get('bullish', 0)} msgs</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    c3.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Bearish</div>"
        f"<div style='font-size:18px;color:#ff4444;font-weight:600'>{bear}%</div>"
        f"<div style='font-size:11px;color:#888'>{sent.get('bearish', 0)} msgs</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    c4.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Untagged</div>"
        f"<div style='font-size:18px;color:#888;font-weight:600'>{sent.get('untagged', 0)}</div>"
        f"<div style='font-size:11px;color:#888'>no label</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Recent messages"):
        for m in sent.get("sample_messages", []):
            sent_color = "#00ff00" if m["sentiment"] == "Bullish" else "#ff4444" if m["sentiment"] == "Bearish" else "#888"
            body_safe = m["body"].replace("$", "&#36;")
            st.markdown(
                f"<div style='padding:8px;background:#1a1a2e;border-left:3px solid {sent_color};margin:6px 0;border-radius:4px'>"
                f"<div style='font-size:11px;color:#888'>@{m['user']} · {m['time'][:16]} · <span style='color:{sent_color}'>{m['sentiment']}</span></div>"
                f"<div style='font-size:13px;color:#ccc;margin-top:4px'>{body_safe}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
