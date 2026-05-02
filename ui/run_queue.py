"""Run-queue + launch button.

Demo mode: provider is selected via session_state from hero's BYOK widget.
Prod mode: provider is selected here via radio (default Ollama).
"""
import json
import os
import subprocess
import threading
import streamlit as st

import db
from .data_sources import disabled_sources
from .demo import DEMO_MODE
from .providers import PROVIDERS, PROVIDER_LABELS, get_by_label


# Process-global registry of in-flight runs across all Streamlit sessions.
# Used in DEMO_MODE only, to cap concurrent subprocesses.
#
# Streamlit serves each session in its own thread, so reading + writing
# this dict needs a lock. Otherwise two visitors who hit Run at the same
# moment can both see len(_active_runs) < cap, both spawn, and exceed the
# cap. The check, the spawn, and the register all happen inside _active_lock.
_active_runs = {}  # session_id -> subprocess.Popen
_active_lock = threading.Lock()


def _reap_finished_locked():
    """Drop entries whose subprocess has exited. Caller must hold _active_lock.

    proc.poll() returns the exit code if the subprocess has terminated, or
    None if it's still running. So this is the line that decrements the
    registry — there is no separate event-driven removal, the pruning is
    lazy and happens whenever a new spawn attempt comes through.
    """
    for sid, proc in list(_active_runs.items()):
        if proc.poll() is not None:
            _active_runs.pop(sid, None)


def _try_spawn(sid, build_proc):
    """Atomically reap, check capacity, spawn, register.

    Returns the Popen on success, None if at capacity. Holding the lock
    across subprocess.Popen is intentional — fork+exec on Linux is fast
    and non-blocking, and keeping spawn inside the critical section is
    what makes the cap actually enforceable.
    """
    cap = int(os.getenv("MAX_CONCURRENT_RUNS", "4"))
    with _active_lock:
        _reap_finished_locked()
        if len(_active_runs) >= cap:
            return None
        proc = build_proc()
        _active_runs[sid] = proc
        return proc


# Token estimate per mode (rough averages from observed runs)
MODE_HINTS = {
    "solo": "~30s · ~18K tokens/run",
    "core": "~60s · ~55K tokens/run",
    "full": "~5–15 min · ~400K tokens/run",
    "agent": "~60–120s · variable tokens · up to 10 tool calls (LLM-driven)",
}


