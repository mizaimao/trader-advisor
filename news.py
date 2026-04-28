import finnhub
import os
import requests
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))

def get_news_finnhub(ticker: str, start_date: str, end_date: str) -> str:
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

def days_until_earnings(ticker):
    """Returns int days until next earnings, or None."""
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

def get_insider_transactions_finnhub(ticker, start_date=None, end_date=None, days_back=30):
    """Returns recent insider transactions from Finnhub.
    
    Returns a dict with summary stats and raw transactions:
      {
        "net_shares": int,        # positive = net buying, negative = net selling
        "buy_count": int,
        "sell_count": int,
        "total_value": float,     # in USD, signed (negative = net selling)
        "transactions": [...]     # raw list
      }
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