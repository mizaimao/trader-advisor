"""
Sector/macro context using yfinance.

Auto-detects each ticker's sector via yfinance.info, then maps to a representative
sector ETF for performance comparison. SPY and QQQ are always included as broad
market context.
"""
import yfinance as yf

# yfinance sector → representative ETF
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
}

# Cache sector lookups in-process to avoid repeat yfinance calls
_sector_cache = {}

def get_sector(ticker):
    """Returns yfinance sector string for a ticker, or None."""
    if ticker in _sector_cache:
        return _sector_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        _sector_cache[ticker] = sector
        return sector
    except Exception:
        _sector_cache[ticker] = None
        return None

def get_sector_etf(ticker):
    """Returns the ETF symbol that represents the ticker's sector."""
    sector = get_sector(ticker)
    return SECTOR_ETF_MAP.get(sector) if sector else None

def _pct_change(symbol, period):
    """Returns % change over the period (e.g. '5d', '1mo'). Returns None on error."""
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty or len(hist) < 2:
            return None
        first = float(hist["Close"].iloc[0])
        last = float(hist["Close"].iloc[-1])
        return ((last - first) / first) * 100
    except Exception:
        return None

def get_sector_context(ticker):
    """Returns dict with ticker vs SPY/QQQ/sector performance over 1d, 5d, 1mo.
    
    Shape:
      {
        "sector": "Technology",
        "sector_etf": "XLK",
        "ticker": {"1d": 1.2, "5d": 4.5, "1mo": 12.3},
        "spy":    {"1d": 0.3, "5d": 1.1, "1mo": 3.2},
        "qqq":    {"1d": 0.5, "5d": 1.8, "1mo": 5.1},
        "sector_etf_perf": {"1d": 0.4, "5d": 1.5, "1mo": 4.0},
      }
    """
    sector = get_sector(ticker)
    sector_etf = get_sector_etf(ticker)

    result = {
        "sector": sector,
        "sector_etf": sector_etf,
        "ticker": {},
        "spy": {},
        "qqq": {},
        "sector_etf_perf": {},
    }

    for period_label, period in [("1d", "5d"), ("5d", "1mo"), ("1mo", "3mo")]:
        # yfinance "5d" period gives ~5 trading days; use last 2 entries for "1d"
        if period_label == "1d":
            for sym, key in [(ticker, "ticker"), ("SPY", "spy"), ("QQQ", "qqq")]:
                try:
                    hist = yf.Ticker(sym).history(period="5d")
                    if len(hist) >= 2:
                        prev = float(hist["Close"].iloc[-2])
                        cur = float(hist["Close"].iloc[-1])
                        result[key]["1d"] = round(((cur - prev) / prev) * 100, 2)
                except:
                    result[key]["1d"] = None
            if sector_etf:
                try:
                    hist = yf.Ticker(sector_etf).history(period="5d")
                    if len(hist) >= 2:
                        prev = float(hist["Close"].iloc[-2])
                        cur = float(hist["Close"].iloc[-1])
                        result["sector_etf_perf"]["1d"] = round(((cur - prev) / prev) * 100, 2)
                except:
                    result["sector_etf_perf"]["1d"] = None
        else:
            for sym, key in [(ticker, "ticker"), ("SPY", "spy"), ("QQQ", "qqq")]:
                pct = _pct_change(sym, period)
                result[key][period_label] = round(pct, 2) if pct is not None else None
            if sector_etf:
                pct = _pct_change(sector_etf, period)
                result["sector_etf_perf"][period_label] = round(pct, 2) if pct is not None else None

    return result

def sector_summary_text(ticker):
    """Returns a short summary suitable for the analysis prompt."""
    ctx = get_sector_context(ticker)
    sector = ctx.get("sector") or "unknown"
    etf = ctx.get("sector_etf") or "—"
    
    def fmt(d):
        return ", ".join(f"{k}: {v:+.2f}%" if v is not None else f"{k}: n/a" for k, v in d.items())

    lines = [
        f"Sector: {sector} (ETF: {etf})",
        f"{ticker}: {fmt(ctx['ticker'])}",
        f"SPY: {fmt(ctx['spy'])}",
        f"QQQ: {fmt(ctx['qqq'])}",
    ]
    if etf != "—":
        lines.append(f"{etf}: {fmt(ctx['sector_etf_perf'])}")

    # Compute relative performance for the prompt
    rel_lines = []
    for period in ["1d", "5d", "1mo"]:
        t = ctx["ticker"].get(period)
        s = ctx["spy"].get(period)
        if t is not None and s is not None:
            diff = t - s
            direction = "outperforming" if diff > 0 else "underperforming"
            rel_lines.append(f"{period}: {direction} SPY by {abs(diff):.2f}pp")

    if rel_lines:
        lines.append("Relative performance vs SPY: " + " | ".join(rel_lines))

    return "\n".join(lines)