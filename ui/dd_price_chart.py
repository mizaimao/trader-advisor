"""Deep-dive right-column: 6mo candlestick + volume + MACD + RSI subplots."""
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots


def render(ticker_pick):
    hist = yf.Ticker(ticker_pick).history(period="6mo")
    if hist.empty:
        st.info("No price history available.")
        return

    hist["MA50"] = hist["Close"].rolling(50).mean()
    hist["MA200"] = hist["Close"].rolling(200).mean()
    exp12 = hist["Close"].ewm(span=12).mean()
    exp26 = hist["Close"].ewm(span=26).mean()
    hist["MACD"] = exp12 - exp26
    hist["Signal"] = hist["MACD"].ewm(span=9).mean()
    hist["Histogram"] = hist["MACD"] - hist["Signal"]
    delta = hist["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    hist["RSI"] = 100 - (100 / (1 + rs))

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.15, 0.2, 0.15],
        vertical_spacing=0.03,
        subplot_titles=("Price", "Volume", "MACD", "RSI"),
    )
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="Price", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist["MA50"], line=dict(color="orange", width=1), name="MA50"), row=1, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist["MA200"], line=dict(color="blue", width=1), name="MA200"), row=1, col=1)

    vol_colors = ["green" if c >= o else "red" for c, o in zip(hist["Close"], hist["Open"])]
    fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"], marker_color=vol_colors, name="Volume", showlegend=False), row=2, col=1)

    macd_colors = ["green" if v >= 0 else "red" for v in hist["Histogram"]]
    fig.add_trace(go.Bar(x=hist.index, y=hist["Histogram"], marker_color=macd_colors, name="Histogram", showlegend=False), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist["MACD"], line=dict(color="blue", width=1), name="MACD"), row=3, col=1)
    fig.add_trace(go.Scatter(x=hist.index, y=hist["Signal"], line=dict(color="orange", width=1), name="Signal"), row=3, col=1)

    fig.add_trace(go.Scatter(x=hist.index, y=hist["RSI"], line=dict(color="purple", width=1), name="RSI", showlegend=False), row=4, col=1)
    fig.add_hline(y=70, line=dict(color="red", dash="dash", width=1), row=4, col=1)
    fig.add_hline(y=30, line=dict(color="green", dash="dash", width=1), row=4, col=1)

    fig.update_layout(
        height=600,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.05),
    )
    fig.update_yaxes(title_text="RSI", row=4, col=1, range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)
