# config.py
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Paths
TICKERS_FILE = os.path.expanduser("~/.tradingagents/tickers.txt")
RATE_LOG = os.path.expanduser("~/.tradingagents/rate_log.json")

# Provider config
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = "gemma4:26b"
GEMINI_MODEL = "gemini-flash-latest"

# Per-mode Ollama context window (num_ctx). Sized from measured prompt
# footprints plus completion + safety margin:
#   solo  — single call, ~6-7K prompt, 2K completion
#   core  — 3 calls, synthesizer turn carries prior responses (~12-14K input)
#   agent — tool results accumulate across turns; this is the heaviest
# Full mode is omitted: TradingAgents manages its own LLM clients and falls
# back to the Ollama server's OLLAMA_CONTEXT_LENGTH default.
OLLAMA_NUM_CTX_BY_MODE = {
    "solo":  16_384,
    "core":  32_768,
    # Agent's tool-call loop accumulates ALL prior tool results in the
    # conversation; 21 tool calls × ~3K each + thinking traces can blow
    # past 60K. Setting 128K so a long-running multi-tool agent doesn't
    # silently truncate the head of the message list and start re-fetching
    # data it already has. KV cache for gpt-oss:120b at 128K ≈ 25 GB,
    # fits comfortably on the 96 GB host with NUM_PARALLEL=1.
    "agent": 131_072,
}


# ── Telegram bot — short-name resolution ─────────────────────────────────────
# Users text the bot in shorthand like "nvda qwen agent". MODEL_ALIASES maps
# each casual fragment to the canonical Ollama model id. Aliases are
# matched case-insensitively. Multiple aliases may resolve to the same model.
MODEL_ALIASES: dict[str, str] = {
    # qwen family. Bare "qwen" defaults to qwen3.6:35b — frontier-class on
    # reasoning tasks while staying fast enough for daily-driver agent runs.
    # The 122B is reachable via "qwen122" / "qwen3.5" for premium runs.
    "qwen":         "qwen3.6:35b",
    "qwen122":      "qwen3.5:122b",
    "qwen3.5":      "qwen3.5:122b",
    "qwen32":       "qwen3:32b",
    "qwen3":        "qwen3:32b",
    "qwen35":       "qwen3.6:35b",
    "qwen3.6":      "qwen3.6:35b",
    # gpt-oss family
    "gpt":          "gpt-oss:120b",
    "gpt-oss":      "gpt-oss:120b",
    "gptoss":       "gpt-oss:120b",
    "gpt120":       "gpt-oss:120b",
    "gpt20":        "gpt-oss:20b",
    # gemma family
    "gemma":        "gemma4:26b",
    "gemma4":       "gemma4:26b",
    "gemma26":      "gemma4:26b",
    "gemma31":      "gemma4:31b",
    # llama
    "llama":        "llama3.3:70b",
    "llama3":       "llama3.3:70b",
    "llama70":      "llama3.3:70b",
    # deepseek r1
    "deepseek":     "deepseek-r1:32b",
    "r1":           "deepseek-r1:32b",
    "ds":           "deepseek-r1:32b",
}

MODE_ALIASES: dict[str, str] = {
    "solo":  "solo",
    "core":  "core",
    "full":  "full",
    "agent": "agent",
    "auto":  "agent",
}


# Per-model agent budgets — used when launching agent runs from the bot.
# Match Ollama's "natural" context size for each model so the model doesn't
# need to reload between runs (reload costs ~30-60s for the 100B+ models).
# Fall back to AGENT_BUDGETS_DEFAULT for unknown models.
AGENT_BUDGETS_BY_MODEL: dict[str, dict] = {
    "qwen3.5:122b":   {"max_tool_calls": 30, "max_tokens": 2_000_000, "num_ctx": 262_144},
    "gpt-oss:120b":   {"max_tool_calls": 20, "max_tokens":   500_000, "num_ctx": 131_072},
    "gpt-oss:20b":    {"max_tool_calls": 12, "max_tokens":   200_000, "num_ctx":  32_768},
    "qwen3.6:35b":    {"max_tool_calls": 15, "max_tokens":   300_000, "num_ctx":  65_536},
    "qwen3:32b":      {"max_tool_calls": 15, "max_tokens":   300_000, "num_ctx":  65_536},
    "llama3.3:70b":   {"max_tool_calls": 15, "max_tokens":   300_000, "num_ctx":  65_536},
    "deepseek-r1:32b":{"max_tool_calls": 15, "max_tokens":   300_000, "num_ctx":  65_536},
    "gemma4:26b":     {"max_tool_calls": 12, "max_tokens":   200_000, "num_ctx":  32_768},
    "gemma4:31b":     {"max_tool_calls": 12, "max_tokens":   200_000, "num_ctx":  32_768},
}

AGENT_BUDGETS_DEFAULT: dict = {
    "max_tool_calls": 12,
    "max_tokens":     200_000,
    "num_ctx":         32_768,
}


# Stuck-run detection — Telegram bot nudges the user with [Kill]/[Wait]
# buttons when the current ticker has been running longer than this.
# Thresholds derived from the runs DB: roughly 3× P95 per mode, so a
# legitimately slow run (network blip, big context reload) doesn't false-
# positive but a truly hung process surfaces within a few minutes.
STUCK_THRESHOLD_SECONDS: dict[str, int] = {
    "solo":   90,    # p95 32s
    "core":   240,   # p95 84s
    "agent":  240,   # p95 80s
    "full":   900,   # p95 322s; full mode is genuinely slow
}


def get_agent_budget(model: str) -> dict:
    """Return the agent-mode budget for a model. Falls back to defaults
    for unknown models."""
    return AGENT_BUDGETS_BY_MODEL.get(model, AGENT_BUDGETS_DEFAULT)


def resolve_model(token: str) -> str | None:
    """Map a bot shorthand model token to a canonical Ollama model id.

    Returns None if no alias matches and the token doesn't look like a
    raw model id (no colon). If the token contains a colon (e.g.
    "gpt-oss:20b"), returns it verbatim — assumed to already be canonical.
    """
    if not token:
        return None
    if ":" in token:
        return token  # already canonical, e.g. "qwen3:32b"
    return MODEL_ALIASES.get(token.lower())


def resolve_mode(token: str) -> str | None:
    """Map a bot shorthand mode token to a canonical mode name."""
    if not token:
        return None
    return MODE_ALIASES.get(token.lower())

def get_provider():
    """Resolve provider from CLI args or env."""
    provider = os.getenv("LLM_PROVIDER", "ollama")
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        provider = sys.argv[idx + 1]
    return provider

def get_model(provider):
    return GEMINI_MODEL if provider == "gemini" else OLLAMA_MODEL

def get_tickers():
    """Resolve tickers from CLI args or file."""
    if "--tickers" in sys.argv:
        idx = sys.argv.index("--tickers")
        return sys.argv[idx + 1].split(",")
    if not os.path.exists(TICKERS_FILE):
        return ["NVDA"]
    with open(TICKERS_FILE) as f:
        return [t.strip().upper() for t in f.readlines() if t.strip()]

def log_request(provider):
    """Log LLM API request for rate tracking."""
    import json
    from datetime import datetime, timedelta
    now = datetime.now().isoformat()
    entries = []
    if os.path.exists(RATE_LOG):
        try:
            with open(RATE_LOG) as f:
                entries = json.load(f)
        except:
            pass
    entries.append({"time": now, "provider": provider})
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    entries = [e for e in entries if e["time"] > cutoff]
    os.makedirs(os.path.dirname(RATE_LOG), exist_ok=True)
    with open(RATE_LOG, "w") as f:
        json.dump(entries, f)