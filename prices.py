"""
Multi-timeframe price data for analysis context.

Returns curated views at different granularities:
- Last 30 days, daily candles (short-term setup)
- Last 1 year, weekly candles (medium-term trend)
- Last 5 years, monthly candles (long-term regime)
"""
import yfinance as yf
import pandas as pd
import price_cache


def _format_candles(df, granularity_label):
    """Convert OHLCV dataframe to compact text rows."""
    if df is None or df.empty:
        return f"No {granularity_label} data available."
    lines = []
    for date, row in df.iterrows():
        date_str = date.strftime("%Y-%m-%d")
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])
        v = int(row["Volume"]) if not pd.isna(row["Volume"]) else 0
        lines.append(f"{date_str}  O={o:.2f}  H={h:.2f}  L={l:.2f}  C={c:.2f}  V={v:,}")
    return "\n".join(lines)


def _fetch_with_cache(ticker, granularity, period, interval):
    """Returns DataFrame, hitting cache when possible."""
    cached = price_cache.get(ticker, granularity)
    if cached is not None:
        return cached
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    if not df.empty:
        price_cache.put(ticker, granularity, df)
    return df


tool_get_price_context: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "get_price_context",
        "description": (
            "Multi-timeframe price snapshot: last 30 daily candles, 1y weekly candles, "
            "5y monthly candles, plus a Quick Summary (current price, 30d/1y/5y change, "
            "5y high/low and distance from current). Almost always the first tool to call — "
            "it establishes the trend setup across timeframes, reveals whether the stock is "
            "at a regime extreme (near 5y high or low), and informs which follow-up tools "
            "matter (e.g. insider/options if near 5y high, news/sector if anomalous moves)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock symbol, e.g. 'NVDA'.",
                },
            },
            "required": ["ticker"],
        },
    },
}


def get_price_context(ticker):
    """Build the multi-timeframe price text block.

    Args:
        ticker: Stock symbol (e.g. "NVDA").

    Returns:
        Markdown text with four sections: Quick Summary (current, 30d/1y/5y
        % change, 5y high/low with % from current), then daily, weekly, and
        monthly candle tables (OHLCV). Returns an error string on yfinance
        failure rather than raising.
    """
    sections = []

    try:
        daily = _fetch_with_cache(ticker, "daily", period="1mo", interval="1d")
        weekly = _fetch_with_cache(ticker, "weekly", period="1y", interval="1wk")
        monthly = _fetch_with_cache(ticker, "monthly", period="5y", interval="1mo")

        # Quick summary stats from each timeframe (insert at top)
        if not daily.empty and not weekly.empty and not monthly.empty:
            current = float(daily["Close"].iloc[-1])
            d30_chg = ((current - float(daily["Close"].iloc[0])) / float(daily["Close"].iloc[0])) * 100
            y1_chg = ((current - float(weekly["Close"].iloc[0])) / float(weekly["Close"].iloc[0])) * 100
            y5_chg = ((current - float(monthly["Close"].iloc[0])) / float(monthly["Close"].iloc[0])) * 100
            high_5y = float(monthly["High"].max())
            low_5y = float(monthly["Low"].min())
            pct_from_5y_high = ((current - high_5y) / high_5y) * 100

            sections.append(
                f"### Quick Summary\n"
                f"Current: ${current:.2f}\n"
                f"30d change: {d30_chg:+.2f}%\n"
                f"1y change: {y1_chg:+.2f}%\n"
                f"5y change: {y5_chg:+.2f}%\n"
                f"5y high: ${high_5y:.2f} ({pct_from_5y_high:+.2f}% from current)\n"
                f"5y low: ${low_5y:.2f}"
            )

        sections.append(f"### Last 30 days (daily candles)\n{_format_candles(daily, 'daily')}")
        sections.append(f"### Last 1 year (weekly candles)\n{_format_candles(weekly, 'weekly')}")
        sections.append(f"### Last 5 years (monthly candles)\n{_format_candles(monthly, 'monthly')}")

        return "\n\n".join(sections)
    except Exception as e:
        return f"Price context unavailable: {e}"