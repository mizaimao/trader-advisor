"""Add/remove tracked tickers."""
import streamlit as st


def render(managed_tickers, save_tickers):
    with st.expander("⚙️ Manage Tickers"):
        col_add, col_remove, col_list = st.columns([1, 1, 2])
        with col_add:
            new_ticker = st.text_input("Add ticker").strip().upper()
            if st.button("Add") and new_ticker:
                if new_ticker not in managed_tickers:
                    managed_tickers.append(new_ticker)
                    save_tickers(managed_tickers)
                    st.success(f"Added {new_ticker}")
                    st.rerun()
                else:
                    st.warning(f"{new_ticker} already exists")
        with col_remove:
            remove_ticker = st.selectbox("Remove ticker", managed_tickers)
            if st.button("Remove"):
                managed_tickers.remove(remove_ticker)
                save_tickers(managed_tickers)
                st.success(f"Removed {remove_ticker}")
                st.rerun()
        with col_list:
            st.markdown("**Current tickers:**")
            st.write(", ".join(managed_tickers))
