"""Streamlit cached wrappers around data sources."""
import streamlit as st
import yfinance as yf

from news import (
    days_until_earnings as _days_until_earnings_raw,
    get_earnings_calendar_finnhub,
    insider_summary_text,
    get_insider_transactions_finnhub,
)
from options import get_options_summary
from sentiment import stocktwits_summary


@st.cache_data(ttl=3600)
def days_until_earnings_cached(ticker):
    return _days_until_earnings_raw(ticker)


@st.cache_data(ttl=3600)
def get_earnings_event_cached(ticker):
    return get_earnings_calendar_finnhub(ticker)


@st.cache_data(ttl=900)
def stocktwits_cached(ticker):
    return stocktwits_summary(ticker)


@st.cache_data(ttl=3600)
def insider_summary_cached(ticker):
    return insider_summary_text(ticker)


@st.cache_data(ttl=3600)
def insider_transactions_cached(ticker, days_back=90):
    return get_insider_transactions_finnhub(ticker, days_back=days_back)


@st.cache_data(ttl=1800)
def options_summary_cached(ticker):
    return get_options_summary(ticker)


@st.cache_data(ttl=1800)
def options_chain_cached(ticker, expiry):
    """Returns (calls_records, puts_records) for the given expiry."""
    tk = yf.Ticker(ticker)
    chain = tk.option_chain(expiry)
    return chain.calls.to_dict("records"), chain.puts.to_dict("records")
