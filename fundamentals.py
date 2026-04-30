"""
Fundamentals from yfinance, formatted to match TradingAgents output.

Replaces:
    route_to_vendor("get_fundamentals", ticker)
"""
import yfinance as yf
from datetime import datetime


# Field order matched to TradingAgents output for prompt continuity
FUNDAMENTAL_FIELDS = [
    ("longName", "Name"),
    ("sector", "Sector"),
    ("industry", "Industry"),
    ("marketCap", "Market Cap"),
    ("trailingPE", "PE Ratio (TTM)"),
    ("forwardPE", "Forward PE"),
    ("trailingPegRatio", "PEG Ratio"),
    ("priceToBook", "Price to Book"),
    ("trailingEps", "EPS (TTM)"),
    ("forwardEps", "Forward EPS"),
    ("dividendYield", "Dividend Yield"),
    ("beta", "Beta"),
    ("fiftyTwoWeekHigh", "52 Week High"),
    ("fiftyTwoWeekLow", "52 Week Low"),
    ("fiftyDayAverage", "50 Day Average"),
    ("twoHundredDayAverage", "200 Day Average"),
    ("totalRevenue", "Revenue (TTM)"),
    ("grossProfits", "Gross Profit"),
    ("ebitda", "EBITDA"),
    ("netIncomeToCommon", "Net Income"),
    ("profitMargins", "Profit Margin"),
    ("operatingMargins", "Operating Margin"),
    ("returnOnEquity", "Return on Equity"),
    ("returnOnAssets", "Return on Assets"),
    ("debtToEquity", "Debt to Equity"),
    ("currentRatio", "Current Ratio"),
    ("bookValue", "Book Value"),
    ("freeCashflow", "Free Cash Flow"),
]


def get_fundamentals_text(ticker):
    """Returns formatted fundamentals text matching TradingAgents output."""
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        return f"Fundamentals unavailable: {e}"

    if not info:
        return f"No fundamentals data available for {ticker}."

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Company Fundamentals for {ticker}",
        f"# Data retrieved on: {now}",
        "",
    ]
    for field, label in FUNDAMENTAL_FIELDS:
        value = info.get(field)
        if value is None or value == "":
            continue
        lines.append(f"{label}: {value}")

    return "\n".join(lines)