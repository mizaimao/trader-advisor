"""Central registry of supported LLM providers and models.

Each provider entry includes:
  - label: dropdown display string
  - provider: internal name passed to runner.py via --provider
  - model: specific model identifier
  - needs_key: whether a user API key is required (False for local Ollama)
  - is_local: whether this is a local/self-hosted provider
  - tokens_solo / tokens_core: rough estimates for the run-queue hints
"""

PROVIDERS = [
    {
        "label": "Gemini Flash",
        "provider": "gemini",
        "model": "gemini-flash-latest",
        "needs_key": True,
        "is_local": False,
        "key_env": "GOOGLE_API_KEY",
        "key_placeholder": "AIza...",
        "key_help_url": "https://aistudio.google.com/apikey",
    },
    {
        "label": "Gemini Pro",
        "provider": "gemini",
        "model": "gemini-pro-latest",
        "needs_key": True,
        "is_local": False,
        "key_env": "GOOGLE_API_KEY",
        "key_placeholder": "AIza...",
        "key_help_url": "https://aistudio.google.com/apikey",
    },
    {
        "label": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "needs_key": True,
        "is_local": False,
        "key_env": "ANTHROPIC_API_KEY",
        "key_placeholder": "sk-ant-...",
        "key_help_url": "https://console.anthropic.com/settings/keys",
    },
    {
        "label": "Claude Haiku 4.5",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "needs_key": True,
        "is_local": False,
        "key_env": "ANTHROPIC_API_KEY",
        "key_placeholder": "sk-ant-...",
        "key_help_url": "https://console.anthropic.com/settings/keys",
    },
    {
        "label": "OpenAI GPT-5.4",
        "provider": "openai",
        "model": "gpt-5-4-turbo",
        "needs_key": True,
        "is_local": False,
        "key_env": "OPENAI_API_KEY",
        "key_placeholder": "sk-...",
        "key_help_url": "https://platform.openai.com/api-keys",
    },
    {
        "label": "Ollama (local)",
        "provider": "ollama",
        "model": "gemma4:26b",
        "needs_key": False,
        "is_local": True,
        "key_env": None,
        "key_placeholder": None,
        "key_help_url": None,
        "url_env": "OLLAMA_BASE_URL",
        "url_placeholder": "http://localhost:11434/v1",
    },
]

PROVIDER_LABELS = [p["label"] for p in PROVIDERS]


def get_by_label(label):
    for p in PROVIDERS:
        if p["label"] == label:
            return p
    return None
