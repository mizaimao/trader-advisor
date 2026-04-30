"""Per-session ephemeral state for the HF demo deployment.

Each browser session gets /tmp/moose-demo/{session_id}/ holding its own
trading.db and run_status.json. Pre-populated from demo_template.db (if
present in repo root) on first session load. Tab-close = state lost,
reload = fresh session.

Only used when MOOSE_DEMO_MODE=true. In prod/local, db.py falls back to
~/.tradingagents/ as before.
"""
import os
import shutil
import time
import uuid
from pathlib import Path

import streamlit as st

from db import set_session_paths

DEMO_ROOT = "/tmp/moose-demo"
SESSION_TTL_SECONDS = 3600  # abandoned tabs swept after 1 hour

_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DB = _REPO_ROOT / "demo_template.db"


def _session_id():
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:12]
    return st.session_state.session_id


def session_dir():
    return os.path.join(DEMO_ROOT, _session_id())


def bootstrap():
    """Create session dir, seed from template, bind paths to thread.

    Called on every Streamlit rerun in demo mode — idempotent. Returns
    (db_path, status_path) so callers (like run_queue) can pass them to
    subprocess env.
    """
    sweep_old_sessions()
    sdir = session_dir()
    os.makedirs(sdir, exist_ok=True)

    db_path = os.path.join(sdir, "trading.db")
    status_path = os.path.join(sdir, "run_status.json")

    if not os.path.exists(db_path) and TEMPLATE_DB.exists():
        shutil.copy(TEMPLATE_DB, db_path)

    set_session_paths(db_path, status_path)
    return db_path, status_path


def sweep_old_sessions():
    """Delete /tmp/moose-demo/{sid}/ directories older than the TTL.

    Cheap stat-and-rmtree over a small dir. Runs on every rerun; the
    overhead is negligible compared to a Streamlit page render.
    """
    if not os.path.exists(DEMO_ROOT):
        return
    cutoff = time.time() - SESSION_TTL_SECONDS
    try:
        entries = os.listdir(DEMO_ROOT)
    except OSError:
        return
    for entry in entries:
        full = os.path.join(DEMO_ROOT, entry)
        try:
            if os.path.getmtime(full) < cutoff:
                shutil.rmtree(full, ignore_errors=True)
        except OSError:
            pass
