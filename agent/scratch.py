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

def build_system_message(remaining_tool_calls: int, max_tool_calls: int) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
        "You are a stock trader and wants to decide what to do with the given stock ONDS"
        "You have access to a bunch of tools but have limited number of calls."
        f"[Budget: Now you have {remaining_tool_calls}/{max_tool_calls} calls so use them wisely.]"
    )
    }

messages: list[dict[str, str]] = []

# Initial API call and we log its response.
response = client.chat.completions.create(
    model=model_name, messages=[build_system_message(remaining_tool_calls, max_tool_calls)] + messages, tools=tools, tool_choice="auto"
)
# We get the response from the LLM, and then append it right back to the conversation log.
assistant_msg = response.choices[0].message
messages.append(normalize_assistant_msg(assistant_msg))

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
                "content": normalize_tool_result(result),  # This field has to be a string.
            }
        )

    response = client.chat.completions.create(
        model=model_name, 
        messages=[build_system_message(remaining_tool_calls, max_tool_calls)] + messages, 
        tools=tools, tool_choice="auto"
    )
    assistant_msg = response.choices[0].message
    messages.append(normalize_assistant_msg(assistant_msg))

# The LLM decides not to call functions and the loop broke early.
if not assistant_msg.tool_calls:
    final_message: str = response.choices[0].message.content
# Tool budget exhausted.
else:
    # final API call
    final_prompt = client.chat.completions.create(
        model=model_name,
        messages=[build_system_message(remaining_tool_calls, max_tool_calls)] + messages,
        tools=tools,
        tool_choice="none",  # No more tool calls for the final answer.
    )
    final_message = final_prompt.choices[0].message.content

for m in messages:
    print(m)
    print()
    print()
    print()
    print()
    print()

print(final_message)

