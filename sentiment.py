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
        r = requests.get(url, timeout=10, headers={"User-Agent": "moose-trader/1.0"})
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