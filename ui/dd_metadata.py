"""Deep-dive left-column metadata: decision badge + dates + costs."""
import streamlit as st


def render(row):
    decision_str = str(row["decision"]).upper()
    if "BUY" in decision_str or "OVERWEIGHT" in decision_str:
        badge = "🟢"
    elif "SELL" in decision_str or "UNDERWEIGHT" in decision_str:
        badge = "🔴"
    else:
        badge = "🟡"

    st.markdown(f"### {badge} {row['decision']}")
    st.markdown(f"**Date:** {row['run_date']}")
    st.markdown(f"**Mode:** {row.get('mode', '—')}")
    st.markdown(f"**Model:** {row.get('model', '—')}")
    st.markdown(f"**Host:** {row.get('host', '—')}")
    st.markdown(f"**Runtime:** {row.get('runtime_seconds', '—')}s")
    st.markdown(f"**Tokens:** {row['total_tokens']:,}")
    st.markdown(f"**Cost (Claude Sonnet):** ${row['cost_sonnet']:.4f}")
    st.markdown(f"**Cost (Claude Opus):** ${row['cost_opus']:.4f}")
    fallback_openai = row['prompt_tokens'] / 1e6 * 2.5 + row['completion_tokens'] / 1e6 * 15
    st.markdown(f"**Cost (GPT-5.4):** ${row.get('cost_openai', fallback_openai):.4f}")
    st.markdown(f"**Cost (Gemini 3.1):** ${row['cost_gemini']:.4f}")
