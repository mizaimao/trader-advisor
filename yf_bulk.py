"""Shared yfinance bulk-download primitives.

Used by peers.py and sector.py to amortize HTTP cost when fetching price
history across multiple symbols. Both consumers do their own per-shape
aggregation on top — this module owns the network primitives only, not
the per-consumer assembly.
"""
import pandas as pd
import yfinance as yf


def bulk_history(symbols: list[str], period: str):
    """yf.download wrapper. Returns DataFrame or None on bulk failure.

    With len(symbols) > 1, returns MultiIndex columns (symbol, field). With
    a single symbol, returns flat columns. `perf_from_bulk` handles both.
    """
    if not symbols:
        return None
    try:
        return yf.download(
            symbols,
            period=period,
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=False,  # callers own concurrency
        )
    except Exception:
        return None


def perf_from_bulk(df, symbol: str, *, mode: str) -> float | None:
    """Extract % change from a bulk-downloaded DataFrame for one symbol.

    `mode='last_two'` uses last two trading-day closes (e.g. 1d perf within
    a 5d window). `mode='first_last'` uses first vs last close (whole-period).
    """
    if df is None or len(df) == 0:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if symbol not in df.columns.get_level_values(0):
                return None
            closes = df[symbol]["Close"].dropna()
        else:
            # Single-symbol fallback (yfinance returns flat columns then)
            closes = df["Close"].dropna()

        if len(closes) < 2:
            return None

        if mode == "last_two":
            prev = float(closes.iloc[-2])
            cur = float(closes.iloc[-1])
        else:  # first_last
            prev = float(closes.iloc[0])
            cur = float(closes.iloc[-1])

        if prev == 0:
            return None
        return ((cur - prev) / prev) * 100
    except Exception:
        return None
