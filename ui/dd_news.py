"""Deep-dive latest news with adjustable lookback slider."""
from datetime import datetime, timedelta

import streamlit as st

from news import get_news_finnhub
from .render_news import render_news


def render(ticker_pick):
    with st.expander("📰 Latest News", expanded=False):
        days_back = st.slider("Days back", 1, 14, 3)
        end = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        render_news(get_news_finnhub(ticker_pick, start, end))
