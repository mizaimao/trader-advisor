"""Deep-dive options snapshot: 4 metric cards + volume-by-strike chart."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from .cache import options_chain_cached, options_summary_cached


def render(ticker_pick):
    st.markdown("**Options Snapshot**")
    opts = options_summary_cached(ticker_pick)
    if opts.get("error"):
        st.info(f"Options unavailable: {opts['error']}")
        return

    _render_cards(opts)

    expiry = opts.get("near_expiry")
    if expiry:
        _render_volume_chart(ticker_pick, expiry)


def _render_cards(opts):
    c1, c2, c3, c4 = st.columns(4)

    pc = opts.get("put_call_ratio")
    if pc is not None:
        sentiment = "Bearish" if pc > 1.0 else "Bullish" if pc < 0.7 else "Neutral"
        pc_color = "#ff4444" if pc > 1.0 else "#00ff00" if pc < 0.7 else "#ffff00"
        c1.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>P/C Ratio</div>"
            f"<div style='font-size:18px;color:{pc_color};font-weight:600'>{pc}</div>"
            f"<div style='font-size:11px;color:#888'>{sentiment}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    iv = opts.get("atm_iv")
    if iv:
        iv_pct = iv * 100
        iv_color = "#ff4444" if iv_pct > 50 else "#ffff00" if iv_pct > 30 else "#888"
        c2.markdown(
            f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
            f"<div style='font-size:11px;color:#888'>ATM IV</div>"
            f"<div style='font-size:18px;color:{iv_color};font-weight:600'>{iv_pct:.1f}%</div>"
            f"<div style='font-size:11px;color:#888'>Implied Vol</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    vol_total = opts.get("total_call_volume", 0) + opts.get("total_put_volume", 0)
    unusual = opts.get("unusual_volume")
    vol_color = "#ff4444" if unusual else "#888"
    vol_label = "⚠️ Unusual" if unusual else "Normal"
    c3.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Volume</div>"
        f"<div style='font-size:18px;color:{vol_color};font-weight:600'>{vol_total:,}</div>"
        f"<div style='font-size:11px;color:#888'>{vol_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    expiry = opts.get("near_expiry", "—")
    c4.markdown(
        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
        f"<div style='font-size:11px;color:#888'>Near Expiry</div>"
        f"<div style='font-size:18px;color:#7ab8f5;font-weight:600'>{expiry}</div>"
        f"<div style='font-size:11px;color:#888'>Calls/Puts: {opts.get('total_call_volume', 0):,} / {opts.get('total_put_volume', 0):,}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_volume_chart(ticker_pick, expiry):
    try:
        calls_records, puts_records = options_chain_cached(ticker_pick, expiry)
        calls_df = pd.DataFrame(calls_records)
        puts_df = pd.DataFrame(puts_records)

        spot_hist = yf.Ticker(ticker_pick).history(period="1d")
        spot = float(spot_hist["Close"].iloc[-1]) if not spot_hist.empty else None

        if calls_df.empty or puts_df.empty:
            return

        if spot:
            lo, hi = spot * 0.7, spot * 1.3
            calls_df = calls_df[(calls_df["strike"] >= lo) & (calls_df["strike"] <= hi)]
            puts_df = puts_df[(puts_df["strike"] >= lo) & (puts_df["strike"] <= hi)]

        calls_df = calls_df.fillna(0)
        puts_df = puts_df.fillna(0)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=calls_df["strike"], y=calls_df["volume"],
            name="Calls", marker_color="#1a8a1a",
            hovertemplate="Strike: $%{x}<br>Call Vol: %{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=puts_df["strike"], y=puts_df["volume"],
            name="Puts", marker_color="#a01a1a",
            hovertemplate="Strike: $%{x}<br>Put Vol: %{y:,.0f}<extra></extra>",
        ))
        if spot:
            fig.add_vline(
                x=spot, line=dict(color="#ffff00", dash="dash", width=1),
                annotation_text=f"Spot ${spot:.2f}",
                annotation_position="top",
            )
        fig.update_layout(
            height=300,
            margin=dict(l=0, r=0, t=30, b=0),
            barmode="group",
            xaxis_title=f"Strike (expiry {expiry})",
            yaxis_title="Volume",
            legend=dict(orientation="h", y=1.1),
            title=dict(text="Options Volume by Strike", font=dict(size=14)),
        )
        st.plotly_chart(fig, width="stretch")
    except Exception as e:
        st.caption(f"Volume chart unavailable: {e}")
