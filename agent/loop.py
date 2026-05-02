"""Tool-use agent loop. Promoted from agent/scratch.py.

Public API:
    from agent import run_agent
    text, meta = run_agent(ticker="NVDA", today="2026-05-02")

Behavioral parity with scratch.py at promotion time. Provider abstraction
deferred — currently always builds an OpenAI-compatible client against
`base_url` (Ollama by default). The Anthropic adapter slots in later
(Phase 1 Spec, Step 9), at which point this file refactors against an
actual second implementation rather than a speculative interface.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from openai import OpenAI

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


# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_MODEL: str = "gpt-oss:20b"
DEFAULT_MAX_TOOL_CALLS: int = 10
DEFAULT_MAX_TOKENS: int = 50_000
DEFAULT_BASE_URL: str = "http://ml39.local:11434/v1"

# Ollama-specific. temp=0.3 stabilizes tool-arg generation without flattening
# branching choices; default (~0.8) was producing rare ticker hallucinations.
OLLAMA_OPTIONS: dict[str, Any] = {"num_ctx": 32768, "temperature": 0.3}


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
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def normalize_assistant_msg(assistant_msg) -> dict:
    """Convert assistant message to a dict the API accepts on the next call.

    Needed because GPT-OSS sometimes emits content as a dict not string, and
    carries fields (reasoning, refusal, audio, etc.) that break round-trip.
    """
    msg = assistant_msg.model_dump(exclude_unset=True, exclude_none=True)

    content = msg.get("content")
    if content is None:
        msg["content"] = ""
    elif not isinstance(content, str):
        msg["content"] = str(content)

    msg.pop("reasoning", None)
    msg.pop("function_call", None)
    msg.pop("refusal", None)
    msg.pop("annotations", None)
    msg.pop("audio", None)
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


def build_trace_entry(
    assistant_msg, *, step: int, budget_remaining_before: int
) -> dict:
    """Build the response-derived portion of a trace entry.

    `tool_results` starts empty; the dispatch loop appends to it as each tool
    actually runs. Captures `reasoning` separately from `thought` because
    GPT-OSS emits chain-of-thought there while visible answer goes in `content`
    — and `normalize_assistant_msg` strips `reasoning` before round-trip.
    """
    return {
        "step": step,
        "thought": assistant_msg.content or "",
        "reasoning": getattr(assistant_msg, "reasoning", None) or "",
        "tool_calls": [
            {
                "name": call.function.name,
                "args": (
                    json.loads(call.function.arguments)
                    if call.function.arguments
                    else {}
                ),
                "id": call.id,
            }
            for call in (assistant_msg.tool_calls or [])
        ],
        "tool_results": [],
        "budget_remaining_before": budget_remaining_before,
    }


def build_system_message(
    *,
    remaining_tool_calls: int,
    max_tool_calls: int,
    must_finalize: bool = False,
) -> dict[str, str]:
    """System message with the budget reminder appended.

    Three states: normal, low-budget warning (<20% remaining), forced-finalize
    (budget exhausted or token cap hit).
    """
    budget_msg: str = (
        f"[Budget: Now you have {remaining_tool_calls}/{max_tool_calls} calls so use them wisely.]"
    )
    if must_finalize:
        budget_msg += (
            "\n[Budget exhausted. Produce your final analysis now without further "
            "tool calls. End with FINAL DECISION: <BUY|SELL|HOLD>.]"
        )
    elif max_tool_calls > 0 and remaining_tool_calls / max_tool_calls < 0.2:
        budget_msg += (
            f"\n[LOW BUDGET WARNING: You've spent over 80% of your budget, only "
            f"{remaining_tool_calls} tool calls remaining. Decide wisely before "
            f"calling another tool.]"
        )
    return {"role": "system", "content": AGENT_SYSTEM + budget_msg}


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
    trace_path: str | None = None,
) -> tuple[str, dict]:
    """Run the tool-use agent loop on a single ticker.

    Args:
        ticker: Stock symbol to analyze (e.g. "NVDA").
        today: Current date in YYYY-MM-DD format. Used in the user prompt
            for the agent's reasoning context. Tool functions inject their
            own dates server-side so this is documentation, not gating.
        provider_name: Reserved for future use (Anthropic adapter, etc.).
            Currently always builds an OpenAI-compatible client.
        model: Model identifier. Defaults to gpt-oss:20b.
        base_url: OpenAI-compatible endpoint URL. Defaults to the local
            Ollama server on ml39.
        max_tool_calls: Cap on tool calls actually executed. Final-answer
            turns don't count against this.
        max_tokens: Cumulative token cap; forces final answer when exceeded.
        trace_path: Optional path to flush per-step trace JSON. Useful for
            live polling from the dashboard.

    Returns:
        (analysis_text, run_metadata)
        - analysis_text: the model's final analysis paragraph(s).
        - run_metadata: {trace, tokens, tool_calls_used, max_tool_calls,
                         forced_final}
    """
    client = OpenAI(base_url=base_url, api_key="ollama")

    user_prompt: str = f"Analyze {ticker} as of {today} and recommend BUY/SELL/HOLD."
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    trace: list[dict] = []
    tool_calls_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    iter_cap: int = max_tool_calls + 3  # safety bound against pathological loops

    for iteration in range(iter_cap):
        budget_remaining: int = max_tool_calls - tool_calls_used
        must_finalize: bool = (
            budget_remaining <= 0
            or (prompt_tokens + completion_tokens) >= max_tokens
        )

        sys_msg = build_system_message(
            remaining_tool_calls=max(budget_remaining, 0),
            max_tool_calls=max_tool_calls,
            must_finalize=must_finalize,
        )

        response = client.chat.completions.create(
            model=model,
            messages=[sys_msg] + messages,
            tools=tools,
            tool_choice="none" if must_finalize else "auto",
            extra_body={"options": OLLAMA_OPTIONS},
        )
        assistant_msg = response.choices[0].message

        if response.usage:
            prompt_tokens += response.usage.prompt_tokens or 0
            completion_tokens += response.usage.completion_tokens or 0

        trace.append(
            build_trace_entry(
                assistant_msg,
                step=iteration,
                budget_remaining_before=budget_remaining,
            )
        )
        messages.append(normalize_assistant_msg(assistant_msg))

        # Termination paths: model finalized voluntarily, OR we forced finalize
        if not assistant_msg.tool_calls or must_finalize:
            _flush_trace(trace_path, trace)
            return (
                assistant_msg.content or "",
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
        for call in assistant_msg.tool_calls:
            if tool_calls_used >= max_tool_calls:
                break
            tool_calls_used += 1

            args: dict = (
                json.loads(call.function.arguments)
                if call.function.arguments
                else {}
            )
            fn_name: str = call.function.name

            if fn_name in tool_func_mapper:
                try:
                    result = tool_func_mapper[fn_name](**args)
                except Exception as e:
                    result = json.dumps(
                        {"error": f"tool execution failed: {type(e).__name__}: {e}"}
                    )
            else:
                result = json.dumps({"error": f"unknown tool: {fn_name}"})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": normalize_tool_result(result),
                }
            )
            trace[-1]["tool_results"].append(
                {
                    "id": call.id,
                    "name": fn_name,
                    "input": args,
                    "output": result,
                }
            )

        _flush_trace(trace_path, trace)

    # If we reach here, iter_cap was hit — likely a pathological loop bug
    raise RuntimeError(
        f"Agent exceeded iteration cap ({iter_cap}). "
        f"Used {tool_calls_used} of {max_tool_calls} tool calls."
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