def render(managed_tickers, status, project_root, python_bin, runner_path):
    st.subheader("Run Queue")

    # Own ticker selection — replaces the previous master_table checkbox-fed
    # `chk_{ticker}` session_state pattern. Defaults to empty so the user has
    # to deliberately pick (preserves the "explicit gesture" UX).
    queued = st.multiselect(
        "Tickers to run",
        options=managed_tickers,
        default=[],
        key="run_queue_tickers",
        disabled=DEMO_MODE,
        help="Pick one or more tickers to queue. Defaults to empty.",
    )

    col_mode, col_btn = st.columns([3, 1])

    with col_mode:
        # All 4 modes in both demo and prod. In demo every control below is
        # disabled, so the visitor sees the full surface without firing runs.
        modes_available = ["solo", "core", "full", "agent"]
        run_mode = st.radio(
            "Mode",
            modes_available,
            index=1 if "core" in modes_available else 0,
            horizontal=True,
            help="\n".join(f"{m}: {MODE_HINTS[m]}" for m in modes_available),
            disabled=DEMO_MODE,
        )

    with col_btn:
        clicked = st.button(
            "🚀 Run",
            type="primary",
            disabled=DEMO_MODE,
            help=(
                "Disabled in demo mode. See top banner. Run locally to enable."
                if DEMO_MODE
                else None
            ),
        )
        if DEMO_MODE:
            st.caption("(disabled in demo)")

    # Token hints under the radio
    st.caption(MODE_HINTS.get(run_mode, ""))

    # Agent-only: budget sliders. Tool-call cap and cumulative-token cap.
    agent_max_tool_calls = None
    agent_max_tokens = None
    if run_mode == "agent":
        col_calls, col_tokens = st.columns(2)
        with col_calls:
            agent_max_tool_calls = st.slider(
                "Max tool calls",
                min_value=4,
                max_value=20,
                value=st.session_state.get("agent_max_tool_calls", 10),
                key="agent_max_tool_calls",
                help=(
                    "Cap on tool calls the agent can make. Final-answer turns "
                    "don't count. Lower = faster + cheaper but more constrained "
                    "reasoning. Higher = more thorough but more cost."
                ),
                disabled=DEMO_MODE,
            )
        with col_tokens:
            agent_max_tokens = st.slider(
                "Max tokens (cumulative)",
                min_value=50_000,
                max_value=200_000,
                value=st.session_state.get("agent_max_tokens", 120_000),
                step=10_000,
                key="agent_max_tokens",
                help=(
                    "Cumulative-tokens-across-API-calls budget. Each tool call "
                    "adds the growing message history to the next call's prompt, "
                    "so this scales with tool-call count. Observed: ~65K for a "
                    "7-tool run, ~100K+ for full 10-tool runs. Bumping helps when "
                    "the agent gets force-finalized with empty content."
                ),
                disabled=DEMO_MODE,
            )

    # Provider selector — demo mode reads from BYOK session_state, prod has a radio
    provider_entry = _resolve_provider(DEMO_MODE)
    if not DEMO_MODE:
        st.caption(f"Provider: **{provider_entry['label']}** · model `{provider_entry['model']}`")

    # Demo mode: explain why all modes are disabled (matches top-banner copy)
    if DEMO_MODE:
        with st.expander("ℹ️ Why are runs disabled in demo?"):
            st.markdown(
                "All four modes are disabled in demo for two reasons: "
                "(1) BYOK browser visitors can't realistically supply the multiple API "
                "keys the system needs (Finnhub + Alpha Vantage + LLM provider), and "
                "(2) Streamlit's rerun-on-interaction model fights live BYOK input flows. "
                "The full UI is exposed so you can see the system's surface — controls, "
                "modes, settings — without firing real runs. The pre-loaded analyses in "
                "the table above are real runs from the production deployment; click "
                "into any of them to see the full deep-dive (price chart, agent trace, "
                "options snapshot, sentiment, and more)."
            )

    if clicked:
        _handle_click(
            queued, run_mode, provider_entry, status,
            project_root, python_bin, runner_path,
            agent_max_tool_calls=agent_max_tool_calls,
            agent_max_tokens=agent_max_tokens,
        )


def _resolve_provider(demo_mode):
    """Pick which provider entry to use based on session state and mode."""
    if demo_mode:
        chosen_label = st.session_state.get("byok_provider_label")
        if chosen_label:
            entry = get_by_label(chosen_label)
            if entry:
                return entry
        # Fallback to Gemini Flash placeholder so the UI doesn't break before user picks
        return get_by_label("Gemini Flash")

    # Prod: full provider list. Keys come from .env (no BYOK form here).
    # Default lands on Ollama (local) — matches the original two-option radio.
    default_label = "Ollama (local)"
    default_idx = (
        PROVIDER_LABELS.index(default_label)
        if default_label in PROVIDER_LABELS else 0
    )
    chosen = st.selectbox(
        "Provider",
        PROVIDER_LABELS,
        index=default_idx,
        key="prod_provider_select",
    )
    entry = get_by_label(chosen)

    # When Ollama is picked in prod, auto-detect installed models from the
    # OLLAMA_BASE_URL env var so the user can switch models without editing
    # providers.py. Falls back silently if the probe can't reach the server.
    if entry and entry["is_local"]:
        url = os.getenv("OLLAMA_BASE_URL")
        if url:
            from .ollama_probe import probe_models
            models, err = probe_models(url)
            if models:
                # Default to whatever providers.py has hardcoded if it's
                # actually installed; otherwise pick the first model.
                default_model = entry["model"] if entry["model"] in models else models[0]
                model_idx = models.index(default_model)
                chosen_model = st.selectbox(
                    "Model",
                    models,
                    index=model_idx,
                    key="prod_ollama_model",
                    help=f"Auto-detected from OLLAMA_BASE_URL ({len(models)} installed).",
                )
                entry = {**entry, "model": chosen_model}

    return entry


