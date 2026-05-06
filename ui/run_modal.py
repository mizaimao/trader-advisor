"""Run Analysis modal — replaces the old About-tab BYOK + Run Queue panels.

Triggered by the persistent top-right "⚡ Run Analysis" button. Opens via
`@st.dialog` decorator, large width.

Contents:
A. Provider + Model dropdowns + API key (masked-from-env with override pattern)
   (Ollama special case: base URL field instead of API key)
B. Ticker mini-table with freshness column + multi-select checkboxes
C. Mode radio (defaults to agent) + agent budget sliders (interactive in demo
   so visitors can see the tuning surface)
D. Cost preview line
E. Cancel / Run Now buttons

In demo mode: Run Now is disabled, all interactive surfaces are visible
(sliders / dropdowns drag-able), but the run can't fire. The disabled
button's tooltip explains why.
"""
import json
import os
import subprocess
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

import db
from .data_sources import disabled_sources
from .demo import DEMO_MODE
from .providers import PROVIDERS, get_by_label
from .ollama_probe import normalize_for_openai


# ── Provider/model registry built from existing PROVIDERS ──────────────────
PROVIDER_DISPLAY_NAMES = {
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "ollama": "Ollama (local)",
}

ENV_KEY_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}

# Per-1K-token cost rates, blended (~95% prompt / 5% completion ratio for
# typical agent runs). Rough; meant for the cost-preview line, not billing.
COST_PER_1K = {
    "anthropic": 0.006,   # ~Sonnet 4.6 blend
    "openai": 0.0075,
    "gemini": 0.002,
    "ollama": 0.0,        # local
}

# Token estimates per ticker for a typical run, by mode.
PER_TICKER_TOKENS = {
    "solo": 18_000,
    "core": 55_000,
    "full": 400_000,  # all 4 analysts; scales linearly when fewer are picked
    # agent: scales with tool-call budget — handled separately
}

FULL_ANALYSTS = ["market", "social", "news", "fundamentals"]
FULL_ANALYST_LABELS = {
    "market": "Market (technical)",
    "social": "Social sentiment",
    "news": "News",
    "fundamentals": "Fundamentals",
}


# Fallback Ollama model list, used only when the live `/api/tags` probe fails
# (server unreachable, demo mode, network issue). In normal operation the
# modal pulls the actual installed-models list from the configured URL.
_OLLAMA_FALLBACK_MODELS = [
    "gpt-oss:20b",
    "gemma4:26b",
    "qwen3.6:latest",
]


def _build_provider_groups(ollama_url=None):
    """Group entries from providers.PROVIDERS by provider key.

    For Ollama: probe the server's `/api/tags` endpoint to list installed
    models live. Falls back to a small hardcoded list only if the probe
    fails. The probe is cached at 60s TTL by `ui/ollama_probe.py` so calling
    this on every modal render is cheap.

    Returns dict { provider_key: [(label, model), ...] }.
    """
    grouped: dict[str, list[tuple[str, str]]] = {}
    for p in PROVIDERS:
        grouped.setdefault(p["provider"], []).append((p["label"], p["model"]))

    probed_models: list[str] = []
    if ollama_url:
        from .ollama_probe import probe_models
        models, _err = probe_models(ollama_url)
        probed_models = models or []

    if probed_models:
        # Tag the "recommended for agent" model so the user can spot it.
        grouped["ollama"] = [
            (
                f"{m} (recommended for agent)" if m == "gpt-oss:20b" else m,
                m,
            )
            for m in probed_models
        ]
    else:
        grouped["ollama"] = [(m, m) for m in _OLLAMA_FALLBACK_MODELS]

    return grouped


