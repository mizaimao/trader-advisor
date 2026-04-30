"""Top-of-page job status banner."""
import os
import signal
import streamlit as st

from db import set_status


def render(status):
    if status["status"] == "running":
        completed = status.get("completed", 0)
        total = status.get("total", 0)
        current = status.get("current", "—")
        done = status.get("tickers", [])[:completed]
        remaining = status.get("tickers", [])[completed + 1:]
        st.warning(
            f"⚙️ **[{status.get('mode','').upper()}] Running** — "
            f"**{current}** ({completed + 1} of {total}) | "
            f"Done: {', '.join(done) if done else 'none'} | "
            f"Remaining: {', '.join(remaining) if remaining else 'none'} | "
            f"Started: {status.get('started_at', '—')}"
        )
        col_refresh, col_kill, _ = st.columns([1, 1, 6])
        col_refresh.button("🔄 Refresh Status", key="refresh_btn")
        if col_kill.button("🛑 Kill Job", type="primary", key="kill_btn"):
            pid = status.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    set_status("idle")
                    st.success(f"Killed PID {pid}")
                    st.rerun()
                except (ProcessLookupError, OSError):
                    set_status("idle")
                    st.success(f"PID {pid} was already dead. Status cleared.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to kill: {e}")
            else:
                set_status("idle")
                st.success("Status forcibly cleared.")
                st.rerun()
    else:
        st.success("✅ Idle — no jobs running")
