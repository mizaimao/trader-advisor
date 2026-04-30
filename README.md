# moose-trader

Personal short-term-trading dashboard with multi-mode LLM-driven analysis.

## Modes

- **solo** — single LLM call. Fast (~30s), single perspective.
- **core** (default) — 3-call adversarial panel: initial analyst, devil's advocate, synthesizer. Surfaces blind spots a single-pass analyst misses. ~60s.
- **full** — TradingAgents 7-agent graph (debate + risk management). Slowest, most thorough. Requires the optional `tradingagents` package.

## Components

| File | Role |
|------|------|
| `runner.py` | Analysis orchestrator (CLI entry point) |
| `dashboard.py` | Streamlit web UI |
| `bot.py` | Telegram bot |
| `prompts.py` | Externalized prompt templates |
| `prices.py` | Multi-timeframe yfinance price context |
| `price_cache.py` | SQLite cache for price data |
| `news.py` | Finnhub news, earnings, insider activity |
| `options.py` | yfinance options snapshot |
| `sector.py` | Sector/macro relative performance |
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

## Usage

Tickers are passed as a single comma-separated argument (no spaces).

Default (core, 3-call adversarial panel):

    python runner.py --tickers NVDA,AMD

Solo (single fast call):

    python runner.py --tickers NVDA --solo

Full (TradingAgents pipeline):

    python runner.py --tickers NVDA --full

Dashboard:

    streamlit run dashboard.py

Telegram bot:

    python bot.py

## Architecture

All three modes share a common `fetch_context()` builder that pulls multi-timeframe prices, earnings calendar, insider activity, options snapshot, sector performance, technical indicators, fundamentals, and recent news into a single structured prompt payload.

Solo runs that payload through a single LLM call. Core runs three sequential LLM calls — the second argues against the first, and the third synthesizes both. Full hands off to the TradingAgents multi-agent graph.

Results are persisted to `~/.tradingagents/trading.db`. Price data is cached separately in `~/.tradingagents/price_cache.db`.
