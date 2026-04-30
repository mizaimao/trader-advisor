"""Deep-dive Reddit activity panel (via ApeWisdom)."""
import streamlit as st

from .cache import reddit_cached


def render(ticker_pick):
    st.markdown("**Reddit Activity (ApeWisdom)**")
    s = reddit_cached(ticker_pick)

    if not s.get("trending"):
        st.info(f"{ticker_pick} is not in the top ~100 trending tickers on Reddit. Low retail chatter.")
        return

    rank = s.get("rank", "?")
    mentions = s.get("mentions_24h", 0)
    delta = s.get("delta_pct")
    upvotes = s.get("upvotes", 0)
    score = s.get("sentiment_score")

    c1, c2, c3, c4 = st.columns(4)

    c1.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Reddit Rank</div>"
        f"<div style='font-size:18px;color:#7ab8f5;font-weight:600'>#{rank}</div>"
        f"<div style='font-size:11px;color:#888'>among trending</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    c2.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Mentions (24h)</div>"
        f"<div style='font-size:18px;color:#ffd966;font-weight:600'>{mentions:,}</div>"
        f"<div style='font-size:11px;color:#888'>{upvotes:,} upvotes</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if delta is not None:
        delta_color = "#00ff00" if delta > 0 else "#ff4444" if delta < 0 else "#888"
        delta_label = "🔥 surging" if delta > 100 else "rising" if delta > 0 else "fading"
        c3.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>Δ vs 24h ago</div>"
            f"<div style='font-size:18px;color:{delta_color};font-weight:600'>{delta:+.1f}%</div>"
            f"<div style='font-size:11px;color:#888'>{delta_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        c3.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>Δ vs 24h ago</div>"
            f"<div style='font-size:18px;color:#888;font-weight:600'>—</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if score is not None:
        if score >= 70:
            label, color = "strongly bullish", "#00ff00"
        elif score >= 55:
            label, color = "leaning bullish", "#88cc88"
        elif score <= 30:
            label, color = "strongly bearish", "#ff4444"
        elif score <= 45:
            label, color = "leaning bearish", "#cc8888"
        else:
            label, color = "neutral", "#ffff00"
        c4.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>Sentiment</div>"
            f"<div style='font-size:18px;color:{color};font-weight:600'>{score}/100</div>"
            f"<div style='font-size:11px;color:#888'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        c4.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>Sentiment</div>"
            f"<div style='font-size:18px;color:#888;font-weight:600'>—</div>"
            f"<div style='font-size:11px;color:#888'>not available</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