# ── The dialog ──────────────────────────────────────────────────────────────
@st.dialog("Run Analysis", width="large")
def run_analysis_modal(
    managed_tickers, df, status,
    project_root, python_bin, runner_path,
):
    if DEMO_MODE:
        st.caption(
            "🔒 Demo mode — inputs and sliders are interactive so you can "
            "see the configurability surface, but **Run Now** is disabled. "
            "Clone the repo to run live."
        )

    # Resolve the Ollama URL BEFORE building provider groups so the model
    # dropdown can be populated from the live /api/tags probe. The URL field
    # itself renders later (in the API-key block), but its value lives in
    # session_state across reruns, so reading it here is safe — on a fresh
    # session we fall back to the env var or localhost default.
    ollama_url_for_probe = (
        st.session_state.get("modal_ollama_url")
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://localhost:11434"
    )
    grouped = _build_provider_groups(ollama_url=ollama_url_for_probe)
    provider_keys = list(grouped.keys())
    # Default to Ollama on first open — agent mode requires it, and it's the
    # only provider that works without external API keys. Subsequent opens
    # use whatever the user last selected (session_state via the key).
    default_provider_idx = (
        provider_keys.index("ollama") if "ollama" in provider_keys else 0
    )

    # ── A. Provider + Model + API key ───────────────────────────────────
    st.markdown("##### Provider")
    col_prov, col_model = st.columns(2)
    with col_prov:
        provider = st.selectbox(
            "Provider",
            provider_keys,
            index=default_provider_idx,
            format_func=lambda p: PROVIDER_DISPLAY_NAMES.get(p, p),
            key="modal_provider",
            label_visibility="collapsed",
        )
    with col_model:
        # When the provider changes, drop the stale model-label from session
        # state — it's almost certainly not in the new provider's options
        # and Streamlit's selectbox state-persistence makes it stick to a
        # value that no longer exists, leaving the dropdown unselectable.
        if st.session_state.get("_modal_prev_provider") != provider:
            st.session_state.pop("modal_model_label", None)
            st.session_state["_modal_prev_provider"] = provider

        model_choices = grouped[provider]
        # Display by label, return underlying model id
        labels = [lbl for lbl, _ in model_choices]
        chosen_label = st.selectbox(
            "Model",
            labels,
            key="modal_model_label",
            label_visibility="collapsed",
        )
        model = next(m for lbl, m in model_choices if lbl == chosen_label)

    # API key field (env-var-with-override pattern) for cloud providers.
    api_key_override: Optional[str] = None
    has_usable_key = True  # ollama doesn't need a key

    env_key_var = ENV_KEY_BY_PROVIDER.get(provider)
    if env_key_var:
        env_key = os.environ.get(env_key_var)
        if env_key:
            masked = (
                f"{env_key[:7]}…{env_key[-4:]}"
                if len(env_key) > 12
                else "✓"
            )
            col_status, col_override = st.columns([3, 1])
            with col_status:
                st.markdown(
                    f'<div style="color:#5cb85c;padding:6px 0">'
                    f'✓ Key loaded from <code>{env_key_var}</code>: '
                    f'<code>{masked}</code></div>',
                    unsafe_allow_html=True,
                )
            with col_override:
                if st.button(
                    "Override", key="modal_show_override", width="stretch"
                ):
                    st.session_state["modal_show_override_input"] = True
            if st.session_state.get("modal_show_override_input"):
                api_key_override = st.text_input(
                    "Override key",
                    type="password",
                    disabled=DEMO_MODE,
                    placeholder="Paste a different key for this run",
                    key="modal_api_key_override",
                )
        else:
            api_key_override = st.text_input(
                f"{PROVIDER_DISPLAY_NAMES[provider]} API key",
                type="password",
                disabled=DEMO_MODE,
                placeholder="Disabled in demo" if DEMO_MODE else "sk-…",
                key="modal_api_key",
                help=(
                    f"Set `{env_key_var}` in your `.env` to skip this prompt "
                    "next time."
                ),
            )
            has_usable_key = bool(api_key_override)
    elif provider == "ollama":
        ollama_url_default = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        ollama_url = st.text_input(
            "Ollama base URL",
            value=ollama_url_default,
            disabled=DEMO_MODE,
            key="modal_ollama_url",
            help="Local server (default localhost:11434) or a remote URL.",
        )
    else:
        ollama_url = None

    st.divider()

    # ── B. Ticker mini-table ────────────────────────────────────────────
    # Always editable, even in demo — selection feeds the cost preview so
    # users can explore "what would this cost?". The Run Now button is
    # still gated by DEMO_MODE so they can't actually fire a job.
    st.markdown("##### Tickers")
    sel_all_col, clear_col, _spacer = st.columns([1, 1, 4])
    with sel_all_col:
        if st.button("Select all", key="modal_select_all", width="stretch"):
            st.session_state["_modal_select_default"] = True
            st.session_state.pop("modal_ticker_table", None)
            st.rerun()
    with clear_col:
        if st.button("Clear", key="modal_clear_all", width="stretch"):
            st.session_state["_modal_select_default"] = False
            st.session_state.pop("modal_ticker_table", None)
            st.rerun()

    freshness_df = _build_freshness_df(
        managed_tickers, df,
        default_select=st.session_state.get("_modal_select_default", False),
    )
    edited = st.data_editor(
        freshness_df,
        column_config={
            "select": st.column_config.CheckboxColumn("Run", default=False),
            "ticker": st.column_config.TextColumn("Ticker", disabled=True),
            "last_run_age": st.column_config.TextColumn(
                "Last run", disabled=True,
            ),
            "last_mode": st.column_config.TextColumn("Mode", disabled=True),
            "last_decision": st.column_config.TextColumn(
                "Verdict", disabled=True,
            ),
        },
        hide_index=True,
        width="stretch",
        height=280,
        key="modal_ticker_table",
    )
    if isinstance(edited, pd.DataFrame) and "select" in edited.columns:
        selected_tickers = edited[edited["select"]]["ticker"].tolist()
    else:
        selected_tickers = []

    st.divider()

    # ── C. Mode + Agent budget controls ─────────────────────────────────
    st.markdown("##### Mode & Settings")
    modes = ["agent", "solo", "core", "full"]
    mode = st.radio(
        "Mode",
        modes,
        horizontal=True,
        index=0,  # agent default
        key="modal_mode",
        label_visibility="collapsed",
    )

    max_tool_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    selected_analysts: list[str] = list(FULL_ANALYSTS)
    if mode == "agent":
        col_calls, col_tokens = st.columns(2)
        with col_calls:
            max_tool_calls = st.slider(
                "Max tool calls",
                min_value=4, max_value=20, value=12,
                key="modal_max_tool_calls",
                help=(
                    "Cap on tool calls the agent can make. Final-answer "
                    "turns don't count."
                ),
            )
        with col_tokens:
            max_tokens = st.slider(
                "Max tokens (cumulative)",
                min_value=20_000, max_value=200_000, value=120_000,
                step=10_000,
                key="modal_max_tokens",
                help="Cumulative token cap across all API calls in the run.",
            )
    elif mode == "full":
        st.markdown(
            "**Analysts** — TradingAgents runs up to 4 in parallel. "
            "Drop one to cut ~25% off runtime/tokens."
        )
        cols = st.columns(len(FULL_ANALYSTS))
        picked = []
        for col, key in zip(cols, FULL_ANALYSTS):
            with col:
                if st.checkbox(
                    FULL_ANALYST_LABELS[key],
                    value=True,
                    key=f"modal_full_analyst_{key}",
                ):
                    picked.append(key)
        if not picked:
            st.warning("Pick at least one analyst.")
        selected_analysts = picked

    # ── D. Cost preview ─────────────────────────────────────────────────
    # For ollama we still show a dollar estimate (priced at the Anthropic
    # Sonnet reference rate) so the user has a sense of scale, then tag
    # it as free since local inference doesn't actually cost anything.
    n_tickers = len(selected_tickers)
    est_tokens = _estimate_total_tokens(
        mode, max_tool_calls, n_tickers,
        full_analyst_count=len(selected_analysts),
    )
    provider_rate = COST_PER_1K.get(provider, 0)
    rate = provider_rate or COST_PER_1K["anthropic"]
    est_cost = est_tokens / 1000 * rate
    cost_str = f"~${est_cost:.4f}"
    if provider == "ollama":
        cost_str += " (free for local inference)"
    st.caption(
        f"Estimated: **{n_tickers}** ticker(s) · ~{est_tokens:,} tokens · "
        f"{cost_str}"
    )
    if provider == "ollama":
        rate_basis = (
            f"Dollar figure priced at the Anthropic Sonnet reference rate "
            f"(${COST_PER_1K['anthropic']:.4f}/1K tokens) for scale — "
            f"local inference on `{model}` is free."
        )
    else:
        rate_basis = (
            f"Estimate uses the {PROVIDER_LABELS.get(provider, provider)} "
            f"blended rate (${rate:.4f}/1K tokens). Actual cost on "
            f"`{model}` will vary with the prompt/completion split."
        )
    st.caption(rate_basis)

    # ── E. Action buttons ───────────────────────────────────────────────
    col_cancel, col_run = st.columns([1, 1])
    with col_cancel:
        if st.button("Cancel", width="stretch", key="modal_cancel"):
            _reset_modal_state()
            st.rerun()
    with col_run:
        # Disable rules
        no_tickers = not selected_tickers
        no_key = (
            env_key_var is not None
            and not os.environ.get(env_key_var)
            and not api_key_override
        )
        agent_provider_mismatch = mode == "agent" and provider != "ollama"
        no_analysts = mode == "full" and not selected_analysts
        run_disabled = (
            DEMO_MODE
            or no_tickers
            or no_key
            or agent_provider_mismatch
            or no_analysts
            or status["status"] == "running"
        )
        if DEMO_MODE:
            run_help = "Disabled in demo — clone the repo and run locally."
        elif status["status"] == "running":
            run_help = "A run is already in flight. Wait for it to finish."
        elif no_tickers:
            run_help = "Pick at least one ticker to run."
        elif no_key:
            run_help = (
                f"Add `{env_key_var}` to your `.env` or paste a key above."
            )
        elif agent_provider_mismatch:
            run_help = (
                "Agent mode currently requires Ollama. Other providers will "
                "be supported once the Anthropic adapter ships."
            )
        elif no_analysts:
            run_help = "Pick at least one analyst for full mode."
        else:
            run_help = None

        if st.button(
            "Run Now",
            type="primary",
            disabled=run_disabled,
            help=run_help,
            width="stretch",
            key="modal_run_now",
        ):
            _fire_run(
                tickers=selected_tickers,
                provider=provider,
                model=model,
                mode=mode,
                api_key_override=api_key_override,
                ollama_url=ollama_url if provider == "ollama" else None,
                max_tool_calls=max_tool_calls,
                max_tokens=max_tokens,
                analysts=selected_analysts if mode == "full" else None,
                env_key_var=env_key_var,
                project_root=project_root,
                python_bin=python_bin,
                runner_path=runner_path,
            )
            _reset_modal_state()
            st.rerun()


