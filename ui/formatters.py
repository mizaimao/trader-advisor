"""Pure formatting helpers — no Streamlit dependencies."""
import re
from datetime import datetime


def escape_dollars(text):
    """Replace $ with HTML entity so Streamlit doesn't render LaTeX math.
    Streamlit interprets $...$ as inline math; this breaks any text containing
    dollar amounts (e.g. '$180 million', '$10.00 level')."""
    if not text:
        return text
    return text.replace("$", "&#36;")


def abbrev_dollar(amount):
    """Format a number like 22249357 -> '$22M' or 1234 -> '$1K'."""
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return "?"
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.0f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"


def insider_label(summary):
    """Compact label: emoji + abbreviated $amount + (latest date)."""
    if not summary:
        return "—"
    m = re.search(r"\$([\d,]+)", summary)
    raw = m.group(1).replace(",", "") if m else "0"
    amt = abbrev_dollar(raw)

    date_match = re.search(r"latest:\s*(\d{4}-\d{2}-\d{2})", summary)
    date_str = ""
    if date_match:
        try:
            d = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            date_str = f" ({d.month}/{d.day})"
        except ValueError:
            date_str = ""

    if "buying" in summary:
        return f"🟢 {amt}{date_str}"
    if "selling" in summary:
        return f"🔴 {amt}{date_str}"
    return f"{amt}{date_str}"


def insider_color(summary):
    if not summary:
        return "color: #444444"
    if "buying" in summary:
        return "color: #00ff00"
    if "selling" in summary:
        return "color: #ff4444"
    return "color: #888"


def earnings_label(days):
    if days is None:
        return "—"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"{days}d"


def earnings_color(days):
    if days is None:
        return "color: #444444"
    if days <= 3:
        return "color: #ff4444; font-weight: 600"
    if days <= 7:
        return "color: #ffff00"
    return "color: #888"


def relative_time(date_str):
    if not date_str or str(date_str) in ("None", "nan", ""):
        return "—"
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        delta = datetime.today() - dt
        if delta.days == 0:
            return "today"
        if delta.days == 1:
            return "yesterday"
        return f"{delta.days}d ago"
    except ValueError:
        return "—"


def time_color(date_str):
    if not date_str or str(date_str) in ("None", "nan", ""):
        return "color: #444444"
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        delta = datetime.today() - dt
        if delta.days == 0:
            return "color: #00ff00"
        if delta.days <= 1:
            return "color: #ffff00"
        return "color: #ff4444"
    except ValueError:
        return "color: #444444"


def color_decision(val):
    val = str(val).upper()
    if "BUY" in val or "OVERWEIGHT" in val:
        return "background-color: #1a4a1a; color: #00ff00"
    if "SELL" in val or "UNDERWEIGHT" in val:
        return "background-color: #4a1a1a; color: #ff4444"
    if val in ("—", "UNKNOWN", "NAN", ""):
        return "color: #444444"
    return "background-color: #3a3a1a; color: #ffff00"


def decision_label(val):
    """Compact display label for a decision verdict.

    UNDERWEIGHT and OVERWEIGHT are abbreviated to fit the master table's
    narrow per-mode columns without wrapping. Pair with `title=` on the
    rendered span to preserve the full word on hover.
    """
    val = str(val).upper()
    if val == "UNDERWEIGHT":
        return "UNDER"
    if val == "OVERWEIGHT":
        return "OVER"
    return val
