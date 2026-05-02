"""
Cross-ticker peer comparison — agent-facing tool.

Given a primary ticker and 1-5 peer tickers, returns side-by-side performance
and valuation metrics. The agent picks the peers itself (this is its uniquely-
agentic affordance — workflow modes can't do this because they don't know
which peers matter for THIS ticker until they've already seen its sector,
industry, and market cap).

Output formats:
- "json" (default) — structured data with mean/median summary stats
- "markdown" — human-readable tables

Performance:
- Prices fetched via yf.download() in bulk — 3 HTTP calls total (5d, 1mo, 1y)
  regardless of peer count, instead of N×3 sequential history() calls.
- yf.Ticker(t).info has no bulk endpoint; fetched concurrently via a thread
  pool (network-bound, parallelizes well).
- End-to-end latency: ~5-8s for 5 peers (was ~15-30s with the sequential
  approach in the previous draft).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
import yfinance as yf


# ── Tool schema ──────────────────────────────────────────────────────────────
tool_peer_comparison: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "peer_comparison",
        "description": (
            "Compare a ticker against 1-5 peer tickers you choose. Returns "
            "side-by-side performance (1d/5d/1mo/1y % change) and valuation "
            "(PE, forward PE, profit margin, operating margin, market cap) "
            "for the primary and each peer, plus a summary with peer mean and "
            "median for the most decision-relevant metrics (1mo perf, forward "
            "PE, market cap). Useful for validating a strength claim ('does "
            "this name actually outperform its comps?') or spotting a value "
            "trap ('low PE — but margins are worse than peers'). Pick peers "
            "based on sector/industry already revealed by "
            "`get_fundamentals_text` — don't guess. Note: this tool is "
            "moderately slow (~5-8s for 5 peers) so reach for it deliberately, "
            "after you have a thesis to test."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Primary stock symbol, e.g. 'NVDA'.",
                },
                "peer_tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "1-5 peer ticker symbols. Choose meaningful peers "
                        "based on what you already know — same sector and "
                        "similar market cap usually matter most. Don't include "
                        "the primary ticker."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                    "description": (
                        "Output format. 'json' (default) for structured data "
                        "with mean/median summary stats — easier to parse "
                        "reliably across models. 'markdown' for human-readable "
                        "tables — useful when the trace will be read by a "
                        "person."
                    ),
                },
            },
            "required": ["ticker", "peer_tickers"],
        },
    },
}


# ── Public function ──────────────────────────────────────────────────────────
def peer_comparison(
    ticker: str,
    peer_tickers: list[str],
    format: str = "json",
) -> str:
    """Compare a primary ticker against peers. See module docstring."""
    if not peer_tickers:
        return _empty_response(format, f"No peers provided to compare against {ticker}.")

    # Dedupe + exclude the primary from peers (in case the agent included it)
    main = ticker.upper()
    seen: set[str] = {main}
    cleaned_peers: list[str] = []
    for p in peer_tickers:
        p_upper = p.upper()
        if p_upper not in seen:
            seen.add(p_upper)
            cleaned_peers.append(p_upper)
    if not cleaned_peers:
        return _empty_response(
            format, f"No valid peers after deduplication. Provide peers different from {main}."
        )

    # Cap at 5 (the schema's maxItems is advisory; defend at runtime too)
    cleaned_peers = cleaned_peers[:5]

    all_tickers = [main] + cleaned_peers
    metrics_by_ticker = _fetch_all_metrics(all_tickers)
    main_m = metrics_by_ticker[main]
    peer_ms = [metrics_by_ticker[p] for p in cleaned_peers]
    summary = _compute_summary(main_m, peer_ms)

    if format == "markdown":
        return _format_markdown(main_m, peer_ms, summary)
    return _format_json(main_m, peer_ms, summary)


# ── Bulk fetchers ────────────────────────────────────────────────────────────
def _fetch_all_metrics(tickers: list[str]) -> dict[str, dict]:
    """Fetch perf + valuation metrics for all tickers in bulk.

    Three bulk yf.download() calls cover all price periods; .info calls are
    parallelized via a thread pool. Failures at any field reduce to None
    rather than raising — same per-field robustness as the sequential version.
    """
    # Bulk price downloads — one HTTP call per period, all tickers at once
    prices_5d = _bulk_history(tickers, period="5d")
    prices_1mo = _bulk_history(tickers, period="1mo")
    prices_1y = _bulk_history(tickers, period="1y")

    # Concurrent .info — yfinance has no bulk endpoint for this
    infos = _concurrent_infos(tickers)

    return {
        t: _assemble_metrics(t, prices_5d, prices_1mo, prices_1y, infos.get(t, {}))
        for t in tickers
    }


def _bulk_history(tickers: list[str], period: str):
    """yf.download wrapper. Returns DataFrame or None on bulk failure.

    Returns shape: when len(tickers) > 1, MultiIndex columns (ticker, field).
    When len(tickers) == 1 (shouldn't happen here — agent always has main +
    at least 1 peer — but defended anyway), flat columns.
    """
    try:
        return yf.download(
            tickers,
            period=period,
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=False,  # we own concurrency above; don't double-thread
        )
    except Exception:
        return None


def _concurrent_infos(tickers: list[str]) -> dict[str, dict]:
    """Fetch yf.Ticker(t).info for each ticker concurrently."""
    def _fetch_one(t):
        try:
            return yf.Ticker(t).info or {}
        except Exception:
            return {}

    max_workers = min(len(tickers), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_fetch_one, tickers))
    return dict(zip(tickers, results))


def _assemble_metrics(
    ticker: str,
    prices_5d,
    prices_1mo,
    prices_1y,
    info: dict,
) -> dict:
    """Stitch bulk fetch results into a single ticker's metrics dict."""
    return {
        "ticker": ticker,
        "perf_1d": _perf_from_bulk(prices_5d, ticker, mode="last_two"),
        "perf_5d": _perf_from_bulk(prices_5d, ticker, mode="first_last"),
        "perf_1mo": _perf_from_bulk(prices_1mo, ticker, mode="first_last"),
        "perf_1y": _perf_from_bulk(prices_1y, ticker, mode="first_last"),
        "pe": info.get("trailingPE"),
        "fwd_pe": info.get("forwardPE"),
        "profit_margin": info.get("profitMargins"),
        "operating_margin": info.get("operatingMargins"),
        "market_cap": info.get("marketCap"),
    }


