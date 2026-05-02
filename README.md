# trader-advisor

Personal short-term-trading dashboard with multi-mode LLM-driven analysis. Four pipelines, ten data sources, one toolbox the LLM can drive itself.

## Modes

- **solo** — single LLM call. Fast (~30s), single perspective. Workflow.
- **core** (default) — 3-call adversarial panel: initial analyst, devil's advocate, synthesizer. Flips ~30% of decisions vs solo. ~60s. Workflow.
- **full** — TradingAgents 7-agent debate graph (debate + risk management). Slowest, most thorough. Requires the optional `tradingagents` package. Multi-agent.
- **agent** — autonomous tool-use loop. The LLM picks which of 12 data tools to call, in what order, based on what it learns each step. Bounded by a tool-call budget. ~60-120s. Genuinely agentic.

The first three modes are **workflows** in the Anthropic sense — the developer specifies the steps, the LLM fills them in. The fourth mode is an **agent** — the LLM decides its own steps, with `peer_comparison` as the standout tool because the model picks the comparison set itself.

## Components

| File | Role |
|------|------|
| `runner.py` | Analysis orchestrator (CLI entry point) |
| `dashboard.py` | Streamlit web UI |
| `bot.py` | Telegram bot (prod-only) |
| `prompts.py` | Externalized prompt templates |
| `agent/loop.py` | Tool-use loop for `--agent` mode |
| `prices.py` | Multi-timeframe yfinance price context |
| `indicators.py` | MACD / RSI / SMA / EMA computed in-house |
| `fundamentals.py` | Per-company snapshot from yfinance |
| `news.py` | Finnhub news + earnings + insider activity |
| `options.py` | yfinance options snapshot |
| `sector.py` | Dynamic sector + industry ETF benchmarks |
| `sentiment.py` | StockTwits + Reddit/ApeWisdom |
| `peers.py` | Cross-ticker peer comparison (agent-only) |
| `yf_bulk.py` | Shared yfinance bulk-download primitives |
| `price_cache.py` | SQLite cache for price data |
| `db.py` | SQLite storage for analysis runs |
| `config.py` | Provider/model/ticker config |
| `debug_context.py` | Print the full prompt sent to the LLM |

## Setup

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    # edit .env with your API keys
    python -c "from db import init_db; init_db()"

For `full` mode, also install TradingAgents:

    pip install git+https://github.com/TauricResearch/TradingAgents.git

For `agent` mode, no extra dependency — just an Ollama server reachable at `OLLAMA_BASE_URL` running a tool-use-capable model (`gpt-oss:20b` recommended).

## Usage

Tickers are passed as a single comma-separated argument (no spaces).

Default (core, 3-call adversarial panel):

    python runner.py --tickers NVDA,AMD

Solo (single fast call):

    python runner.py --tickers NVDA --solo

Full (TradingAgents pipeline):

    python runner.py --tickers NVDA --full

Agent (tool-use loop, model picks data sources):

    python runner.py --tickers NVDA --agent

Dashboard:

    streamlit run dashboard.py

Telegram bot:

    python bot.py

## Architecture

The first three modes share a common `fetch_context()` builder that pulls multi-timeframe prices, earnings calendar, insider activity, options snapshot, sector performance, technical indicators, fundamentals, sentiment, and recent news into a single structured prompt payload — *fixed* context, dumped upfront.

- **solo** runs that payload through a single LLM call.
- **core** runs three sequential LLM calls — the second argues against the first, the third synthesizes both.
- **full** hands off to the TradingAgents multi-agent graph.
- **agent** does NOT use the upfront context dump. Instead, the model gets a toolbox of 12 functions wrapping the same data sources (`get_price_context`, `get_indicator_text`, `peer_comparison`, etc.) and decides which to call, in what order, based on what each result reveals. The loop tracks a tool-call budget; the model self-rations across steps. Every step is captured in a structured trace, persisted as JSON in the run's DB row, and rendered as a vertical timeline in the dashboard's deep-dive view.

Results are persisted to `~/.tradingagents/trading.db`. Price data is cached separately in `~/.tradingagents/price_cache.db`.

## Design docs

- `docs/agent_phase1_spec.md` — full spec for the agent mode (tool schemas, loop structure, provider abstraction, build order)
- `NOTES.md` — running journal of design decisions and observed agent pathologies
