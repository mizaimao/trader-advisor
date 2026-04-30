"""Demo mode toggles. Activated by TRADER_ADVISOR_DEMO_MODE env var."""
import os

DEMO_MODE = os.getenv("TRADER_ADVISOR_DEMO_MODE", "").lower() in ("1", "true", "yes")

DEMO_TICKERS = ["NVDA", "MSFT", "AAPL", "GOOGL", "TSLA", "AMD", "AMZN", "META"]


def is_demo():
    return DEMO_MODE