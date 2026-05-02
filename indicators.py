"""
Technical indicators computed in-house, formatted to match TradingAgents output.

Replaces:
    route_to_vendor("get_indicators", ticker, indicator_name, today, days)

Supported indicators: macd, rsi, close_50_sma, close_10_ema
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import price_cache


# Descriptions matched to TradingAgents' get_indicators output for prompt continuity
INDICATOR_DESCRIPTIONS = {
    "macd": (
        "MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers "
        "and divergence as signals of trend changes. Tips: Confirm with other "
        "indicators in low-volatility or sideways markets."
    ),
    "rsi": (
        "RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply "
        "70/30 thresholds and watch for divergence to signal reversals. Tips: In "
        "strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. Usage: Identify trend direction and "
        "serve as dynamic support/resistance. Tips: It lags price; combine with faster "
        "indicators for timely signals."
    ),
    "close_10_ema": (
        "10 EMA: A responsive short-term average. Usage: Capture quick shifts in "
        "momentum and potential entry points. Tips: Prone to noise in choppy markets; "
        "use alongside longer averages for filtering false signals."
    ),
}


def _fetch_history(ticker, lookback_days=400):
    """Fetch enough history to compute indicators reliably (>200 days for SMA/EMA stability)."""
    cached = price_cache.get(ticker, "indicators_daily")
    if cached is not None:
        return cached
    df = yf.Ticker(ticker).history(period="2y", interval="1d")
    if not df.empty:
        price_cache.put(ticker, "indicators_daily", df)
    return df


def _compute_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    return ema12 - ema26


def _compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _compute_indicator(df, indicator):
    close = df["Close"]
    if indicator == "macd":
        return _compute_macd(close)
    if indicator == "rsi":
        return _compute_rsi(close)
    if indicator == "close_50_sma":
        return close.rolling(50).mean()
    if indicator == "close_10_ema":
        return close.ewm(span=10, adjust=False).mean()
    raise ValueError(f"Unknown indicator: {indicator}")


tool_get_indicator_text: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "get_indicator_text",
        "description": (
            "Get formatted indicator text. Returns the indicator value for each "
            "calendar day in the window, with non-trading days shown as N/A. "
            "Output ends with a description of how to interpret this indicator. "
            "Use one indicator per call — issue separate calls for MACD, RSI, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock symbol, e.g. 'NVDA'.",
                },
                "indicator": {
                    "type": "string",
                    "description": (
                        "Which indicator to compute. One of: "
                        "'macd' (momentum / trend-change signal), "
                        "'rsi' (overbought >70 / oversold <30), "
                        "'close_50_sma' (medium-term trend, dynamic support/resistance), "
                        "'close_10_ema' (short-term momentum, faster than SMA)."
                    ),
                    "enum": ["macd", "rsi", "close_50_sma", "close_10_ema"],
                },
                "days_back": {
                    "type": "integer",
                    "description": "Calendar-day window ending at today. Default 30. Non-trading days appear as N/A.",
                },
            },
            "required": ["ticker", "indicator"],
        },
    },
}


def get_indicator_text(ticker: str, indicator: str, today_str: str = None, days_back: int=30):
    """Returns formatted indicator text matching TradingAgents output structure.

    Output shape:
        ## <indicator> values from <start> to <today>:

        2026-04-27: N/A: Not a trading day (weekend or holiday)
        2026-04-24: 6.508380165266033
        ...

        <indicator description>
    """
    if today_str is None:
        today_str = datetime.now().strftime("%Y-%m-%d")
    df = _fetch_history(ticker)
    if df.empty:
        return f"No data available for {ticker}."

    # Compute indicator over the full series so longer windows (50 SMA, etc.) stabilize
    series = _compute_indicator(df, indicator)

    # Strip timezone for clean date parsing/comparison
    if hasattr(series.index, "tz") and series.index.tz is not None:
        series.index = series.index.tz_localize(None)

    today = datetime.strptime(today_str, "%Y-%m-%d")
    start = today - timedelta(days=days_back)

    # Build a list of every calendar date in the window (including weekends/holidays)
    all_dates = [today - timedelta(days=i) for i in range(days_back + 1)]

    # Index trading-day values by date for quick lookup
    by_date = {idx.date(): val for idx, val in series.items()}

    lines = [f"## {indicator} values from {start.strftime('%Y-%m-%d')} to {today_str}:", ""]
    for d in all_dates:
        d_key = d.date()
        if d_key in by_date and pd.notna(by_date[d_key]):
            lines.append(f"{d.strftime('%Y-%m-%d')}: {by_date[d_key]}")
        else:
            lines.append(f"{d.strftime('%Y-%m-%d')}: N/A: Not a trading day (weekend or holiday)")

    description = INDICATOR_DESCRIPTIONS.get(indicator, "")
    if description:
        lines.append("")
        lines.append("")
        lines.append(description)

    return "\n".join(lines)