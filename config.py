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