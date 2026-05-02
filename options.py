"""
Options data fetcher with vendor-agnostic interface.

To switch vendors later (e.g. Polygon.io), implement a new backend function
matching the same return shape from get_options_summary().
"""
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

VENDOR = os.getenv("OPTIONS_VENDOR", "yfinance")  # "yfinance" or "polygon"


def get_options_summary(ticker):
    """Returns vendor-agnostic options summary.
    
    Returns dict:
      {
        "put_call_ratio": float | None,    # volume-based
        "iv_rank": float | None,           # 0-100, higher = vol expensive
        "atm_iv": float | None,            # at-the-money IV for nearest expiry
        "near_expiry": str | None,         # YYYY-MM-DD
        "unusual_volume": bool,            # spike vs avg
        "total_call_volume": int,
        "total_put_volume": int,
        "error": str | None,
      }
    """
    if VENDOR == "yfinance":
        return _yfinance_summary(ticker)
    # Future: elif VENDOR == "polygon": return _polygon_summary(ticker)
    return {"error": f"Unknown vendor: {VENDOR}"}


def _yfinance_summary(ticker):
    import yfinance as yf
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            return {"error": "No options chain available"}

        near_expiry = expirations[0]
        chain = tk.option_chain(near_expiry)
        calls, puts = chain.calls, chain.puts

        total_call_vol = int(calls["volume"].fillna(0).sum())
        total_put_vol = int(puts["volume"].fillna(0).sum())
        pc_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else None

        # Get current stock price
        hist = tk.history(period="5d")
        if hist.empty:
            return {"error": "No price data for ATM lookup"}
        spot = float(hist["Close"].iloc[-1])

        # ATM IV: find option closest to spot in nearest expiry
        atm_iv = None
        try:
            calls_with_iv = calls[calls["impliedVolatility"] > 0].copy()
            if not calls_with_iv.empty:
                calls_with_iv["dist"] = (calls_with_iv["strike"] - spot).abs()
                atm_iv = float(calls_with_iv.sort_values("dist").iloc[0]["impliedVolatility"])
        except Exception:
            pass

        # IV rank: not directly available from yfinance; would need historical IV.
        # Skipping for now (will add if we move to Polygon).
        iv_rank = None

        # Unusual volume heuristic: total vol > 2x open interest
        total_oi = int(calls["openInterest"].fillna(0).sum() + puts["openInterest"].fillna(0).sum())
        total_vol = total_call_vol + total_put_vol
        unusual = (total_vol > 2 * total_oi) if total_oi > 0 else False

        return {
            "put_call_ratio": round(pc_ratio, 2) if pc_ratio is not None else None,
            "iv_rank": iv_rank,
            "atm_iv": round(atm_iv, 3) if atm_iv else None,
            "near_expiry": near_expiry,
            "unusual_volume": unusual,
            "total_call_volume": total_call_vol,
            "total_put_volume": total_put_vol,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e)}


tool_options_summary_text: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "options_summary_text",
        "description": (
            "Options activity snapshot — put/call volume ratio (with bullish/bearish/neutral "
            "label), at-the-money implied volatility, an unusual-volume flag, and the nearest "
            "expiry date. Useful for checking smart-money hedging near recent highs (high P/C "
            "+ price near 5y high = caution), gauging expected near-term volatility ahead of "
            "earnings (elevated ATM IV), or investigating unusual volume as a catalyst signal. "
            "Skip for small caps or recent IPOs that lack liquid options."
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


def options_summary_text(ticker):
    """One-line options summary text for prompt context.

    Args:
        ticker: Stock symbol (e.g. "NVDA").

    Returns:
        Pipe-separated string with present fields, e.g.
        "P/C ratio: 0.85 (bullish-leaning) | ATM IV: 38.2% | near-expiry: 2026-05-16".
        Returns None when the chain is unavailable, the ticker has no options,
        or every field would be empty. Never raises.
    """
    data = get_options_summary(ticker)
    if data.get("error"):
        return None
    parts = []
    pc = data.get("put_call_ratio")
    if pc is not None:
        sentiment = "bearish-leaning" if pc > 1.0 else "bullish-leaning" if pc < 0.7 else "neutral"
        parts.append(f"P/C ratio: {pc} ({sentiment})")
    iv = data.get("atm_iv")
    if iv:
        parts.append(f"ATM IV: {iv*100:.1f}%")
    if data.get("unusual_volume"):
        parts.append("⚠️ unusual options volume")
    expiry = data.get("near_expiry")
    if expiry:
        parts.append(f"near-expiry: {expiry}")
    return " | ".join(parts) if parts else None
