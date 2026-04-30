"""Render news cards from the Finnhub-formatted text block."""
import streamlit as st

from .formatters import escape_dollars


def render_news(news_text):
    if not news_text:
        return
    current = {}
    for line in news_text.split("\n"):
        line = line.strip()
        if line.startswith("###"):
            if current.get("title"):
                _render_news_card(current)
                current = {}
            current["title"] = line.replace("###", "").strip()
        elif line.startswith("Date:"):
            current["date"] = line.replace("Date:", "").strip()
        elif line.startswith("Link:"):
            current["link"] = line.replace("Link:", "").strip()
        elif line and not line.startswith("##") and current.get("title"):
            current["summary"] = current.get("summary", "") + " " + line
    if current.get("title"):
        _render_news_card(current)


def _render_news_card(article):
    title = escape_dollars(article.get("title", ""))
    date = article.get("date", "")
    link = article.get("link", "")
    summary = escape_dollars(article.get("summary", "").strip())
    st.markdown(
        f'''<div style="background:#1a1a2e;border-left:3px solid #2a6496;padding:12px 16px;margin:8px 0;border-radius:4px">
<div style="font-size:15px;font-weight:600;color:#7ab8f5;margin-bottom:4px">{title}</div>
<div style="font-size:12px;color:#888;margin-bottom:6px">{date}</div>
<div style="font-size:14px;color:#cccccc;line-height:1.6;margin-bottom:8px">{summary}</div>
<a href="{link}" target="_blank" style="font-size:12px;color:#4a90d9">Read more →</a>
</div>''',
        unsafe_allow_html=True,
    )
