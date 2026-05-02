# Project Notes

## 2026-05-02 — Project repositioning: adding agent mode

Decision: `gpt-oss:20b` on the ml39 Ollama server is the v1 default; `gemma4:26b` is the local fallback. No automatic fallback logic.

Qwen3.6 35B-A3B Q4_K_M doesn't fit. Model alone is 24GB.

tool schema's `description` field is written and tuned independently from the Python function's docstring. 


1. Final analysis loses nuance from intermediate reasoning.
2.  Agent forgets its own plan across turns. ~ num_ctx???
3. Agent flags questions but doesn't follow through.
4. Strategy branches don't fire reliably.
5. News tool returns mostly off-topic articles.

Need to write new tools for the agent

Some tools/function calls may return empty or None objects. Need to deal with it in the agent loop.

The sector information should be fine-tuned by each stock as the current default is not a great reflection.

GPT-OSS 20B sometimes decides to terminate the loop early, and sometimes requests weird tickers like "NVUPCOMING". Tuned down temp to 0.3 now.

## 2026-05-02 — Sector tool: dynamic ETF selection at two levels
We want a comparsion of single stock to a sector.

1. Map ticker's sector → sector ETF (XLK / XLF / XLV / etc). Not good enough but info (noise?)
2. So two levels: Sector ETF and then Industry ETF

Big problem: I cannot reliably enable demo mode because it takes more than one API key.
That means even if I fix the streamlit bug it will still need keys from e.g. alpha_vantage, finnhub, telegram.