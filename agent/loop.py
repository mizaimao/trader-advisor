"""Tool-use agent loop. Promoted from agent/scratch.py.

Public API:
    from agent import run_agent
    text, meta = run_agent(ticker="NVDA", today="2026-05-02")

Talks to Ollama's native `/api/chat` endpoint (not the OpenAI `/v1` compat
layer). The compat layer silently drops per-request `options.num_ctx`, which
caused gpt-oss:120b to load at the server-default 8K context regardless of
what we asked for — and that 8K cap made long agent runs lose state and
re-fetch the same tools repeatedly. `/api/chat` honors `options.num_ctx`,
exposes the model's `thinking` field as a first-class peer of `content`,
and accepts the same OpenAI-format tool schema on the request side.

Provider abstraction deferred — currently always builds an Ollama-native
client. The Anthropic adapter slots in later (Phase 1 Spec, Step 9), at
which point this file refactors against an actual second implementation.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import requests

from config import OLLAMA_MODEL as DEFAULT_MODEL, OLLAMA_NUM_CTX_BY_MODE
from prices import tool_get_price_context, get_price_context
from indicators import tool_get_indicator_text, get_indicator_text
from news import (
    tool_get_news_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_days_until_earnings,
    tool_get_earnings_calendar_finnhub,
    get_news_finnhub,
    get_insider_transactions_finnhub,
    days_until_earnings,
    get_earnings_calendar_finnhub,
)
from options import tool_options_summary_text, options_summary_text
from sector import tool_sector_summary_text, sector_summary_text
from fundamentals import tool_get_fundamentals_text, get_fundamentals_text
from sentiment import (
    tool_stocktwits_summary_text,
    tool_reddit_summary_text,
    stocktwits_summary_text,
    reddit_summary_text,
)
from peers import tool_peer_comparison, peer_comparison


# ── Defaults ─────────────────────────────────────────────────────────────────
# DEFAULT_MODEL is imported from config.py as OLLAMA_MODEL — single source of
# truth across all modes (solo/core/full/agent).
DEFAULT_MAX_TOOL_CALLS: int = 10
DEFAULT_MAX_TOKENS: int = 120_000
# Native Ollama endpoint base. Pulled from the env to track ml60/local swaps;
# `/v1` suffix is tolerated (stripped before hitting /api/chat).
DEFAULT_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ml60.local:11434")

# Ollama options. temp=0.3 stabilizes tool-arg generation without flattening
# branching choices; default (~0.8) was producing rare ticker hallucinations.
# num_ctx comes from config.OLLAMA_NUM_CTX_BY_MODE — single source of truth
# across all modes (matches runner.py's _make_llm wiring for solo/core).
OLLAMA_OPTIONS: dict[str, Any] = {
    "num_ctx": OLLAMA_NUM_CTX_BY_MODE["agent"],
    "temperature": 0.3,
}


# ── Prompts ──────────────────────────────────────────────────────────────────
AGENT_SYSTEM: str = """
You are a stock trading advisor and the user would ask you a specific stock to analyze.
The user would want you to gather data, potentially from different sources and angles to perform the analysis.
You can request tool usage from a selection, and that will give you up-to-date data about the stock to help your analysis.

