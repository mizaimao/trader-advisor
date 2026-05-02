"""
Sector + industry performance context using yfinance.

The comparison ETF is chosen dynamically per ticker based on its sector and
industry. Industry-level ETFs (e.g. SOXX for semiconductors) take precedence
over sector ETFs (XLK for tech) when available — they're the more specific
benchmark. Sector ETF stays as the broader rotation context. Both surface
in the output so the agent can read both signals at once.

Caching / performance:
- yfinance `.info` is hit twice per ticker (sector + industry); cached
  process-locally to avoid the duplicate cost.
- Price history for 4-5 symbols (ticker + SPY + sector/industry ETFs + QQQ
  for Tech) fetched in 2 bulk yf.download() calls instead of 8-10 sequential
  history() calls. Same pattern as peers.py.
"""
import yfinance as yf

from yf_bulk import bulk_history, perf_from_bulk


# yfinance sector → broad sector ETF
SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}


# yfinance industry → industry-specific ETF (only mapped where a clean
# ETF exists; uncommon industries fall through to sector ETF only).
INDUSTRY_TO_ETF = {
    "Semiconductors": "SOXX",
    "Software - Application": "IGV",
    "Software - Infrastructure": "IGV",
    "Banks - Regional": "KRE",
    "Banks - Diversified": "KBE",
    "Biotechnology": "XBI",
    "Drug Manufacturers - General": "XLV",
    "Oil & Gas E&P": "XOP",
    "Oil & Gas Integrated": "XLE",
    "Homebuilding": "ITB",
    "Retail - Apparel & Luxury Goods": "XRT",
    "Steel": "XME",
    "Aerospace & Defense": "ITA",
    "Airlines": "JETS",
}


# Process-local cache for yf.Ticker(t).info. The .info call is the slow part
# of yfinance (1-3s) and we now read both `sector` and `industry` from it.
# Caching here avoids the second lookup hitting the network.
_info_cache: dict[str, dict] = {}


def _get_info(ticker: str) -> dict:
    """Cached yfinance Ticker(ticker).info — returns {} on failure."""
    if ticker in _info_cache:
        return _info_cache[ticker]
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    _info_cache[ticker] = info
    return info


