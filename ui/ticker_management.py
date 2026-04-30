"""Add/remove tracked tickers. Disabled in demo mode."""
import streamlit as st


def render(managed_tickers, save_tickers, demo_mode=False):
    label = "⚙️ Manage Tickers" + (" (read-only in demo)" if demo_mode else "")
    with st.expander(label):
        col_add, col_remove, col_list = st.columns([1, 1, 2])

        with col_add:
            new_ticker = st.text_input(
                "Add ticker",
                disabled=demo_mode,
                key="add_ticker_input",
            ).strip().upper()
            if st.button("Add", disabled=demo_mode, key="add_ticker_btn") and new_ticker:
                if new_ticker not in managed_tickers:
                    managed_tickers.append(new_ticker)
                    save_tickers(managed_tickers)
                    st.success(f"Added {new_ticker}")
                    st.rerun()
                else:
                    st.warning(f"{new_ticker} already exists")

        with col_remove:
            remove_ticker = st.selectbox(
                "Remove ticker",
                managed_tickers,
                disabled=demo_mode,
                key="remove_ticker_select",
            )
            if st.button("Remove", disabled=demo_mode, key="remove_ticker_btn"):
                managed_tickers.remove(remove_ticker)
                save_tickers(managed_tickers)
                st.success(f"Removed {remove_ticker}")
                st.rerun()

        with col_list:
            st.markdown("**Current tickers:**")
            st.write(", ".join(managed_tickers))