STRATEGY:
1. Start with `get_price_context` and `get_indicator_text` — that's the absolute basic
2. Branch based on what you observe — no need to fetch everything
3. Each tool call costs a step from your budget
4. When you have enough information, write your final analysis and surface the strongest counter-evidence you encountered, not just what supports your decision.
5. End your analysis with: FINAL DECISION: <BUY|SELL|HOLD>
"""


# ── Tool registry (module-level, hardcoded for v1) ───────────────────────────
# Ordered roughly by hypothetical request frequency. Order doesn't constrain
# the model's choice but slightly nudges weighting on similar options.
tools: list[dict[str, Any]] = [
    tool_get_price_context,
    tool_get_indicator_text,
    tool_get_fundamentals_text,
    tool_get_news_finnhub,
    tool_days_until_earnings,
    tool_get_earnings_calendar_finnhub,
    tool_get_insider_transactions_finnhub,
    tool_options_summary_text,
    tool_sector_summary_text,
    tool_stocktwits_summary_text,
    tool_reddit_summary_text,
    # Synthesis tool
    tool_peer_comparison,
]

tool_func_mapper: dict[str, Callable] = {
    "get_price_context": get_price_context,
    "get_indicator_text": get_indicator_text,
    "get_fundamentals_text": get_fundamentals_text,
    "get_news_finnhub": get_news_finnhub,
    "days_until_earnings": days_until_earnings,
    "get_earnings_calendar_finnhub": get_earnings_calendar_finnhub,
    "get_insider_transactions_finnhub": get_insider_transactions_finnhub,
    "options_summary_text": options_summary_text,
    "sector_summary_text": sector_summary_text,
    "stocktwits_summary_text": stocktwits_summary_text,
    "reddit_summary_text": reddit_summary_text,
    "peer_comparison": peer_comparison,
}


# Source IDs (from ui/data_sources.py TOGGLEABLE) → tool function names.
# Always-on sources (price, indicators, fundamentals) aren't listed — they
# can't be disabled via TRADER_ADVISOR_DISABLED_SOURCES regardless.
_SOURCE_TO_TOOL_NAMES: dict[str, list[str]] = {
    "earnings": ["days_until_earnings", "get_earnings_calendar_finnhub"],
    "insider": ["get_insider_transactions_finnhub"],
    "options": ["options_summary_text"],
    "sector": ["sector_summary_text"],
    "stocktwits": ["stocktwits_summary_text"],
    "reddit": ["reddit_summary_text"],
    "news": ["get_news_finnhub"],
}


def _disabled_tool_names() -> set[str]:
    """Return tool names to skip based on TRADER_ADVISOR_DISABLED_SOURCES env.

    The env var is JSON-encoded list of source IDs (e.g. ["options","reddit"]).
    Set by ui/run_queue.py when spawning the runner subprocess. Bad values are
    silently ignored — the agent can still produce a useful analysis with the
    full toolbox if the env var is malformed.
    """
    raw = os.getenv("TRADER_ADVISOR_DISABLED_SOURCES", "")
    if not raw:
        return set()
    try:
        disabled_sources = set(json.loads(raw))
    except (ValueError, TypeError):
        return set()
    skipped: set[str] = set()
    for source_id in disabled_sources:
        skipped.update(_SOURCE_TO_TOOL_NAMES.get(source_id, []))
    return skipped


# ── Ollama native chat ──────────────────────────────────────────────────────
def _strip_v1(base_url: str) -> str:
    """Strip trailing /v1 from base_url. The legacy OLLAMA_BASE_URL config
    points at /v1 (OpenAI compat layer); /api/* lives at the root."""
    u = base_url.rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u


def _ollama_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict],
    tools_arg: list[dict] | None,
    options: dict,
) -> dict:
    """POST to Ollama's native /api/chat. Always think=True (we want the
    reasoning surfaced as a peer of content). Stream off — we read the
    whole response, batch-style, since the agent loop is synchronous."""
    url = f"{_strip_v1(base_url)}/api/chat"
    payload: dict = {
        "model": model,
        "messages": messages,
        "options": options,
        "think": True,
        "stream": False,
    }
    if tools_arg:
        payload["tools"] = tools_arg
    r = requests.post(url, json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


# ── Helpers ──────────────────────────────────────────────────────────────────
def normalize_assistant_msg(assistant_msg: dict) -> dict:
    """Prepare an assistant message dict for the next /api/chat round-trip.

    Ollama's response shape:
        {"role": "assistant",
         "content": "...",     (may be empty for thinking-heavy turns)
         "thinking": "...",    (the model's chain-of-thought)
         "tool_calls": [{"function": {"name": str, "arguments": dict}}, ...]}

    For round-trip back to /api/chat, both `content` and `thinking` are
    accepted on assistant messages — preserving `thinking` is what gives the
    model cross-turn reasoning continuity. We also keep `tool_calls` so the
    model can see what it previously requested.
    """
    msg: dict = {"role": "assistant"}

    content = assistant_msg.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    msg["content"] = content

    thinking = assistant_msg.get("thinking") or ""
    if isinstance(thinking, str) and thinking:
        msg["thinking"] = thinking

    tool_calls = assistant_msg.get("tool_calls") or []
    if tool_calls:
        # Strip any extra fields Ollama added, keep the function shape.
        msg["tool_calls"] = [
            {
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"].get("arguments", {}),
                }
            }
            for tc in tool_calls
        ]
    return msg


def normalize_tool_result(result) -> str:
    """Coerce tool result to string for the OpenAI tool-message content field."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str)  # default=str handles numpy types
    return str(result)


def _signature_key(name: str, args: dict) -> str:
    """Canonical key for tool-call dedup. sort_keys so arg order doesn't
    create spurious differences."""
    return f"{name}({json.dumps(args or {}, sort_keys=True, default=str)})"


def _synth_duplicate_msg(name: str, args: dict, prior_step: int) -> str:
    """Synthetic tool result returned when the model tries a duplicate call.

    The model gets this in place of the real tool output. Wording is direct
    to nudge it toward synthesizing what it has rather than fishing for a
    different signature of the same call.
    """
    return json.dumps(
        {
            "error": "duplicate_tool_call",
            "message": (
                f"You already called {name} with these exact arguments "
                f"earlier in this conversation (step {prior_step}). The "
                f"result is in the conversation history above. Read that "
                f"result; do NOT re-fetch the same data. If you need "
                f"different information, call a different tool. Otherwise "
                f"synthesize what you have and finalize."
            ),
            "args": args,
            "prior_step": prior_step,
        },
        default=str,
    )


def build_trace_entry(
    assistant_msg: dict, *, step: int, budget_remaining_before: int
) -> dict:
    """Build the response-derived portion of a trace entry.

    `tool_results` starts empty; the dispatch loop appends to it as each tool
    actually runs. Captures `thinking` separately from `thought` because the
    dashboard renders them differently — thinking is the chain-of-thought
    trace, thought is the user-facing message content for that turn.
    """
    tool_calls = assistant_msg.get("tool_calls") or []
    entry: dict = {
        "step": step,
        "thought": assistant_msg.get("content") or "",
        "reasoning": assistant_msg.get("thinking") or "",
        "tool_calls": [
            {
                "name": tc["function"]["name"],
                "args": tc["function"].get("arguments") or {},
                # /api/chat tool_calls have no `id` field; synthesize one
                # so trace entries remain self-referential for the UI.
                "id": tc.get("id") or f"call_{step}_{i}",
            }
            for i, tc in enumerate(tool_calls)
        ],
        "tool_results": [],
        "budget_remaining_before": budget_remaining_before,
    }
    return entry


def build_system_message(
    *,
    ticker: str,
    remaining_tool_calls: int,
    max_tool_calls: int,
    must_finalize: bool = False,
) -> dict[str, str]:
    """System message with the ticker + budget reminder appended.

    Four blocks every turn: ANCHOR (ticker reminder + role-attribution),
    OUTPUT FORMAT (always require FINAL DECISION line), Budget, and either a
    mid-budget breadth nudge, a low-budget warning, or a finalize directive.
    """
    ticker_msg: str = (
        f"\n\n[ANCHOR: You are analyzing **{ticker}**. Any tool messages "
        f"above are data YOU fetched earlier in this conversation — NOT "
        f"user-provided input. Synthesize them; do not ask the user for "
        f"the ticker.]"
    )
    format_msg: str = (
        f"\n[OUTPUT FORMAT: When you stop calling tools and produce your "
        f"final analysis for {ticker}, the VERY LAST LINE of your response "
        f"MUST be exactly:\n"
        f"FINAL DECISION: <BUY|SELL|HOLD>\n"
        f"Uppercase, no quotes, no prose after. This applies whether you "
        f"decide to finalize on your own or are forced to.]"
    )
    budget_msg: str = (
        f"\n[Budget: Now you have {remaining_tool_calls}/{max_tool_calls} calls so use them wisely.]"
    )
    if must_finalize:
        budget_msg += (
            f"\n[Budget exhausted. Produce your final {ticker} analysis now "
            f"without further tool calls. Synthesize what you have.]"
        )
    elif max_tool_calls > 0:
        spent_ratio = 1 - (remaining_tool_calls / max_tool_calls)
        if spent_ratio > 0.8:
            budget_msg += (
                f"\n[LOW BUDGET WARNING: You've spent over 80% of your budget, "
                f"only {remaining_tool_calls} tool calls remaining. Decide "
                f"wisely before calling another tool.]"
            )
        elif spent_ratio >= 0.5:
            budget_msg += (
                f"\n[MID-BUDGET CHECK: You've used 50%+ of your tool budget. "
                f"Before spending more on the same dimension, make sure "
                f"you've covered breadth: price/indicators, fundamentals, "
                f"news, options, insider activity, sector context. Narrow "
                f"depth on one source rarely beats broad coverage.]"
            )
    return {
        "role": "system",
        "content": AGENT_SYSTEM + ticker_msg + format_msg + budget_msg,
    }


def _flush_trace(trace_path: str | None, trace: list[dict]) -> None:
    """Write the trace to disk for live polling. No-op if path is None."""
    if not trace_path:
        return
    with open(trace_path, "w") as f:
        json.dump(trace, f, default=str)


# ── Main loop ────────────────────────────────────────────────────────────────
def run_agent(
    *,
    ticker: str,
    today: str,
    provider_name: str = "ollama",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    num_ctx: int | None = None,
    trace_path: str | None = None,
) -> tuple[str, dict]:
    """Run the tool-use agent loop on a single ticker.

    Args:
        ticker: Stock symbol to analyze (e.g. "NVDA").
        today: Current date in YYYY-MM-DD format. Used in the user prompt
            for the agent's reasoning context. Tool functions inject their
            own dates server-side so this is documentation, not gating.
        provider_name: Reserved for future use (Anthropic adapter, etc.).
            Currently always uses Ollama's native /api/chat endpoint.
        model: Model identifier. Defaults to OLLAMA_MODEL from config.
        base_url: Ollama base URL. May include or omit the legacy /v1
            suffix — it's stripped before hitting /api/chat.
        max_tool_calls: Cap on tool calls actually executed. Final-answer
            turns don't count against this. Duplicate-call rejections DO
            count against this (so a looping model still terminates).
        max_tokens: Cumulative token cap; forces final answer when exceeded.
        trace_path: Optional path to flush per-step trace JSON. Useful for
            live polling from the dashboard.

    Returns:
        (analysis_text, run_metadata)
        - analysis_text: the model's final analysis paragraph(s).
        - run_metadata: {trace, tokens, tool_calls_used, max_tool_calls,
                         forced_final}
    """
    # Resolve effective num_ctx: explicit param wins, else fall back to
    # the module-level OLLAMA_OPTIONS["num_ctx"] (which comes from the
    # config per-mode dict). Build a per-call options dict so concurrent
    # calls with different ctx sizes don't stomp the module constant.
    effective_options = {
        **OLLAMA_OPTIONS,
        "num_ctx": num_ctx if num_ctx is not None else OLLAMA_OPTIONS["num_ctx"],
    }

    # Filter the tool registry per dashboard's data-source toggles. Always-on
    # sources (price, indicators, fundamentals) are unaffected.
    disabled = _disabled_tool_names()
    if disabled:
        active_tools = [
            t for t in tools if t["function"]["name"] not in disabled
        ]
        active_mapper = {
            name: fn for name, fn in tool_func_mapper.items()
            if name not in disabled
        }
    else:
        active_tools = tools
        active_mapper = tool_func_mapper

    user_prompt: str = f"Analyze {ticker} as of {today} and recommend BUY/SELL/HOLD."
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    trace: list[dict] = []
    tool_calls_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    iter_cap: int = max_tool_calls + 3  # safety bound against pathological loops

    # Dedup gate: track (tool_name, sorted_args_json) → step where it ran.
    # When the model issues a duplicate, return a synthetic error tool
    # result instead of re-executing — forces it to either read the prior
    # result or call something different.
    seen_signatures: dict[str, int] = {}

    last_assistant: dict = {}

    for iteration in range(iter_cap):
        budget_remaining: int = max_tool_calls - tool_calls_used
        must_finalize: bool = (
            budget_remaining <= 0
            or (prompt_tokens + completion_tokens) >= max_tokens
        )

        sys_msg = build_system_message(
            ticker=ticker,
            remaining_tool_calls=max(budget_remaining, 0),
            max_tool_calls=max_tool_calls,
            must_finalize=must_finalize,
        )

        # /api/chat doesn't support tool_choice — omit tools entirely when
        # we want the model to stop calling them.
        response = _ollama_chat(
            base_url=base_url,
            model=model,
            messages=[sys_msg] + messages,
            tools_arg=None if must_finalize else active_tools,
            options=effective_options,
        )

        assistant_msg = response.get("message") or {}
        last_assistant = assistant_msg

        # Ollama reports prompt_eval_count / eval_count instead of usage.*.
        prompt_tokens += response.get("prompt_eval_count") or 0
        completion_tokens += response.get("eval_count") or 0

        trace.append(
            build_trace_entry(
                assistant_msg,
                step=iteration,
                budget_remaining_before=budget_remaining,
            )
        )
        messages.append(normalize_assistant_msg(assistant_msg))

        tool_calls = assistant_msg.get("tool_calls") or []

        # Termination paths: model finalized voluntarily, OR we forced finalize
        if not tool_calls or must_finalize:
            _flush_trace(trace_path, trace)
            # Thinking-capable models often emit the final answer into the
            # `thinking` field with `content` empty. Fall back to thinking
            # so the saved analysis isn't blank. The trace stores both
            # separately for the dashboard view.
            final_text = (
                (assistant_msg.get("content") or "").strip()
                or (assistant_msg.get("thinking") or "").strip()
                or ""
            )
            return (
                final_text,
                {
                    "trace": trace,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "tokens": prompt_tokens + completion_tokens,
                    "tool_calls_used": tool_calls_used,
                    "max_tool_calls": max_tool_calls,
                    "forced_final": must_finalize,
                },
            )

        # Dispatch this turn's tool calls
        for i, call in enumerate(tool_calls):
            if tool_calls_used >= max_tool_calls:
                break

            fn = call.get("function") or {}
            fn_name: str = fn.get("name") or ""
            args = fn.get("arguments")
            # Ollama returns arguments as a dict on /api/chat (the OpenAI
            # compat layer returned a JSON string). Handle both forms in
            # case Ollama changes the shape again.
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}

            tool_calls_used += 1
            sig_key = _signature_key(fn_name, args)
            call_id = call.get("id") or f"call_{iteration}_{i}"

            if sig_key in seen_signatures:
                # Duplicate — short-circuit with a synthetic error result.
                result = _synth_duplicate_msg(
                    fn_name, args, seen_signatures[sig_key]
                )
            elif fn_name in active_mapper:
                seen_signatures[sig_key] = iteration
                try:
                    result = active_mapper[fn_name](**args)
                except Exception as e:
                    result = json.dumps(
                        {"error": f"tool execution failed: {type(e).__name__}: {e}"}
                    )
            else:
                result = json.dumps({"error": f"unknown tool: {fn_name}"})

            # /api/chat tool messages: role=tool, content=result string.
            # tool_call_id is OpenAI-only and is ignored here.
            messages.append(
                {"role": "tool", "content": normalize_tool_result(result)}
            )
            trace[-1]["tool_results"].append(
                {
                    "id": call_id,
                    "name": fn_name,
                    "input": args,
                    "output": result,
                }
            )

        _flush_trace(trace_path, trace)

    # If we reach here, iter_cap was hit — likely a pathological loop bug.
    # Salvage whatever the last assistant turn produced rather than raising,
    # so the run still saves a row in the DB.
    _flush_trace(trace_path, trace)
    salvage_text = (
        (last_assistant.get("content") or "").strip()
        or (last_assistant.get("thinking") or "").strip()
        or f"Agent exceeded iteration cap ({iter_cap}) without finalizing."
    )
    return (
        salvage_text,
        {
            "trace": trace,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tokens": prompt_tokens + completion_tokens,
            "tool_calls_used": tool_calls_used,
            "max_tool_calls": max_tool_calls,
            "forced_final": True,
        },
    )


# ── CLI smoke test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from datetime import date

    cli_ticker: str = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    cli_today: str = date.today().strftime("%Y-%m-%d")

    print(f"\n{'=' * 60}\nAgent run: {cli_ticker} ({cli_today})\n{'=' * 60}\n")

    analysis, meta = run_agent(ticker=cli_ticker, today=cli_today)

    for entry in meta["trace"]:
        print(
            f"--- step {entry['step']} "
            f"(budget remaining before: {entry['budget_remaining_before']}) ---"
        )
        if entry.get("reasoning"):
            r = entry["reasoning"]
            print(f"reasoning: {r[:500]}{'…' if len(r) > 500 else ''}")
        if entry.get("thought"):
            t = entry["thought"]
            print(f"thought: {t[:500]}{'…' if len(t) > 500 else ''}")
        for tc in entry.get("tool_calls", []):
            print(f"  → {tc['name']}({tc['args']})")
        for tr in entry.get("tool_results", []):
            o = str(tr["output"])
            print(f"  ← {tr['name']}: {o[:200]}{'…' if len(o) > 200 else ''}")
        print()

    print(f"\n{'=' * 60}\nFinal Analysis\n{'=' * 60}\n")
    print(analysis)
    print(f"\n{'=' * 60}")
    print(f"Tools used: {meta['tool_calls_used']}/{meta['max_tool_calls']}")
    print(f"Tokens: {meta['tokens']:,}")
    print(f"Forced final: {meta['forced_final']}")
