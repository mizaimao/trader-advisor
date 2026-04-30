"""Deep-dive header: scroll anchor + run selector + history window picker."""
import time
from datetime import datetime, timedelta

import streamlit as st


def maybe_scroll():
    """If session flag is set, emit JS to scroll to the deep-dive heading."""
    if not st.session_state.get("scroll_to_deep_dive"):
        return
    st.session_state["scroll_to_deep_dive"] = False
    nonce = int(time.time() * 1000)
    st.html(
        f"""
        <script>
        // nonce: {nonce}
        const tryScroll = () => {{
            const doc = window.parent.document;
            const el = doc.getElementById("deep-dive-anchor")
                || Array.from(doc.querySelectorAll('h2,h3'))
                    .find(h => h.textContent.includes("Deep Dive"));
            if (el) {{
                el.scrollIntoView({{behavior: "smooth", block: "start"}});
                return true;
            }}
            return false;
        }};
        let attempts = 0;
        const interval = setInterval(() => {{
            if (tryScroll() || attempts++ > 20) clearInterval(interval);
        }}, 100);
        </script>
        """
    )


def select_run(ticker_runs_all):
    """Render the history window + run-label dropdowns. Returns the selected row, or None."""
    col_window, col_run = st.columns([1, 3])
    with col_window:
        window = st.selectbox(
            "History window",
            ["Last 7 days", "Last 30 days", "All time"],
            index=0,
            key="history_window",
        )

    cutoff_days = {"Last 7 days": 7, "Last 30 days": 30, "All time": 99999}[window]
    cutoff_date = (datetime.today() - timedelta(days=cutoff_days)).strftime("%Y-%m-%d")
    ticker_runs = (
        ticker_runs_all[ticker_runs_all["run_date"] >= cutoff_date]
        .sort_values("id", ascending=False)
        .reset_index(drop=True)
    )

    if ticker_runs.empty:
        st.info(f"No runs in {window.lower()}. Try a wider window.")
        return None, ticker_runs

    ticker_runs["run_label"] = ticker_runs.apply(
        lambda r: f"#{r['id']} | {r['run_date']} | {r['mode']} | {str(r.get('created_at', ''))[:16]}",
        axis=1,
    )
    with col_run:
        run_label_pick = st.selectbox(
            "Select Run",
            ticker_runs["run_label"].tolist(),
            index=0,
        )
    row = ticker_runs[ticker_runs["run_label"] == run_label_pick].iloc[0]
    return row, ticker_runs