def _perf_from_bulk(df, ticker: str, *, mode: str) -> float | None:
    """Extract % change from a bulk-downloaded DataFrame for one ticker.

    `mode='last_two'` uses last two closes (1d perf within a 5d window).
    `mode='first_last'` uses first vs last close (whole-period change).
    """
    if df is None or len(df) == 0:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            level0 = df.columns.get_level_values(0)
            if ticker not in level0:
                return None
            closes = df[ticker]["Close"].dropna()
        else:
            # Single-ticker fallback (yfinance returns flat columns then)
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


# ── Summary stats ────────────────────────────────────────────────────────────
# Metrics we surface in the summary block. Per-peer values live in the peer
# rows / peer array — summary only carries the cross-peer aggregates.
_SUMMARY_METRICS: tuple[str, ...] = ("perf_1mo", "fwd_pe", "market_cap")


def _compute_summary(main: dict, peers: list[dict]) -> dict:
    """Peer mean + median + primary's gap, for each summary metric."""
    summary: dict[str, Any] = {}
    for metric in _SUMMARY_METRICS:
        peer_vals = [p[metric] for p in peers if p.get(metric) is not None]
        if not peer_vals:
            continue
        peer_mean = sum(peer_vals) / len(peer_vals)
        sorted_vals = sorted(peer_vals)
        n = len(sorted_vals)
        peer_median = (
            (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
            if n % 2 == 0
            else sorted_vals[n // 2]
        )
        primary_val = main.get(metric)
        summary[metric] = {
            "primary": primary_val,
            "peer_mean": peer_mean,
            "peer_median": peer_median,
            "vs_mean": (primary_val - peer_mean) if primary_val is not None else None,
            "vs_median": (primary_val - peer_median) if primary_val is not None else None,
        }
    return summary


# ── Empty / error response ───────────────────────────────────────────────────
def _empty_response(format: str, message: str) -> str:
    if format == "markdown":
        return message
    return json.dumps({"error": message})


# ── JSON output ──────────────────────────────────────────────────────────────
def _format_json(main: dict, peers: list[dict], summary: dict) -> str:
    payload = {
        "primary": _shape_ticker_for_json(main),
        "peers": [_shape_ticker_for_json(p) for p in peers],
        "summary": summary,
    }
    return json.dumps(payload, default=str)


def _shape_ticker_for_json(m: dict) -> dict:
    return {
        "ticker": m["ticker"],
        "perf": {
            "1d": m["perf_1d"],
            "5d": m["perf_5d"],
            "1mo": m["perf_1mo"],
            "1y": m["perf_1y"],
        },
        "valuation": {
            "pe": m["pe"],
            "fwd_pe": m["fwd_pe"],
            "profit_margin": m["profit_margin"],
            "operating_margin": m["operating_margin"],
            "market_cap": m["market_cap"],
        },
    }


# ── Markdown output ──────────────────────────────────────────────────────────
def _format_markdown(main: dict, peers: list[dict], summary: dict) -> str:
    peer_list = ", ".join(p["ticker"] for p in peers)
    lines = [f"### {main['ticker']} vs {len(peers)} peer(s): {peer_list}"]

    lines.append("\n**Performance** (% change)")
    lines.append("| Ticker | 1d | 5d | 1mo | 1y |")
    lines.append("|---|---|---|---|---|")
    lines.append(_perf_row(main))
    for p in peers:
        lines.append(_perf_row(p))

    lines.append("\n**Valuation & Margins**")
    lines.append("| Ticker | PE (TTM) | Fwd PE | Profit Margin | Op Margin | Mkt Cap |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(_val_row(main))
    for p in peers:
        lines.append(_val_row(p))

    if summary:
        lines.append("\n**Summary** — primary vs peer mean / median")
        lines.append("| Metric | Primary | Peer mean | Peer median | vs mean | vs median |")
        lines.append("|---|---|---|---|---|---|")
        for metric in _SUMMARY_METRICS:
            s = summary.get(metric)
            if s is None:
                continue
            lines.append(_summary_row(metric, s))

    return "\n".join(lines)


def _perf_row(m: dict) -> str:
    return (
        f"| {m['ticker']} "
        f"| {_fmt_pct(m['perf_1d'])} "
        f"| {_fmt_pct(m['perf_5d'])} "
        f"| {_fmt_pct(m['perf_1mo'])} "
        f"| {_fmt_pct(m['perf_1y'])} |"
    )


def _val_row(m: dict) -> str:
    return (
        f"| {m['ticker']} "
        f"| {_fmt_pe(m['pe'])} "
        f"| {_fmt_pe(m['fwd_pe'])} "
        f"| {_fmt_margin(m['profit_margin'])} "
        f"| {_fmt_margin(m['operating_margin'])} "
        f"| {_fmt_mcap(m['market_cap'])} |"
    )


_METRIC_LABEL = {
    "perf_1mo": "1mo perf",
    "fwd_pe": "Fwd PE",
    "market_cap": "Market cap",
}


def _summary_row(metric: str, s: dict) -> str:
    """Per-metric summary row with appropriate formatters."""
    if metric == "perf_1mo":
        fmt = _fmt_pct
        delta_suffix = "pp"  # percentage-points
    elif metric == "fwd_pe":
        fmt = _fmt_pe
        delta_suffix = ""
    elif metric == "market_cap":
        fmt = _fmt_mcap
        delta_suffix = ""
    else:
        fmt = lambda v: f"{v}" if v is not None else "n/a"  # noqa: E731
        delta_suffix = ""

    def _delta(v):
        if v is None:
            return "n/a"
        sign = "+" if v >= 0 else ""
        if metric == "perf_1mo":
            return f"{sign}{v:.2f}{delta_suffix}"
        if metric == "fwd_pe":
            return f"{sign}{v:.2f}"
        if metric == "market_cap":
            return _fmt_mcap_signed(v)
        return f"{sign}{v}"

    return (
        f"| {_METRIC_LABEL.get(metric, metric)} "
        f"| {fmt(s['primary'])} "
        f"| {fmt(s['peer_mean'])} "
        f"| {fmt(s['peer_median'])} "
        f"| {_delta(s['vs_mean'])} "
        f"| {_delta(s['vs_median'])} |"
    )


# ── Formatters ───────────────────────────────────────────────────────────────
def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "n/a"


def _fmt_pe(v) -> str:
    return f"{v:.1f}" if v is not None else "n/a"


def _fmt_margin(v) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def _fmt_mcap(v) -> str:
    if v is None:
        return "n/a"
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:.0f}"


def _fmt_mcap_signed(v) -> str:
    """Signed market-cap delta — keeps sign visible for +/- gaps."""
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else "-"
    return f"{sign}{_fmt_mcap(abs(v))}"