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


tool_get_fundamentals_text: dict[str, str] = {
    "type": "function",
    "function": {
        "name": "get_fundamentals_text",
        "description": (
            "Company fundamentals — name, sector, market cap, valuation ratios (PE, forward "
            "PE, PEG, P/B), margins (profit, operating), EPS and free cash flow, debt-to-equity, "
            "52-week range, and 50/200-day averages. For a SHORT-TERM trader this is risk "
            "context, not the primary driver — useful for sanity-checking whether a technical "
            "thesis is backed by underlying business quality (is a high PE justified by growth?), "
            "spotting potential value traps (low PE + collapsing margins), or sizing position "
            "risk before earnings."
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


def get_fundamentals_text(ticker):
    """Company fundamentals text for prompt context. Matches TradingAgent output.

    Args:
        ticker: Stock symbol (e.g. "NVDA").

    Returns:
        Multi-line string listing company info and key financial metrics
        (valuation, margins, profitability, balance-sheet ratios, 52-week
        range). Field order matches TradingAgents output for prompt continuity.
        Returns an "unavailable" / "no data" string on yfinance failure rather
        than raising.
    """
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