# ── Helpers ─────────────────────────────────────────────────────────────────
def _build_freshness_df(managed_tickers, df, default_select=False):
    """Build the per-ticker latest-run summary table."""
    rows = []
    for ticker in managed_tickers:
        row = {
            "select": default_select,
            "ticker": ticker,
            "last_run_age": "—",
            "last_mode": "—",
            "last_decision": "—",
        }
        if not df.empty and ticker in set(df["ticker"]):
            ticker_runs = df[df["ticker"] == ticker].sort_values(
                "id", ascending=False
            )
            latest = ticker_runs.iloc[0]
            row["last_mode"] = latest.get("mode") or "—"
            row["last_decision"] = latest.get("decision") or "—"
            ts = latest.get("created_at") or latest.get("run_date")
            row["last_run_age"] = _age_label(ts)
        rows.append(row)
    return pd.DataFrame(rows)


def _age_label(ts):
    """Convert a timestamp to 'Xh ago' / 'Xd ago' / 'Just now' / '—'."""
    if not ts:
        return "—"
    try:
        dt = pd.to_datetime(ts)
        delta = datetime.now() - dt.to_pydatetime().replace(tzinfo=None)
        secs = delta.total_seconds()
    except Exception:
        return "—"
    if secs < 0:
        return "—"
    if secs < 60:
        return "Just now"
    if secs < 3600:
        return f"{int(secs / 60)}m ago"
    if secs < 86400:
        return f"{int(secs / 3600)}h ago"
    days = int(secs / 86400)
    return f"{days}d ago"