def _resolve_etfs(ticker: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve (sector, sector_etf, industry, industry_etf) for a ticker.

    Returns Nones for any field that can't be resolved — the caller decides
    how to fall back (e.g. SPY-only comparison when no sector ETF found).
    """
    info = _get_info(ticker)
    sector = info.get("sector") or None
    industry = info.get("industry") or None
    sector_etf = SECTOR_TO_ETF.get(sector) if sector else None
    industry_etf = INDUSTRY_TO_ETF.get(industry) if industry else None
    return sector, sector_etf, industry, industry_etf


def _all_perfs(symbols: list[str]) -> dict[str, dict[str, float | None]]:
    """Fetch 1d/5d/1mo % changes for all symbols in two bulk calls.

    1d and 5d are derived from the 5d-window fetch (last-two close for 1d,
    first-vs-last close for 5d). 1mo needs its own fetch. Net: 2 HTTP calls
    regardless of symbol count. Primitives live in yf_bulk.
    """
    if not symbols:
        return {}
    prices_5d = bulk_history(symbols, "5d")
    prices_1mo = bulk_history(symbols, "1mo")
    return {
        sym: {
            "1d": perf_from_bulk(prices_5d, sym, mode="last_two"),
            "5d": perf_from_bulk(prices_5d, sym, mode="first_last"),
            "1mo": perf_from_bulk(prices_1mo, sym, mode="first_last"),
        }
        for sym in symbols
    }


tool_sector_summary_text: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "sector_summary_text",
        "description": (
            "Sector + industry performance context. The comparison ETFs are "
            "chosen DYNAMICALLY per ticker — JPM benchmarks against XLF "
            "(financial sector) and KBE (banks specifically); NVDA benchmarks "
            "against XLK (tech) and SOXX (semiconductors); PFE benchmarks "
            "against XLV (healthcare). The agent doesn't need to specify or "
            "guess the right ETF. Returns 1d/5d/1mo percent changes for the "
            "ticker, SPY, the sector ETF, the industry ETF (when distinct from "
            "the sector ETF), and QQQ for Technology names. Plus 1mo relative "
            "performance vs sector and industry ETFs on separate lines. Useful "
            "for distinguishing company-specific moves from sector/industry "
            "rotation: outperforming both the broad sector AND the specific "
            "industry signals genuine name-strength; underperforming a strong "
            "industry while the sector is up is a rotation yellow flag."
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


def sector_summary_text(ticker: str) -> str:
    """Multi-line sector + industry relative-performance summary.

    Args:
        ticker: Stock symbol (e.g. "NVDA").

    Returns:
        Multi-line string. Header lists the resolved sector and industry plus
        their ETFs (industry portion omitted if no industry ETF mapped or if
        it would duplicate the sector ETF). Performance lines follow for the
        ticker, SPY, sector ETF, industry ETF, and QQQ (Tech only). Final
        lines show 1mo relative performance vs the sector and industry ETFs
        separately. Falls back to SPY-only comparison when no sector mapping
        exists. Never raises; failed fetches surface as "n/a" inline.
    """
    sector, sector_etf, industry, industry_etf = _resolve_etfs(ticker)

    # Dedupe — if industry ETF is the same as sector ETF (e.g. PFE: XLV+XLV),
    # treat as no industry ETF. The redundant row would just confuse the agent.
    if industry_etf == sector_etf:
        industry_etf = None
        industry = None  # so the header doesn't claim a redundant industry mapping

    # Header
    if sector_etf and industry_etf:
        header = (
            f"Sector: {sector} (ETF: {sector_etf}) | "
            f"Industry: {industry} (ETF: {industry_etf})"
        )
    elif sector_etf:
        header = f"Sector: {sector} (ETF: {sector_etf})"
    else:
        header = f"Sector: {sector or 'unknown'} (no matching ETF — SPY-only comparison)"

    # Build the symbol list upfront, then bulk-fetch all perfs in one shot.
    symbols = [ticker, "SPY"]
    if sector == "Technology":
        symbols.append("QQQ")
    if sector_etf:
        symbols.append(sector_etf)
    if industry_etf:
        symbols.append(industry_etf)

    perfs = _all_perfs(symbols)
    ticker_perf = perfs.get(ticker, {})

    perf_lines = [
        f"{ticker}: {_fmt_perf(perfs.get(ticker, {}))}",
        f"SPY: {_fmt_perf(perfs.get('SPY', {}))}",
    ]
    if sector == "Technology":
        perf_lines.append(f"QQQ: {_fmt_perf(perfs.get('QQQ', {}))}")

    sector_etf_perf = perfs.get(sector_etf) if sector_etf else None
    if sector_etf:
        perf_lines.append(f"{sector_etf}: {_fmt_perf(sector_etf_perf or {})}")

    industry_etf_perf = perfs.get(industry_etf) if industry_etf else None
    if industry_etf:
        perf_lines.append(f"{industry_etf}: {_fmt_perf(industry_etf_perf or {})}")

    # Relative perf lines — 1mo only per spec example. The absolute perf lines
    # above carry 1d/5d/1mo so the agent can derive other gaps if needed.
    rel_lines = []
    t_1mo = ticker_perf.get("1mo")
    if sector_etf_perf and t_1mo is not None:
        s_1mo = sector_etf_perf.get("1mo")
        if s_1mo is not None:
            gap = t_1mo - s_1mo
            rel_lines.append(f"Relative vs {sector_etf}: {gap:+.2f}pp 1mo")
    if industry_etf_perf and t_1mo is not None:
        i_1mo = industry_etf_perf.get("1mo")
        if i_1mo is not None:
            gap = t_1mo - i_1mo
            rel_lines.append(f"Relative vs {industry_etf}: {gap:+.2f}pp 1mo")

    return "\n".join([header] + perf_lines + rel_lines)


def _fmt_perf(perf: dict[str, float | None]) -> str:
    """Format a perf dict {1d, 5d, 1mo} as 'k: +1.20%, …'."""
    return ", ".join(
        f"{k}: {v:+.2f}%" if v is not None else f"{k}: n/a"
        for k, v in perf.items()
    )