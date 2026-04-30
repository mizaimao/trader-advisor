"""Run-queue + launch button (kicks off runner.py as a subprocess)."""
import os
import subprocess
import streamlit as st


def render(managed_tickers, status, project_root, python_bin, runner_path):
    st.subheader("Run Queue")

    queued = [t for t in managed_tickers if st.session_state.get(f"chk_{t}", False)]

    col_queue, col_mode, col_provider, col_btn = st.columns([3, 1.2, 1.2, 1])
    with col_queue:
        st.write(f"Queued: {', '.join(queued)}" if queued else "No tickers queued.")
    with col_mode:
        run_mode = st.radio("Mode", ["core", "solo", "full"], index=0)
    with col_provider:
        run_provider = st.radio("Provider", ["ollama (ml39)", "gemini (cloud)"], index=0)
    with col_btn:
        if st.button("🚀 Run", type="primary"):
            if not queued:
                st.warning("Queue is empty.")
            elif status["status"] == "running":
                st.error("A job is already running.")
            else:
                _launch(queued, run_mode, run_provider, project_root, python_bin, runner_path)


def _launch(queued, run_mode, run_provider, project_root, python_bin, runner_path):
    tickers_arg = ",".join(queued)
    provider_arg = "gemini" if "gemini" in run_provider else "ollama"
    mode_args = []
    if run_mode == "full":
        mode_args = ["--full"]
    elif run_mode == "solo":
        mode_args = ["--solo"]
    try:
        os.makedirs(os.path.expanduser("~/.tradingagents"), exist_ok=True)
        log_file = open(os.path.expanduser("~/.tradingagents/popen.log"), "w")
        proc = subprocess.Popen(
            [python_bin, runner_path,
             "--tickers", tickers_arg,
             "--provider", provider_arg,
             *mode_args],
            cwd=project_root,
            env=os.environ.copy(),
            stdout=log_file,
            stderr=log_file,
        )
        st.session_state["clear_queue"] = True
        st.success(f"Job started (PID {proc.pid})")
        st.rerun()
    except Exception as e:
        st.error(f"Failed: {e}")
