from openai import OpenAI
import json
from typing import Any, Callable

from prices import tool_get_price_context, get_price_context
from indicators import tool_get_indicator_text, get_indicator_text
from news import (
    tool_get_news_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_days_until_earnings,
    get_news_finnhub,
    get_insider_transactions_finnhub,
    days_until_earnings,
)

DEFAULT_MODEL: str = "gpt-oss:20b"
DEFAULT_MAX_TOOL_CALLS: int = 10

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


# Here we define tools available to use. May need to refactor to smaller chunks.
tools: list[dict[str, Any]] = [
    tool_get_price_context,
    tool_get_indicator_text,
    tool_get_news_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_days_until_earnings,
]

tool_func_mapper: dict[str, Callable] = {
    "get_price_context": get_price_context,
    "get_indicator_text": get_indicator_text,
    "get_news_finnhub": get_news_finnhub,
    "get_insider_transactions_finnhub": get_insider_transactions_finnhub,
    "days_until_earnings": days_until_earnings,
}

# Initial message
system_prompt: str = (
    "You are a stock trader and wants to decide what to do with the given stock NVDA"
    "You have access to a bunch of tools but have limited number of calls."
    f"[Budget: Now you have {remaining_tool_calls}/{max_tool_calls} calls so use them wisely.]"
)
messages = [{"role": "system", "content": system_prompt}]

# Initial API call and we log its response.
response = client.chat.completions.create(
    model=model_name, messages=messages, tools=tools, tool_choice="auto"
)
# We get the response from the LLM, and then append it right back to the conversation log.
assistant_msg = response.choices[0].message
messages.append(assistant_msg.model_dump(exclude_unset=True))
# print("Content:", repr(assistant_msg.content))
# print("Tool calls:", assistant_msg.tool_calls)
# print("Raw assistant_msg structure:")
# print(assistant_msg.model_dump_json(indent=2))

while remaining_tool_calls:
    # Call tools based on LLM's decision.
    if assistant_msg.tool_calls:
        for call in assistant_msg.tool_calls:

            if not remaining_tool_calls:
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
                    "content": result if result else "",
                }
            )

            messages.append(
                {"role": "user", "content": f"You now have {remaining_tool_calls}/{max_tool_calls} tool use left, use them wisely!"}
            )

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    assistant_msg = response.choices[0].message
    messages.append(assistant_msg.model_dump(exclude_unset=True))
    # else:  # The LLM decides not to use tools.
    #     break

# For debugging.
for m in messages:
    print(m)

# final API call
final = client.chat.completions.create(
    model=model_name, messages=messages, tools=tools, tool_choice="none"  # No more tool calls for the final answer.
)
print(final.choices[0].message.content)
breakpoint()

# === 8. Print the final answer ===
# Hint: response.choices[0].message.content
print(final.choices[0].message.content)
