"""Run-queue + launch button.

Demo mode: provider is selected via session_state from hero's BYOK widget.
Prod mode: provider is selected here via radio (default Ollama).
"""
import os
import subprocess
import threading
import streamlit as st

import db
from .demo import DEMO_MODE
from .providers import PROVIDERS, get_by_label


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
}


def render(managed_tickers, status, project_root, python_bin, runner_path):
    st.subheader("Run Queue")

    queued = [t for t in managed_tickers if st.session_state.get(f"chk_{t}", False)]

    col_queue, col_mode, col_btn = st.columns([3, 2, 1])

    with col_queue:
        st.write(f"Queued: {', '.join(queued)}" if queued else "No tickers queued.")

    with col_mode:
        modes_available = ["solo", "core"] if DEMO_MODE else ["solo", "core", "full"]
        run_mode = st.radio(
            "Mode",
            modes_available,
            index=1 if "core" in modes_available else 0,
            horizontal=True,
            help="\n".join(f"{m}: {MODE_HINTS[m]}" for m in modes_available),
        )

    with col_btn:
        clicked = st.button("🚀 Run", type="primary")

    # Token hints under the radio
    st.caption(MODE_HINTS.get(run_mode, ""))

    # Provider selector — demo mode reads from BYOK session_state, prod has a radio
    provider_entry = _resolve_provider(DEMO_MODE)
    if not DEMO_MODE:
        st.caption(f"Provider: **{provider_entry['label']}** · model `{provider_entry['model']}`")

    # Demo mode: explain why full is disabled
    if DEMO_MODE:
        with st.expander("ℹ️ Why is full mode disabled in demo?"):
            st.markdown(
                "Full mode runs a 7-agent debate via TradingAgents — analyst, researcher, "
                "trader, risk manager, and others argue across multiple rounds. It produces "
                "the most thorough analysis but uses **~400K tokens per ticker**, which would "
                "burn through any free tier in a single run. It's disabled in the demo so a "
                "single click can't drain your API quota. The full pipeline runs in the "
                "production deployment; see GitHub for details."
            )

    if clicked:
        _handle_click(queued, run_mode, provider_entry, status, project_root, python_bin, runner_path)


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

    # Prod mode: simple radio between Ollama (default) and Gemini cloud
    chosen = st.radio(
        "Provider",
        ["Ollama (local)", "Gemini Flash"],
        index=0,
        horizontal=True,
        key="prod_provider_radio",
    )
    return get_by_label(chosen)


def _handle_click(queued, run_mode, provider_entry, status, project_root, python_bin, runner_path):
    if not queued:
        st.warning("Queue is empty.")
        return
    if status["status"] == "running":
        st.error("A job is already running.")
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
        url = st.session_state.get("byok_ollama_url", "")
        if url:
            env["OLLAMA_BASE_URL"] = url

    # Hand the subprocess this session's DB and status paths so its
    # writes land in the same place the dashboard reads from.
    env["TRADER_ADVISOR_DB_PATH"] = db.db_path()
    env["TRADER_ADVISOR_STATUS_FILE"] = db.status_file()

    tickers_arg = ",".join(queued)
    mode_args = []
    if run_mode == "full":
        mode_args = ["--full"]
    elif run_mode == "solo":
        mode_args = ["--solo"]

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

        st.session_state["clear_queue"] = True
        st.success(f"Job started (PID {proc.pid}) — provider {provider_entry['label']}")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to start: {e}")
