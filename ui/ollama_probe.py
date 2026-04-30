"""Probe an Ollama server for available models.

Hits the native /api/tags endpoint to enumerate installed models. Cached
briefly so the dashboard's frequent reruns don't hammer the user's server
on every keystroke.

URL canonicalization: users may paste either the bare host
(http://host:11434) or the OpenAI-compat URL (http://host:11434/v1).
- normalize_for_probe(): strip trailing /v1 — /api/tags lives outside it
- normalize_for_openai(): ensure /v1 is appended — that's what the
  langchain-openai client expects as base_url
"""
import requests
import streamlit as st


PROBE_TIMEOUT_SECONDS = 3


def _split(url):
    url = url.strip().rstrip("/")
    if url.endswith("/v1"):
        return url[:-3], url
    return url, url + "/v1"


def normalize_for_probe(url):
    return _split(url)[0]


def normalize_for_openai(url):
    return _split(url)[1]


@st.cache_data(ttl=60, show_spinner=False)
def probe_models(url):
    """Return (sorted model names, error_string).

    On success: (['llama3:8b', ...], None).
    On any failure: ([], short_human_message).
    """
    if not url or not url.strip():
        return [], "URL is empty"

    base = normalize_for_probe(url)
    try:
        r = requests.get(f"{base}/api/tags", timeout=PROBE_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        return [], f"timeout after {PROBE_TIMEOUT_SECONDS}s"
    except requests.exceptions.ConnectionError:
        return [], "connection refused / unreachable"
    except Exception as e:
        return [], str(e)[:120]

    if r.status_code != 200:
        return [], f"HTTP {r.status_code}"

    try:
        data = r.json()
    except ValueError:
        return [], "response was not JSON"

    names = [m.get("name") for m in data.get("models", []) if m.get("name")]
    if not names:
        return [], "server reachable but no models installed"

    return sorted(names), None
