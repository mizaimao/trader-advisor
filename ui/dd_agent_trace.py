"""Agent-mode trace renderer — vertical timeline of the tool-use loop.

Reads `runs.extra` JSON (written by agent.loop.run_agent via runner.py) and
renders each step as a divider-separated block: reasoning text + tool calls +
collapsed tool outputs. The final analysis paragraph is rendered separately
by dd_analysis.py — this file shows the *journey*, not the verdict.
"""
import json
import streamlit as st


def render(row):
    extra = row.get("extra")
    if not extra:
        st.info("No agent trace available for this run.")
        return

    try:
        meta = json.loads(extra) if isinstance(extra, str) else extra
    except (json.JSONDecodeError, TypeError):
        st.warning("Could not parse agent trace.")
        return

    trace = meta.get("trace", [])
    if not trace:
        st.info("Agent trace is empty.")
        return

    # Top-level run summary — folded into the expander label so the user can
    # see the run's shape without expanding the (potentially long) trace body.
    used = meta.get("tool_calls_used", 0)
    cap = meta.get("max_tool_calls", "?")
    forced = meta.get("forced_final", False)
    p_tokens = meta.get("prompt_tokens", 0)
    c_tokens = meta.get("completion_tokens", 0)

    label = f"🤖 Agent Trace — {used} of {cap} tool calls · {p_tokens + c_tokens:,} tokens"
    if forced:
        label += " · ⚠️ forced final"

    # Skip the terminal step (no tool_calls). Its `thought` is the final
    # analysis, which dd_analysis.py renders below this block.
    visible_steps = [s for s in trace if s.get("tool_calls")]
    terminal_reasoning = ""
    if trace and not trace[-1].get("tool_calls"):
        terminal_reasoning = (trace[-1].get("reasoning") or "").strip()

    with st.expander(label, expanded=False):
        # Dividers BETWEEN steps only — no leading divider right under the
        # expander header (would look duplicative against the expander border).
        for i, step in enumerate(visible_steps):
            if i > 0:
                st.divider()
            _render_step(step)

        if terminal_reasoning:
            if visible_steps:
                st.divider()
            _render_terminal_reasoning(terminal_reasoning)


def _render_step(step):
    budget = step.get("budget_remaining_before", "?")
    step_idx = step.get("step", "?")

    st.markdown(
        f"**Step {step_idx}** · "
        f"<span style='color:#888;font-size:13px'>{budget} calls remaining</span>",
        unsafe_allow_html=True,
    )

    reasoning = (step.get("reasoning") or "").strip()
    if reasoning:
        _render_reasoning(reasoning)

    # Visible content (often empty when the model is purely calling tools)
    thought = (step.get("thought") or "").strip()
    if thought:
        st.markdown(thought)

    # Tool calls + their matching results
    tool_calls = step.get("tool_calls", []) or []
    tool_results = step.get("tool_results", []) or []
    results_by_id = {r.get("id"): r for r in tool_results}

    for tc in tool_calls:
        _render_tool_call(tc, results_by_id.get(tc.get("id")))


def _render_reasoning(text):
    """Render the chain-of-thought as an italic, accent-bordered block."""
    safe = _escape_html(text)
    st.markdown(
        f"<div style='border-left:3px solid #7ab8f5;padding:8px 14px;"
        f"margin:6px 0 10px 0;color:#cbd5e0;font-style:italic;"
        f"line-height:1.65;font-size:14px'>💭 {safe}</div>",
        unsafe_allow_html=True,
    )


def _render_terminal_reasoning(text):
    """Same look as step reasoning but with a 'Final synthesis' header."""
    st.markdown(
        "**Synthesis** · "
        "<span style='color:#888;font-size:13px'>"
        "agent's reasoning before producing the final analysis"
        "</span>",
        unsafe_allow_html=True,
    )
    _render_reasoning(text)


def _render_tool_call(tc, result):
    name = tc.get("name", "?")
    args = tc.get("args", {})
    args_str = ", ".join(f"{k}={_repr_arg(v)}" for k, v in args.items())
    st.markdown(f"🔧 `{name}({args_str})`")

    if result is None:
        st.caption("(no result captured)")
        return

    output = result.get("output")
    is_error, output_str = _classify_output(output)

    if is_error:
        st.error(f"Tool error · {output_str[:400]}")
        return

    char_count = len(output_str)
    with st.expander(f"▼ Output · {char_count:,} chars", expanded=False):
        # st.code preserves whitespace and gives a monospace block. Use 'text'
        # because tool outputs are mixed (markdown-ish, JSON, plain) — a 'json'
        # hint would mis-highlight non-JSON tools like get_price_context.
        st.code(output_str, language="text")


def _classify_output(output):
    """Return (is_error, output_str). Detects {"error": ...} dicts AND
    JSON-strings of the same shape (the runner stringifies dispatch errors)."""
    if isinstance(output, dict):
        if "error" in output:
            return True, str(output.get("error", ""))
        return False, json.dumps(output, default=str, indent=2)
    if isinstance(output, list):
        return False, json.dumps(output, default=str, indent=2)
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict) and "error" in parsed:
                return True, str(parsed["error"])
        except (json.JSONDecodeError, ValueError):
            pass
        return False, output
    return False, str(output)


def _repr_arg(v):
    """Quote strings, format numbers/lists naturally, truncate long blobs."""
    if isinstance(v, str):
        if len(v) > 60:
            return f"'{v[:57]}…'"
        return f"'{v}'"
    return repr(v)


def _escape_html(text):
    """Minimal HTML escape that keeps newlines visible."""
    if not text:
        return ""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\n", "<br>")
    return text