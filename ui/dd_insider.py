"""Deep-dive insider activity: 90-day buy/sell bar chart + transaction table."""
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .cache import insider_transactions_cached


def render(ticker_pick):
    st.markdown("**Insider Activity (last 90 days)**")
    insider_data = insider_transactions_cached(ticker_pick, days_back=90)
    transactions = insider_data.get("transactions", [])

    if not transactions:
        st.info("No insider transactions in last 90 days.")
        return

    tx_df = pd.DataFrame([
        {
            "date": tx.get("transactionDate"),
            "value": (tx.get("change", 0) or 0) * (tx.get("transactionPrice", 0) or 0),
            "name": tx.get("name", "?"),
            "code": tx.get("transactionCode", "?"),
            "shares": tx.get("change", 0) or 0,
            "price": tx.get("transactionPrice", 0) or 0,
        }
        for tx in transactions
    ])
    tx_df = tx_df[tx_df["date"].notna()]
    tx_df["date"] = pd.to_datetime(tx_df["date"])
    tx_df["direction"] = tx_df["value"].apply(lambda v: "Buy" if v > 0 else "Sell")
    daily = tx_df.groupby([tx_df["date"].dt.date, "direction"])["value"].sum().reset_index()
    daily.columns = ["date", "direction", "value"]
    daily["abs_value"] = daily["value"].abs()

    fig = go.Figure()
    buys = daily[daily["direction"] == "Buy"]
    sells = daily[daily["direction"] == "Sell"]
    if not buys.empty:
        fig.add_trace(go.Bar(
            x=buys["date"], y=buys["abs_value"],
            name="Buy", marker_color="#1a8a1a",
            hovertemplate="%{x}<br>Buy: $%{y:,.0f}<extra></extra>",
        ))
    if not sells.empty:
        fig.add_trace(go.Bar(
            x=sells["date"], y=sells["abs_value"],
            name="Sell", marker_color="#a01a1a",
            hovertemplate="%{x}<br>Sell: $%{y:,.0f}<extra></extra>",
        ))

    end_date = datetime.today()
    start_date = end_date - timedelta(days=90)
    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=10, b=0),
        barmode="group",
        yaxis_title="USD",
        legend=dict(orientation="h", y=1.1),
        xaxis=dict(
            type="date",
            range=[start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
        ),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Transaction details"):
        show_df = tx_df[["date", "name", "code", "shares", "price", "value"]].copy()
        show_df["date"] = show_df["date"].dt.strftime("%Y-%m-%d")
        show_df = show_df.sort_values("date", ascending=False)
        st.dataframe(show_df, use_container_width=True, hide_index=True)
