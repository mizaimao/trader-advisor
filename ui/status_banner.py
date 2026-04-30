"""Top-of-page job status banner.

In prod mode: full banner with kill button, PID, internal labels.
In demo mode: progress-only banner, no kill control, no internals.
"""
import os
import signal
import streamlit as st

from db import set_status


def render(status, demo_mode=False):
    if status["status"] != "running":
        if not demo_mode:
            st.success("✅ Idle — no jobs running")
        return

    completed = status.get("completed", 0)
    total = status.get("total", 0)
    current = status.get("current", "—")
    tickers = status.get("tickers", [])
    done = tickers[:completed]
    remaining = tickers[completed + 1:]
    mode = status.get("mode", "").upper()

    if demo_mode:
        # Clean progress banner, no internals
        progress_pct = (completed / total) if total else 0
        st.info(f"⚙️ **Analyzing {current}** — ticker {completed + 1} of {total}  ·  mode: **{mode}**")
        st.progress(progress_pct, text=f"{completed} of {total} complete")
        if done:
            st.caption(f"Completed: {', '.join(done)}")
        if remaining:
            st.caption(f"Remaining: {', '.join(remaining)}")
        # Auto-refresh hint
        if st.button("🔄 Refresh", key="demo_refresh_btn"):
            st.rerun()
    else:
        st.warning(
            f"⚙️ **[{mode}] Running** — "
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
