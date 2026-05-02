from openai import OpenAI
import json
from typing import Any

DEFAULT_MODEL: str = "gpt-oss:20b"

client = OpenAI(
    base_url = "http://ml39.local:11434/v1",
    api_key = "ollama"
)

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
    {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'description': 'Get the current weather for a city',
        'parameters': {
            'type': 'object',
            'properties': {
                'city': {'type': 'string', 'description': 'The name of the city'},
            },
            'required': ['city'],
        },
    },
}
]

# A fake function to help understand the loop.
def get_weather(city: str) -> str:
    return "if the city is NYC then the tempeature is 70F. Elsewhere it's 230F."

# Initial message
prompt: str = "Hey what's the weather in Tokyo?"
messages = [
    {'role': 'user', 'content': prompt}
]

# Initial API call and we log its response.
response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    tools=tools,
    tool_choice="auto"
)
# We get the response from the LLM, and then append it right back to the conversation log.
assistant_msg = response.choices[0].message
messages.append(assistant_msg.model_dump(exclude_unset=True))
# print("Content:", repr(assistant_msg.content))
# print("Tool calls:", assistant_msg.tool_calls)
# print("Raw assistant_msg structure:")
# print(assistant_msg.model_dump_json(indent=2))

# Call tools based on LLM's decision.
if assistant_msg.tool_calls:
    for call in assistant_msg.tool_calls:
        args: dict[str, str] = json.loads(call.function.arguments)

        if call.function.name == "get_weather":
            result: str =  get_weather(args["city"])
        else:
            pass

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": result if result else ""
            }

        )

# For debugging.
for m in messages:
    print(m)

# === 7. Second API call — model has tool results, produces final text ===
final = client.chat.completions.create(
    model=model_name,
    messages=messages,
    tools=tools,
    tool_choice="auto"
)

# === 8. Print the final answer ===
# Hint: response.choices[0].message.content
print(final.choices[0].message.content)