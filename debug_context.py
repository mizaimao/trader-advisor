"""Print exactly what the LLM sees, without invoking it."""
import sys
import traceback
from datetime import date

if "--ticker" in sys.argv:
    idx = sys.argv.index("--ticker")
    ticker = sys.argv[idx + 1]
else:
    ticker = "NVDA"

today = date.today().strftime("%Y-%m-%d")

print(f"Building context for {ticker} as of {today}...\n")

try:
    from runner import fetch_context
except Exception as e:
    print(f"FAILED to import fetch_context: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    context = fetch_context(ticker, today)
except Exception as e:
    print(f"FAILED inside fetch_context: {e}")
    traceback.print_exc()
    sys.exit(1)

from prompts import SIMPLE_SYSTEM, SIMPLE_USER

print("=" * 70)
print("SYSTEM PROMPT")
print("=" * 70)
print(SIMPLE_SYSTEM)
print()
print("=" * 70)
print("USER PROMPT (context payload sent to LLM)")
print("=" * 70)
print(SIMPLE_USER.format(ticker=ticker, today=today, context=context))
print()
print("=" * 70)
print(f"Context size: {len(context):,} chars")
print(f"Section markers found: {context.count('## ')}")
print(f"Multi-timeframe data present: {'### Last 5 years' in context}")
print("=" * 70)