def _handle_click(
    queued, run_mode, provider_entry, status,
    project_root, python_bin, runner_path,
    *, agent_max_tool_calls=None, agent_max_tokens=None,
):
    # Defense-in-depth: the Run button is disabled in DEMO_MODE so this should
    # never fire there, but if session_state is somehow manipulated, refuse.
    if DEMO_MODE:
        st.error(
            "Live runs are disabled in demo mode. Clone the repo and run "
            "locally to execute analyses — see the banner at the top of the page."
        )
        return
    if not queued:
        st.warning("Queue is empty.")
        return
    if status["status"] == "running":
        st.error("A job is already running.")
        return

    # Pre-flight: agent mode is currently Ollama-only. The loop hardcodes the
    # OpenAI-compatible client + base_url; routing an Anthropic/OpenAI key to
    # the Ollama endpoint just produces an auth failure. Anthropic/OpenAI
    # adapter lands in Phase 1 Step 9; until then, gate it here.
    if run_mode == "agent" and not provider_entry["is_local"]:
        st.error(
            "Agent mode currently requires an Ollama provider. "
            f"**{provider_entry['label']}** support is on the roadmap (Phase 1 Step 9). "
            "Either pick **Ollama (local)** with a reachable server, or run **solo** / "
            f"**core** with {provider_entry['label']}."
        )
        return

    # Pre-flight: if provider needs a key, it must be present in session_state
    if DEMO_MODE and provider_entry["needs_key"]:
        key = st.session_state.get("byok_api_key")
        if not key:
            st.error(
                f"⚠️ {provider_entry['label']} requires an API key. "
                "Open the **🔑 Try it yourself** expander above and enter your key first."
            )
            return

    # Build subprocess env — only this run sees the key, never os.environ
    env = os.environ.copy()
    if provider_entry["needs_key"]:
        key = st.session_state.get("byok_api_key", "")
        if key:
            env[provider_entry["key_env"]] = key

    if provider_entry["is_local"]:
        url = (st.session_state.get("byok_ollama_url") or "").strip()
        if url:
            from .ollama_probe import normalize_for_openai
            env["OLLAMA_BASE_URL"] = normalize_for_openai(url)
        # Override the hardcoded default with the user's choice (auto-detected
        # selectbox if the probe succeeded, manual text field if it didn't).
        user_model = (
            st.session_state.get("byok_ollama_model_select")
            or st.session_state.get("byok_ollama_model_manual")
        )
        if user_model:
            provider_entry = {**provider_entry, "model": user_model}

    # Hand the subprocess this session's DB and status paths so its
    # writes land in the same place the dashboard reads from.
    env["TRADER_ADVISOR_DB_PATH"] = db.db_path()
    env["TRADER_ADVISOR_STATUS_FILE"] = db.status_file()

    # Disabled toggleable sources from the data-sources panel. Always-on
    # sources (price, indicators, fundamentals) cannot be disabled.
    disabled = sorted(disabled_sources())
    if disabled:
        env["TRADER_ADVISOR_DISABLED_SOURCES"] = json.dumps(disabled)

    tickers_arg = ",".join(queued)
    mode_args = []
    if run_mode == "full":
        mode_args = ["--full"]
    elif run_mode == "solo":
        mode_args = ["--solo"]
    elif run_mode == "agent":
        mode_args = ["--agent"]
        if agent_max_tool_calls is not None:
            mode_args.extend(["--max-tool-calls", str(agent_max_tool_calls)])
        if agent_max_tokens is not None:
            mode_args.extend(["--max-tokens", str(agent_max_tokens)])

    cmd = [
        python_bin, runner_path,
        "--tickers", tickers_arg,
        "--provider", provider_entry["provider"],
        "--model", provider_entry["model"],
        *mode_args,
    ]

    try:
        log_dir = os.path.dirname(db.status_file())
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "popen.log"), "w")

        def build_proc():
            return subprocess.Popen(
                cmd, cwd=project_root, env=env,
                stdout=log_file, stderr=log_file,
            )

        if DEMO_MODE:
            sid = st.session_state.get("session_id", "default")
            proc = _try_spawn(sid, build_proc)
            if proc is None:
                log_file.close()
                cap = os.getenv("MAX_CONCURRENT_RUNS", "4")
                st.error(
                    f"⏳ Demo at capacity ({cap} concurrent runs). "
                    "Please try again in a minute."
                )
                return
        else:
            proc = build_proc()

        # Clear the multiselect after a successful spawn so the next click
        # starts from an empty queue.
        st.session_state["run_queue_tickers"] = []
        st.success(f"Job started (PID {proc.pid}) — provider {provider_entry['label']}")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to start: {e}")
