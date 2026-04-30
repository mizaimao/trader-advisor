"""
Social sentiment from StockTwits public API.

No API key required. Public stream endpoint returns latest 30 messages
for a ticker, with self-tagged bullish/bearish sentiment.

Rate limit: ~200 req/hour without auth. With our caching that's plenty.
"""
import requests
from datetime import datetime, timezone


STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"


def get_stocktwits(ticker, limit=30):
    """Fetch latest messages for a ticker from StockTwits."""
    try:
        url = STOCKTWITS_URL.format(ticker=ticker.upper())
        r = requests.get(url, timeout=10, headers={"User-Agent": "trader-advisor/1.0"})
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        data = r.json()
        messages = data.get("messages", [])[:limit]
        return {"messages": messages, "error": None}
    except Exception as e:
        return {"error": str(e), "messages": []}


def stocktwits_summary(ticker):
    """Returns aggregated sentiment + a few example messages.
    
    Shape:
      {
        "total": 30,
        "bullish": 18,
        "bearish": 4,
        "untagged": 8,
        "bullish_pct": 60.0,
        "bearish_pct": 13.3,
        "sample_messages": [{...}, {...}, {...}],  # 3 most recent
        "error": None,
      }
    """
    result = get_stocktwits(ticker, limit=30)
    if result.get("error"):
        return {"error": result["error"]}

    messages = result["messages"]
    if not messages:
        return {"error": "no messages found"}

    bullish = bearish = untagged = 0
    for m in messages:
        sentiment = (m.get("entities") or {}).get("sentiment")
        if sentiment:
            basic = sentiment.get("basic", "").lower()
            if basic == "bullish":
                bullish += 1
            elif basic == "bearish":
                bearish += 1
            else:
                untagged += 1
        else:
            untagged += 1

    total = len(messages)
    sample = []
    for m in messages[:3]:
        body = (m.get("body") or "")[:200]
        ts = m.get("created_at", "")
        username = (m.get("user") or {}).get("username", "?")
        sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic", "—")
        sample.append({
            "user": username,
            "time": ts,
            "sentiment": sent,
            "body": body,
        })

    return {
        "total": total,
        "bullish": bullish,
        "bearish": bearish,
        "untagged": untagged,
        "bullish_pct": round(bullish / total * 100, 1) if total else 0,
        "bearish_pct": round(bearish / total * 100, 1) if total else 0,
        "sample_messages": sample,
        "error": None,
    }


def stocktwits_summary_text(ticker):
    """Returns a short text summary for the prompt context block."""
    s = stocktwits_summary(ticker)
    if s.get("error"):
        return None

    total = s["total"]
    bull = s["bullish_pct"]
    bear = s["bearish_pct"]
    tagged = s["bullish"] + s["bearish"]

    if tagged == 0:
        sentiment_label = "no tagged sentiment"
    elif bull > bear * 2:
        sentiment_label = "strongly bullish"
    elif bull > bear:
        sentiment_label = "leaning bullish"
    elif bear > bull * 2:
        sentiment_label = "strongly bearish"
    elif bear > bull:
        sentiment_label = "leaning bearish"
    else:
        sentiment_label = "mixed"

    return (
        f"StockTwits (last {total} messages): {bull}% bullish, {bear}% bearish "
        f"({tagged}/{total} tagged) — {sentiment_label}"
    )

"""
Reddit sentiment via ApeWisdom (free, no auth required).

ApeWisdom aggregates ticker mentions across stock-related subreddits
(wallstreetbets, stocks, investing, etc.) and exposes the top trending
tickers via a public REST API. Only the top ~100 trending tickers are
included; if your ticker isn't there, that itself is signal — no chatter.
"""

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"


def get_apewisdom(filter_name="all-stocks", pages=2):
    """Fetch trending tickers from ApeWisdom across multiple pages.
    
    Returns a dict keyed by ticker symbol with mention/sentiment data.
    """
    results = {}
    for page in range(1, pages + 1):
        try:
            url = APEWISDOM_URL.format(filter=filter_name, page=page)
            r = requests.get(url, timeout=10, headers={"User-Agent": "trader-advisor/1.0"})
            if r.status_code != 200:
                break
            data = r.json()
            for entry in data.get("results", []):
                ticker = entry.get("ticker", "").upper()
                if ticker:
                    results[ticker] = entry
            if len(data.get("results", [])) < 50:
                break  # last page
        except Exception:
            break
    return results


# In-process cache for the bulk fetch — refreshed every ~15 min
_apewisdom_cache = {"data": None, "fetched_at": None}


def reddit_summary(ticker, max_age_minutes=15):
    """Return Reddit mentions + sentiment for a ticker, or None if not trending."""
    from datetime import datetime, timedelta

    now = datetime.now()
    cached = _apewisdom_cache.get("data")
    fetched = _apewisdom_cache.get("fetched_at")

    if not cached or not fetched or now - fetched > timedelta(minutes=max_age_minutes):
        cached = get_apewisdom("all-stocks", pages=2)
        _apewisdom_cache["data"] = cached
        _apewisdom_cache["fetched_at"] = now

    entry = cached.get(ticker.upper())
    if not entry:
        return {"trending": False, "ticker": ticker.upper()}

    mentions = int(entry.get("mentions", 0))
    mentions_prev = int(entry.get("mentions_24h_ago", 0))
    delta_pct = None
    if mentions_prev > 0:
        delta_pct = round((mentions - mentions_prev) / mentions_prev * 100, 1)

    return {
        "trending": True,
        "ticker": ticker.upper(),
        "rank": int(entry.get("rank", 0)),
        "mentions_24h": mentions,
        "mentions_prev_24h": mentions_prev,
        "delta_pct": delta_pct,
        "upvotes": int(entry.get("upvotes", 0)),
        "sentiment_score": entry.get("sentiment_score"),  # 0-100, may be None
    }


def reddit_summary_text(ticker):
    """Short prompt-friendly summary."""
    s = reddit_summary(ticker)
    if not s.get("trending"):
        return f"{ticker} is not in the top ~100 trending tickers on Reddit (low chatter)."

    lines = [
        f"Reddit (last 24h): {s['mentions_24h']} mentions, "
        f"rank #{s['rank']} of trending tickers."
    ]
    if s.get("delta_pct") is not None:
        direction = "up" if s["delta_pct"] > 0 else "down"
        lines.append(f"Mentions {direction} {abs(s['delta_pct'])}% vs prior 24h.")

    score = s.get("sentiment_score")
    if score is not None:
        if score >= 70:
            label = "strongly bullish"
        elif score >= 55:
            label = "leaning bullish"
        elif score <= 30:
            label = "strongly bearish"
        elif score <= 45:
            label = "leaning bearish"
        else:
            label = "neutral/mixed"
        lines.append(f"Sentiment score: {score}/100 ({label}).")

    return " ".join(lines)