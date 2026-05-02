"""30-day earnings calendar overview.

Two render shapes:
- `wrap_in_expander=True` (default) — wrapped in a foldable expander
- `wrap_in_expander=False` — inline heading + dataframe, no expander

Run Explorer uses the inline form (placed right under the price chart);
the standalone Overview / About usage uses the expander form.
"""
import pandas as pd
import streamlit as st

from .cache import days_until_earnings_cached, get_earnings_event_cached
from .formatters import earnings_label


def render(managed_tickers, *, wrap_in_expander=True):
    if wrap_in_expander:
        with st.expander("📅 Earnings Calendar (next 30 days)", expanded=False):
            _render_body(managed_tickers)
    else:
        st.markdown("**📅 Upcoming Earnings (next 30 days)**")
        _render_body(managed_tickers)


def _render_body(managed_tickers):
    upcoming = []
    for ticker in managed_tickers:
        try:
            days = days_until_earnings_cached(ticker)
            if days is not None and days <= 30:
                event = get_earnings_event_cached(ticker)
                if event:
                    upcoming.append({
                        "ticker": ticker,
                        "days": days,
                        "date": event.get("date", "—"),
                        "eps_estimate": event.get("epsEstimate"),
                        "revenue_estimate": event.get("revenueEstimate"),
                        "hour": event.get("hour", "—"),
                    })
        except Exception:
            pass

    if upcoming:
        upcoming.sort(key=lambda x: x["days"])
        cal_df = pd.DataFrame(upcoming)
        cal_df["countdown"] = cal_df["days"].apply(earnings_label)
        display_df = cal_df[
            ["ticker", "countdown", "date", "hour", "eps_estimate", "revenue_estimate"]
        ]
        display_df.columns = ["Ticker", "In", "Date", "Time", "EPS Est.", "Revenue Est."]
        st.dataframe(display_df, width="stretch", hide_index=True)
    else:
        st.caption("No earnings scheduled within the next 30 days.")
