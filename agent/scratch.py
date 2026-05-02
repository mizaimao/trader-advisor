from openai import OpenAI
import json
from typing import Any, Callable

from prices import tool_get_price_context, get_price_context
from indicators import tool_get_indicator_text, get_indicator_text
from news import (
    tool_get_news_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_days_until_earnings,
    tool_get_earnings_calendar_finnhub,
    get_news_finnhub,
    get_insider_transactions_finnhub,
    days_until_earnings,
    get_earnings_calendar_finnhub,
)
from options import tool_options_summary_text, options_summary_text
from sector import tool_sector_summary_text, sector_summary_text
from fundamentals import tool_get_fundamentals_text, get_fundamentals_text
from sentiment import (
    tool_stocktwits_summary_text,
    tool_reddit_summary_text,
    stocktwits_summary_text,
    reddit_summary_text,
)

DEFAULT_MODEL: str = "gpt-oss:20b"
DEFAULT_MAX_TOOL_CALLS: int = 10

# Ollama-specific. Default temp is 0.8 and it gets too creative.
OLLAMA_OPTIONS: dict[str, Any] = {"num_ctx": 32768, "temperature": 0.3}
AGENT_SYSTEM: str = """
You are a stock trading advisor and the user would ask you a specific stock to analyze.
The user would want you to gather data, potentially from different sources and angles to perform the analysis.
You can request tool usage from a selection, and that will give you up-to-date data about the stock to help your analysis.

STRATEGY:
1. Start with `get_price_context` and `get_indicator_text` — that's the absolute basic
2. Branch based on what you observe — no need to fetch everything
3. Each tool call costs a step from your budget
4. When you have enough information, write your final analysis and surface the strongest counter-evidence you encountered, not just what supports your decision.
5. End your analysis with: FINAL DECISION: <BUY|SELL|HOLD>
"""

ticker = "NVDA"
user_prompt: str = f"Analyze {ticker} and recommend BUY/SELL/HOLD."


client = OpenAI(base_url="http://ml39.local:11434/v1", api_key="ollama")
max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
remaining_tool_calls: int = max_tool_calls

# Resolve models.
available_models: list[str] = [x.id for x in client.models.list().data]
if not available_models:
    raise ValueError("Client does not have models.")
print("Available modesl from client:")
for m in available_models:
    print(m)

model_name: str = available_models[0]
if DEFAULT_MODEL in available_models:
    print(f"Default model {DEFAULT_MODEL} found, will be using that...")
    model_name = DEFAULT_MODEL
else:
    print(f"Default model {DEFAULT_MODEL} not in client, will choose the first one.")

# The agent execution trace are stored here.
trace: list[dict] = []

# Here we define tools available to use. May need to refactor to smaller chunks.
# Ordered by hypothetical request frequency.
tools: list[dict[str, Any]] = [
    tool_get_price_context,
    tool_get_indicator_text,
    tool_get_fundamentals_text,
    tool_get_news_finnhub,
    tool_days_until_earnings,
    tool_get_earnings_calendar_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_options_summary_text,
    tool_sector_summary_text,
    tool_stocktwits_summary_text,
    tool_reddit_summary_text,
]

tool_func_mapper: dict[str, Callable] = {
    "get_price_context": get_price_context,
    "get_indicator_text": get_indicator_text,
    "get_fundamentals_text": get_fundamentals_text,
    "get_news_finnhub": get_news_finnhub,
    "days_until_earnings": days_until_earnings,
    "get_earnings_calendar_finnhub": get_earnings_calendar_finnhub,
    "get_insider_transactions_finnhub": get_insider_transactions_finnhub,
    "options_summary_text": options_summary_text,
    "sector_summary_text": sector_summary_text,
    "stocktwits_summary_text": stocktwits_summary_text,
    "reddit_summary_text": reddit_summary_text,
}


def normalize_assistant_msg(assistant_msg) -> dict:
    """Convert assistant message to a clean dict the API will accept on the next call.

    Helper function needed by GPT-OSS-20B which sometimes returns a dict not string.
    """
    msg = assistant_msg.model_dump(exclude_unset=True, exclude_none=True)

    # Ensure content is a string (Ollama's Harmony translation sometimes returns a dict)
    content = msg.get("content")
    if content is None:
        msg["content"] = ""
    elif not isinstance(content, str):
        msg["content"] = str(content)

    # Drop fields that aren't part of the OpenAI message schema and confuse Ollama on round-trip
    msg.pop("reasoning", None)
    msg.pop("function_call", None)  # legacy, replaced by tool_calls
    msg.pop("refusal", None)
    msg.pop("annotations", None)
    msg.pop("audio", None)
    return msg


