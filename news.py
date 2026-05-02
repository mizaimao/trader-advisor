import finnhub
import os
import requests
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))




tool_get_news_finnhub: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "get_news_finnhub",
        "description": (
            "Recent company news headlines and summaries from Finnhub for a date range. "
            "Returns up to 10 articles (headline, source, date, summary, link) as formatted markdown. "
            "Useful for investigating the catalyst behind a price move, checking for breaking "
            "news ahead of a decision, or gauging coverage volume around an earnings event. "
            "Older articles (>7 days) carry less weight for short-term decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock symbol, e.g. 'NVDA'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start of news window in YYYY-MM-DD format. Typically 7-14 days before today_str for short-term context.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of news window in YYYY-MM-DD format. Usually today_str.",
                },
            },
            "required": ["ticker", "start_date", "end_date"],
        },
    },
}


def get_news_finnhub(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch up to 10 recent company news articles from Finnhub.

    Args:
        ticker: Stock symbol (e.g. "NVDA").
        start_date: Start of news window in YYYY-MM-DD format.
        end_date: End of news window in YYYY-MM-DD format.

    Returns:
        Formatted markdown with up to 10 articles (headline, source, date,
        summary truncated to 300 chars, link). Returns an error/empty string
        on Finnhub failure rather than raising.
    """
    try:
        news = client.company_news(ticker, _from=start_date, to=end_date)
        if not news:
            return f"No news found for {ticker} between {start_date} and {end_date}"
        
        result = f"## {ticker} News ({start_date} to {end_date})\n\n"
        for article in news[:10]:
            dt = datetime.fromtimestamp(article["datetime"]).strftime("%Y-%m-%d")
            result += f"### {article['headline']} ({article['source']})\n"
            result += f"Date: {dt}\n"
            if article.get("summary"):
                result += f"{article['summary'][:300]}\n"
            result += f"Link: {article['url']}\n\n"
        return result
    except Exception as e:
        return f"Error fetching news: {str(e)}"


def get_earnings_calendar_finnhub(ticker, days_ahead=90):
    """Returns next earnings date for a ticker, or None if no upcoming earnings within window."""
    from datetime import datetime, timedelta
    today = datetime.today().strftime("%Y-%m-%d")
    end = (datetime.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    url = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={end}&symbol={ticker}&token={os.getenv('FINNHUB_API_KEY')}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if "earningsCalendar" in data and data["earningsCalendar"]:
            # Sort by date and pick the soonest
            events = sorted(data["earningsCalendar"], key=lambda x: x.get("date", ""))
            return events[0]
        return None
    except Exception as e:
        return None

tool_days_until_earnings: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "days_until_earnings",
        "description": (
            "Days remaining until the next scheduled earnings announcement. "
            "Returns an integer (0 = today, positive = future) or null if no earnings "
            "are scheduled within the next 90 days. Useful for gating short-term decisions "
            "(avoid strong BUY/SELL within 3 days of earnings due to event risk) and for "
            "explaining elevated implied volatility ahead of the event."
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


def days_until_earnings(ticker):
    """Days until the next scheduled earnings announcement.

    Args:
        ticker: Stock symbol (e.g. "NVDA").

    Returns:
        int days (0 = today, positive = future), or None if no earnings
        are scheduled within the next 90 days.
    """
    from datetime import datetime
    event = get_earnings_calendar_finnhub(ticker)
    if not event or not event.get("date"):
        return None
    try:
        earnings_date = datetime.strptime(event["date"], "%Y-%m-%d")
        delta = (earnings_date - datetime.today()).days
        return delta if delta >= 0 else None
    except:
        return None

tool_get_insider_transactions_finnhub: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "get_insider_transactions_finnhub",
        "description": (
            "Form-4 insider transactions (officers, directors, 10% holders) for a date range. "
            "Returns aggregated buy/sell counts, net dollar value, net shares, and the raw "
            "transaction list. Useful for spotting smart-money exits near recent highs, "
            "accumulation near lows, or validating a bull/bear thesis with insider behavior. "
            "Note: Form-4 filings carry a 2-5 day reporting lag and the latest transaction "
            "may still be weeks old — treat as background context, not a real-time signal. "
            "Weight transactions <14 days old more heavily for short-term decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock symbol, e.g. 'NVDA'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional start of window in YYYY-MM-DD. If omitted, derived from days_back.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end of window in YYYY-MM-DD. Defaults to today.",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Window size in days when start_date is not given (default 30). Common values: 30, 60, 90.",
                },
            },
            "required": ["ticker"],
        },
    },
}


def get_insider_transactions_finnhub(ticker, start_date=None, end_date=None, days_back=30):
    """Fetch insider transactions (Form 4 filings) from Finnhub.

    Args:
        ticker: Stock symbol (e.g. "NVDA").
        start_date: Start of window in YYYY-MM-DD. If None, computed as
            today - days_back.
        end_date: End of window in YYYY-MM-DD. Defaults to today.
        days_back: Used to derive start_date when not given (default 30).

    Returns:
        Dict with aggregated stats and raw transactions:
          {
            "net_shares": int,      # +ve = net buying, -ve = net selling
            "buy_count": int,
            "sell_count": int,
            "total_value": float,   # USD, signed (negative = net selling)
            "transactions": [...],  # raw list from Finnhub
          }
        On error, same shape with zeros plus an "error" key — never raises.
    """
    from datetime import datetime, timedelta
    if not end_date:
        end_date = datetime.today().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    url = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&from={start_date}&to={end_date}&token={os.getenv('FINNHUB_API_KEY')}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        transactions = data.get("data", [])

        net_shares = 0
        total_value = 0.0
        buy_count = 0
        sell_count = 0

        for tx in transactions:
            change = tx.get("change", 0) or 0
            price = tx.get("transactionPrice", 0) or 0
            net_shares += change
            total_value += change * price
            if change > 0:
                buy_count += 1
            elif change < 0:
                sell_count += 1

        return {
            "net_shares": net_shares,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_value": total_value,
            "transactions": transactions,
        }
    except Exception as e:
        return {"net_shares": 0, "buy_count": 0, "sell_count": 0, "total_value": 0, "transactions": [], "error": str(e)}

def insider_summary_text(ticker):
    for window in [30, 60, 90]:
        data = get_insider_transactions_finnhub(ticker, days_back=window)
        if data["transactions"]:
            net = data["total_value"]
            direction = "buying" if net > 0 else "selling" if net < 0 else "neutral"
            dates = [tx.get("transactionDate") for tx in data["transactions"] if tx.get("transactionDate")]
            latest = max(dates) if dates else "—"
            return f"Net insider {direction} (last {window}d): ${abs(net):,.0f} | {data['buy_count']} buys, {data['sell_count']} sells | latest: {latest}"
    return "No insider activity in last 90d"