def _estimate_total_tokens(
    mode, agent_max_tool_calls, num_tickers, *, full_analyst_count=4,
):
    """Rough total-token estimate for a run, summed across tickers."""
    if num_tickers == 0:
        return 0
    if mode == "agent":
        # Observed avg: ~7K tokens per tool call in agent loops.
        per_ticker = (agent_max_tool_calls or 10) * 7_000
    elif mode == "full":
        # Default 400K assumes all 4 analysts; scale linearly.
        scale = max(full_analyst_count, 1) / 4
        per_ticker = int(PER_TICKER_TOKENS["full"] * scale)
    else:
        per_ticker = PER_TICKER_TOKENS.get(mode, 0)
    return per_ticker * num_tickers


def _reset_modal_state():
    """Clear ephemeral modal state on close so the next open feels fresh.
    Provider/model selections are intentionally NOT cleared (per spec —
    'provider stays, ticker selection clears')."""
    for k in (
        "modal_ticker_table",
        "modal_show_override_input",
        "modal_api_key_override",
        "modal_api_key",
    ):
        st.session_state.pop(k, None)


def _fire_run(
    *,
    tickers, provider, model, mode,
    api_key_override, ollama_url,
    max_tool_calls, max_tokens,
    analysts,
    env_key_var,
    project_root, python_bin, runner_path,
):
    """Spawn the runner subprocess. Mirrors the old run_queue._handle_click
    logic but reads inputs from modal-local state rather than the
    master_table-derived checkboxes."""
    env = os.environ.copy()

    if api_key_override and env_key_var:
        env[env_key_var] = api_key_override

    if provider == "ollama" and ollama_url:
        env["OLLAMA_BASE_URL"] = normalize_for_openai(ollama_url)

    env["TRADER_ADVISOR_DB_PATH"] = db.db_path()
    env["TRADER_ADVISOR_STATUS_FILE"] = db.status_file()

    disabled = sorted(disabled_sources())
    if disabled:
        env["TRADER_ADVISOR_DISABLED_SOURCES"] = json.dumps(disabled)

    tickers_arg = ",".join(tickers)
    mode_args = []
    if mode == "full":
        mode_args = ["--full"]
        if analysts and len(analysts) < 4:
            mode_args.extend(["--analysts", ",".join(analysts)])
    elif mode == "solo":
        mode_args = ["--solo"]
    elif mode == "agent":
        mode_args = ["--agent"]
        if max_tool_calls is not None:
            mode_args.extend(["--max-tool-calls", str(max_tool_calls)])
        if max_tokens is not None:
            mode_args.extend(["--max-tokens", str(max_tokens)])

    cmd = [
        python_bin, runner_path,
        "--tickers", tickers_arg,
        "--provider", provider,
        "--model", model,
        *mode_args,
    ]

    log_dir = os.path.dirname(db.status_file())
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "popen.log"), "w")

    try:
        proc = subprocess.Popen(
            cmd, cwd=project_root, env=env,
            stdout=log_file, stderr=log_file,
        )
        st.toast(
            f"⚡ Run started (PID {proc.pid}) — {provider} / `{model}`",
            icon="🚀",
        )
    except Exception as e:
        log_file.close()
        st.error(f"Failed to start: {e}")