def normalize_tool_result(result) -> str:
    """Fix tool result formats.
    Tools may return numbers or dicts or strings, while our OpenAI API only support string.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str)  # default=str handles numpy types inside
    return str(result)


def build_trace_entry(
    assistant_msg, *, step: int, budget_remaining_before: int
) -> dict:
    """Extract trace-friendly fields from an assistant message.

    Returns the response-derived portion of a trace entry with `tool_results`
    initialized to an empty list — the caller fills it in after each tool
    actually runs.

    Captures `reasoning` separately from `thought`. GPT-OSS emits chain-of-thought
    in the `reasoning` field while the visible answer goes in `content` — so a
    turn that only fires tool calls often has empty `content` and rich `reasoning`.
    Note: `normalize_assistant_msg` deliberately drops `reasoning` before round-trip
    to the API; this function reads it before that pruning happens.

    Args:
        assistant_msg: The .choices[0].message object from a completion response.
        step: Zero-indexed turn number.
        budget_remaining_before: Tool-call budget at the start of this turn
            (before any tools triggered by this assistant message run).

    Returns:
        Dict with keys: step, thought, reasoning, tool_calls, tool_results, budget_remaining_before.
        - thought: assistant's visible text content, "" if absent.
        - reasoning: model's chain-of-thought, "" if absent.
        - tool_calls: list of {name, args, id} dicts (args parsed from JSON).
        - tool_results: empty list, to be appended to during dispatch.
    """
    return {
        "step": step,
        "thought": assistant_msg.content or "",
        "reasoning": getattr(assistant_msg, "reasoning", None) or "",
        "tool_calls": [
            {
                "name": call.function.name,
                "args": (
                    json.loads(call.function.arguments)
                    if call.function.arguments
                    else {}
                ),
                "id": call.id,
            }
            for call in (assistant_msg.tool_calls or [])
        ],
        "tool_results": [],
        "budget_remaining_before": budget_remaining_before,
    }


def build_system_message(
    remaining_tool_calls: int, max_tool_calls: int
) -> dict[str, str]:
    budget_msg: str = (
        f"[Budget: Now you have {remaining_tool_calls}/{max_tool_calls} calls so use them wisely.]"
    )
    if remaining_tool_calls / max_tool_calls < 0.2:
        budget_msg += f"[LOW BUDGET WARNING: You've spent over 80% of your budget, only {remaining_tool_calls} tool calls remaining. Decide wisely before calling another tool.]"
    return {"role": "system", "content": AGENT_SYSTEM + budget_msg}


messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]

# Initial API call and we log its response.
response = client.chat.completions.create(
    model=model_name,
    messages=[build_system_message(remaining_tool_calls, max_tool_calls)] + messages,
    tools=tools,
    tool_choice="auto",
    extra_body={"options": OLLAMA_OPTIONS},
)
# We get the response from the LLM, and then append it right back to the conversation log.
assistant_msg = response.choices[0].message
messages.append(normalize_assistant_msg(assistant_msg))
trace.append(
    build_trace_entry(
        assistant_msg,
        step=0,
        budget_remaining_before=remaining_tool_calls,
    )
)

while remaining_tool_calls:
    # If the LLM does not call tools, break early it's done thinking.
    if not assistant_msg.tool_calls:
        break

    # Call tools based on LLM's decision.
    for call in assistant_msg.tool_calls:
        if not remaining_tool_calls:  # Tool use exhausted.
            break

        remaining_tool_calls -= 1

        args: dict[str, str] = json.loads(call.function.arguments)
        fn_name: str = call.function.name
        result: str = ""
        if fn_name in tool_func_mapper:
            try:
                result = tool_func_mapper[fn_name](**args)
            except Exception as e:
                result = json.dumps(
                    {"error": f"tool execution failed: {type(e).__name__}: {e}"}
                )
        else:
            result = json.dumps({"error": f"unknown tool: {fn_name}"})

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": normalize_tool_result(
                    result
                ),  # This field has to be a string.
            }
        )

        # Mirror the result into the current turn's trace entry so the
        # printed/displayed trace shows what the agent actually got back.
        # `result` is kept in its native type (str/dict/list) — display logic
        # decides how to render. `messages` already has the stringified copy.
        trace[-1]["tool_results"].append(
            {
                "id": call.id,
                "name": fn_name,
                "input": args,
                "output": result,
            }
        )

    response = client.chat.completions.create(
        model=model_name,
        messages=[build_system_message(remaining_tool_calls, max_tool_calls)]
        + messages,
        tools=tools,
        tool_choice="auto",
        extra_body={"options": OLLAMA_OPTIONS},
    )
    assistant_msg = response.choices[0].message
    messages.append(normalize_assistant_msg(assistant_msg))
    trace.append(
        build_trace_entry(
            assistant_msg,
            step=len(trace),
            budget_remaining_before=remaining_tool_calls,
        )
    )

# The LLM decides not to call functions and the loop broke early.
if not assistant_msg.tool_calls:
    final_message: str = response.choices[0].message.content
# Tool budget exhausted.
else:
    # final API call
    final_prompt = client.chat.completions.create(
        model=model_name,
        messages=[build_system_message(remaining_tool_calls, max_tool_calls)]
        + messages,
        tools=tools,
        tool_choice="none",  # No more tool calls for the final answer.
        extra_body={"options": OLLAMA_OPTIONS},
    )
    final_message = final_prompt.choices[0].message.content

for t in trace:
    for k, v in t.items():
        print(k, v)
    print()
    print()
    print()
    print()
    print()

print(final_message)
