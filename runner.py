import json
import os
import sys
import time
import socket
from datetime import date, datetime, timedelta
from langchain_community.callbacks import get_openai_callback
from db import init_db, save_run, set_status
from config import (
    get_provider, get_model, get_tickers,
    OLLAMA_BASE_URL, OLLAMA_MODEL, GEMINI_MODEL,
    OLLAMA_NUM_CTX_BY_MODE,
    log_request,
)
from prompts import (
    SIMPLE_SYSTEM, SIMPLE_USER,
    EARNINGS_SECTION_TEMPLATE,
    INSIDER_SECTION_TEMPLATE,
    OPTIONS_SECTION_TEMPLATE,
    SECTOR_SECTION_TEMPLATE,
    PRICE_CONTEXT_TEMPLATE,
    ADVOCATE_SYSTEM, ADVOCATE_USER,
    SYNTHESIS_SYSTEM, SYNTHESIS_USER,
    SENTIMENT_SECTION_TEMPLATE,
    REDDIT_SECTION_TEMPLATE,
)
from agent import run_agent as _run_agent_loop


# ── CONTEXT BUILDER (shared by all modes) ─────────────────────────────────────
def _disabled_sources():
    """Read TRADER_ADVISOR_DISABLED_SOURCES (JSON list) from env.

    The dashboard's data-source toggles serialize their off list into this
    env var on subprocess spawn. Honored only for the seven toggleable
    sources — price/indicators/fundamentals are always-on regardless.
    """
    raw = os.getenv("TRADER_ADVISOR_DISABLED_SOURCES", "")
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (ValueError, TypeError):
        print(f"WARN: bad TRADER_ADVISOR_DISABLED_SOURCES={raw!r}; ignoring",
              file=sys.stderr)
        return set()


def fetch_context(ticker, today):
    """Build the context block fed to the LLM.

    Hard-skip semantics: if a source is in the disabled set, its fetch is
    not run at all. If a fetch returns None/empty or raises, the section
    is omitted entirely (no 'Unavailable' filler) so the prompt stays clean.
    Errors are logged to stderr for the operator, not into the prompt.
    """
    disabled = _disabled_sources()
    sections = []

    def add(source_id, builder):
        if source_id in disabled:
            return
        try:
            text = builder()
        except Exception as e:
            print(f"WARN: {source_id} fetch failed for {ticker}: {e}",
                  file=sys.stderr)
            return
        if text:
            sections.append(text)

    def _price():
        from prices import get_price_context
        return PRICE_CONTEXT_TEMPLATE.format(summary=get_price_context(ticker))
    add("price", _price)

    def _earnings():
        from news import days_until_earnings, get_earnings_calendar_finnhub
        days = days_until_earnings(ticker)
        if days is None:
            return None
        event = get_earnings_calendar_finnhub(ticker) or {}
        warning = " ⚠️ IMMINENT" if days <= 3 else (" (within 1 week)" if days <= 7 else "")
        return EARNINGS_SECTION_TEMPLATE.format(
            warning=warning, days=days,
            date=event.get("date", "unknown"),
            eps_est=event.get("epsEstimate"),
            rev_est=event.get("revenueEstimate"),
        )
    add("earnings", _earnings)

    def _insider():
        from news import insider_summary_text
        text = insider_summary_text(ticker)
        return INSIDER_SECTION_TEMPLATE.format(summary=text) if text else None
    add("insider", _insider)

    def _options():
        from options import options_summary_text
        text = options_summary_text(ticker)
        return OPTIONS_SECTION_TEMPLATE.format(summary=text) if text else None
    add("options", _options)

    def _sector():
        from sector import sector_summary_text
        text = sector_summary_text(ticker)
        return SECTOR_SECTION_TEMPLATE.format(summary=text) if text else None
    add("sector", _sector)

    def _stocktwits():
        from sentiment import stocktwits_summary_text
        text = stocktwits_summary_text(ticker)
        return SENTIMENT_SECTION_TEMPLATE.format(summary=text) if text else None
    add("stocktwits", _stocktwits)

    def _reddit():
        from sentiment import reddit_summary_text
        text = reddit_summary_text(ticker)
        return REDDIT_SECTION_TEMPLATE.format(summary=text) if text else None
    add("reddit", _reddit)

    def _indicators():
        from indicators import get_indicator_text
        blocks = []
        for indicator in ["macd", "rsi", "close_50_sma", "close_10_ema"]:
            try:
                blocks.append(
                    f"## {indicator.upper()}\n"
                    f"{get_indicator_text(ticker, indicator, today, days_back=30)}"
                )
            except Exception as e:
                print(f"WARN: indicator {indicator} failed for {ticker}: {e}",
                      file=sys.stderr)
        return "\n\n".join(blocks) if blocks else None
    add("indicators", _indicators)

    def _fundamentals():
        from fundamentals import get_fundamentals_text
        return f"## Fundamentals\n{get_fundamentals_text(ticker)}"
    add("fundamentals", _fundamentals)

    def _news():
        from news import get_news_finnhub
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        return f"## Recent News\n{get_news_finnhub(ticker, start, today)}"
    add("news", _news)

    return "\n\n".join(sections)


_VALID_DECISIONS = {"BUY", "SELL", "HOLD", "OVERWEIGHT", "UNDERWEIGHT"}
# Phrasings the LLMs actually use in practice. "FINAL DECISION:" is what the
# prompt asks for, but models paraphrase to "Bottom Line", "Final Verdict",
# "Recommendation:", etc. Listed in priority order — the first match wins.
_DECISION_PHRASINGS = (
    "FINAL DECISION:",
    "FINAL VERDICT:",
    "FINAL RECOMMENDATION:",
    "RECOMMENDATION:",
    "DECISION:",
    "BOTTOM LINE:",
    "VERDICT:",
)


def _strip_markdown(s: str) -> str:
    return s.replace("**", "").replace("*", "").replace("_", "").replace("`", "").strip()


def _normalize_decision(raw: str) -> str | None:
    """Pull a canonical decision word out of `raw`, or None if not extractable."""
    cleaned = _strip_markdown(raw).rstrip(".,!:;").upper()
    # Sometimes the model writes 'HOLD with tight stops' — take the leading word
    head = cleaned.split()[0] if cleaned else ""
    if head in _VALID_DECISIONS:
        return head
    # Fallback: any of the canonical words appearing anywhere
    for word in _VALID_DECISIONS:
        if word in cleaned.split():
            return word
    return None


def extract_decision(text):
    """Pull a BUY/SELL/HOLD/OVERWEIGHT/UNDERWEIGHT decision from an analysis.

    Strategy:
      1. Look for an explicit phrasing line ("FINAL DECISION: HOLD", "Bottom
         Line: BUY", etc.) scanning bottom-up — the last such line wins,
         since prose summaries often repeat the verdict near the end.
      2. If none found, scan the last ~25 non-empty lines for a standalone
         decision token in bolded/heading form (e.g. `**HOLD.**`,
         `### Bottom Line **BUY**`).
      3. Return "UNKNOWN" if nothing matches.
    """
    if not text:
        return "UNKNOWN"
    lines = text.splitlines()

    # Pass 1: explicit phrasings, bottom-up.
    for line in reversed(lines):
        upper = line.upper()
        for phrase in _DECISION_PHRASINGS:
            if phrase in upper:
                tail = line[upper.index(phrase) + len(phrase):]
                decision = _normalize_decision(tail)
                if decision:
                    return decision

    # Pass 2: trailing-region keyword scan. Look at the last 25 non-empty
    # lines; pick the most recent line that contains exactly one of the
    # canonical tokens after stripping markdown. This handles
    # `**HOLD.**` / `### Bottom Line **BUY**` style endings.
    nonempty = [ln for ln in lines if ln.strip()]
    for line in reversed(nonempty[-25:]):
        cleaned = _strip_markdown(line).rstrip(".,!:;").upper()
        tokens = cleaned.split()
        hits = [t for t in tokens if t in _VALID_DECISIONS]
        if len(hits) == 1:
            return hits[0]

    return "UNKNOWN"


def _make_llm(provider, model=None, mode=None):
    """Build an LLM client for the given provider/model.

    `mode` is the runner mode ("solo", "core", "agent", ...); it's used to
    look up the per-mode Ollama context window from OLLAMA_NUM_CTX_BY_MODE
    and pass it through as a per-request `options.num_ctx`. Without it,
    Ollama falls back to its server-side OLLAMA_CONTEXT_LENGTH (currently
    8K), which silently truncates solo/core prompts.

    API keys are read from environment variables (GOOGLE_API_KEY,
    ANTHROPIC_API_KEY, OPENAI_API_KEY). The dashboard sets these on the
    subprocess env when spawning runner.py — they are NOT mutated in the
    parent Streamlit process.
    """
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model or GEMINI_MODEL, temperature=0.3)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model or "claude-sonnet-4-6", temperature=0.3)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model or "gpt-5-4-turbo", temperature=0.3)

    # Default: Ollama via langchain-ollama (native /api/chat endpoint).
    # We deliberately do NOT use langchain-openai here even though Ollama
    # exposes /v1/chat/completions: that compatibility path silently drops
    # the non-standard `options` field, so per-request num_ctx never reaches
    # the model and prompts get truncated to the server's default ceiling.
    # /api/chat honors `num_ctx` directly. Strip the trailing /v1 from the
    # base URL since ChatOllama hits /api/* not /v1/*.
    from langchain_ollama import ChatOllama
    base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    if base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/")[:-3]
    kwargs = {
        "model": model or OLLAMA_MODEL,
        "base_url": base_url,
        "temperature": 0.3,
        # Thinking-capable models (gemma4 variants, gpt-oss, etc.) emit a
        # separate `thinking` field. For stock analysis, the reasoning IS
        # the analysis — it contains the actual evaluation work, while
        # `content` is just the final verdict. Setting reasoning=True
        # surfaces it as response.additional_kwargs['reasoning_content']
        # so we can save both. _normalize_content concatenates them.
        "reasoning": True,
    }
    # num_ctx semantics: FLOOR, not exact size. If Ollama already has the
    # model loaded with context_length >= our floor, omit num_ctx so the
    # currently-loaded model gets reused (no 30-60s reload). Otherwise
    # send the floor and let Ollama load/reload with that size.
    num_ctx = _resolve_num_ctx()
    if num_ctx is None and mode:
        num_ctx = OLLAMA_NUM_CTX_BY_MODE.get(mode)
    if num_ctx is not None:
        from agent.loop import _loaded_context_for
        loaded_ctx = _loaded_context_for(base_url, kwargs["model"])
        if loaded_ctx is None or loaded_ctx < num_ctx:
            kwargs["num_ctx"] = num_ctx
        # else: model is already loaded with enough context — skip num_ctx
    return ChatOllama(**kwargs)


def _normalize_content(response_or_content):
    """Coerce a langchain message (or its `.content`) to an analysis string.

    For thinking-capable models the reasoning trace lives in
    `response.additional_kwargs['reasoning_content']` — a sibling field to
    `.content`. Both are saved: reasoning first (the analysis trace),
    then content (the final verdict). Order matters: extract_decision
    scans bottom-up, so the FINAL DECISION line in `content` is the first
    thing it finds. If only one of the two fields is populated, return
    that one alone (no separator clutter).
    """
    # Caller may pass either an AIMessage-like object or a raw content value.
    if hasattr(response_or_content, "content"):
        raw_content = response_or_content.content
        reasoning = (
            response_or_content.additional_kwargs or {}
        ).get("reasoning_content") or ""
    else:
        raw_content = response_or_content
        reasoning = ""

    if isinstance(raw_content, list):
        content = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw_content
        )
    else:
        content = raw_content or ""

    reasoning = (reasoning or "").strip()
    content = (content or "").strip()

    if reasoning and content:
        return f"## Reasoning\n\n{reasoning}\n\n---\n\n## Final Analysis\n\n{content}"
    return reasoning or content


# ── SOLO ──────────────────────────────────────────────────────────────────────
def run_solo(ticker, today, provider, model):
    from langchain_core.messages import SystemMessage, HumanMessage
    llm = _make_llm(provider, model, mode="solo")
    context = fetch_context(ticker, today)

    log_request(provider)
    response = llm.invoke([
        SystemMessage(content=SIMPLE_SYSTEM),
        HumanMessage(content=SIMPLE_USER.format(ticker=ticker, today=today, context=context)),
    ])
    analysis = _normalize_content(response)
    return analysis, extract_decision(analysis), None


# ── CORE ──────────────────────────────────────────────────────────────────────
def run_core(ticker, today, provider, model):
    from langchain_core.messages import SystemMessage, HumanMessage
    llm = _make_llm(provider, model, mode="core")
    context = fetch_context(ticker, today)

    log_request(provider)
    initial_resp = llm.invoke([
        SystemMessage(content=SIMPLE_SYSTEM),
        HumanMessage(content=SIMPLE_USER.format(ticker=ticker, today=today, context=context)),
    ])
    initial_analysis = _normalize_content(initial_resp)
    initial_decision = extract_decision(initial_analysis)

    log_request(provider)
    advocate_resp = llm.invoke([
        SystemMessage(content=ADVOCATE_SYSTEM),
        HumanMessage(content=ADVOCATE_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis, context=context,
        )),
    ])
    advocate_analysis = _normalize_content(advocate_resp)

    log_request(provider)
    synthesis_resp = llm.invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM),
        HumanMessage(content=SYNTHESIS_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis,
            advocate_analysis=advocate_analysis, context=context,
        )),
    ])
    synthesis_analysis = _normalize_content(synthesis_resp)
    synthesis_decision = extract_decision(synthesis_analysis)

    extra = {
        "initial_analysis": initial_analysis,
        "initial_decision": initial_decision,
        "advocate_analysis": advocate_analysis,
        "synthesis_analysis": synthesis_analysis,
        "synthesis_decision": synthesis_decision,
    }
    return synthesis_analysis, synthesis_decision, extra


# ── FULL ──────────────────────────────────────────────────────────────────────
FULL_ANALYSTS = ["market", "social", "news", "fundamentals"]


def _resolve_analysts():
    """Read --analysts a,b,c,d CLI arg, or None to use TradingAgents' default
    (all 4: market, social, news, fundamentals). Unknown names are dropped
    silently; an empty list falls back to the default to avoid a hard error
    deep inside graph setup."""
    if "--analysts" not in sys.argv:
        return None
    idx = sys.argv.index("--analysts")
    try:
        raw = sys.argv[idx + 1]
    except IndexError:
        return None
    picked = [a.strip() for a in raw.split(",") if a.strip() in FULL_ANALYSTS]
    return picked or None


def run_full(ticker, today, provider, model):
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG
    except ImportError:
        raise RuntimeError(
            "Full mode requires the TradingAgents package, which is not installed.\n"
            "Install it with:\n"
            "  pip install git+https://github.com/TauricResearch/TradingAgents.git\n"
            "Or use --solo or core (default) mode instead."
        )

    # Map our provider name → TradingAgents' llm_provider string.
    # Native-SDK providers (anthropic, google) ignore backend_url; OpenAI-compat
    # ones (openai, ollama) use it as the base URL for the chat client.
    ta_provider = {
        "gemini": "google",
        "anthropic": "anthropic",
        "openai": "openai",
        "ollama": "ollama",
    }.get(provider, "ollama")

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = ta_provider
    if ta_provider in ("google", "anthropic"):
        config["backend_url"] = None
    elif ta_provider == "ollama":
        config["backend_url"] = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    # openai: leave DEFAULT_CONFIG's backend_url alone (api.openai.com)
    config["deep_think_llm"] = model
    config["quick_think_llm"] = model
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    analysts = _resolve_analysts()
    ta_kwargs = {"debug": True, "config": config}
    if analysts:
        ta_kwargs["selected_analysts"] = analysts
    ta = TradingAgentsGraph(**ta_kwargs)
    state, decision = ta.propagate(ticker, today)
    analysis = "\n\n".join([
        msg.content for msg in state["messages"]
        if hasattr(msg, "content") and len(msg.content) > 100
    ])
    return analysis, decision, None


# ── AGENT ─────────────────────────────────────────────────────────────────────
def _resolve_max_tool_calls():
    """Read --max-tool-calls CLI arg, or None to use agent.loop's default."""
    if "--max-tool-calls" in sys.argv:
        idx = sys.argv.index("--max-tool-calls")
        try:
            return int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            return None
    return None


def _resolve_max_tokens():
    """Read --max-tokens CLI arg, or None to use agent.loop's default."""
    if "--max-tokens" in sys.argv:
        idx = sys.argv.index("--max-tokens")
        try:
            return int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            return None
    return None


def _resolve_num_ctx():
    """Read --num-ctx CLI arg, or None to use the per-mode default.

    When the bot fires a run, it picks a num_ctx that matches Ollama's
    natural context for that model (e.g. 256K for qwen3.5:122b) so the
    server doesn't reload. CLI users can also pass this directly.
    """
    if "--num-ctx" in sys.argv:
        idx = sys.argv.index("--num-ctx")
        try:
            return int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            return None
    return None


def run_agent(ticker, today, provider, model):
    """Adapter from agent.loop.run_agent (2-tuple) to the runner's 3-tuple shape.

    Provider is currently ignored — agent mode always uses the OpenAI-compatible
    Ollama client per Phase 1 spec. Anthropic adapter slots in at Step 9.
    """
    kwargs = {"ticker": ticker, "today": today, "model": model}
    max_tc = _resolve_max_tool_calls()
    if max_tc is not None:
        kwargs["max_tool_calls"] = max_tc
    max_tk = _resolve_max_tokens()
    if max_tk is not None:
        kwargs["max_tokens"] = max_tk
    num_ctx = _resolve_num_ctx()
    if num_ctx is not None:
        kwargs["num_ctx"] = num_ctx
    analysis, meta = _run_agent_loop(**kwargs)
    decision = extract_decision(analysis)
    # Token totals are inside meta because langchain's get_openai_callback
    # doesn't capture the raw openai client agent.loop uses. main() reads them
    # from extra when MODE == 'agent'.
    return analysis, decision, meta


# ── MAIN ──────────────────────────────────────────────────────────────────────
def _resolve_mode():
    if "--full" in sys.argv:
        return "full"
    if "--solo" in sys.argv:
        return "solo"
    if "--agent" in sys.argv:
        return "agent"
    return "core"


def _resolve_runner(mode):
    return {
        "solo": run_solo,
        "core": run_core,
        "full": run_full,
        "agent": run_agent,
    }[mode]


def _resolve_model():
    """Read --model CLI arg if present, otherwise None (resolves per-provider default)."""
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        return sys.argv[idx + 1]
    return None


def main():
    init_db()

    PROVIDER = get_provider()
    MODEL = _resolve_model() or get_model(PROVIDER)
    TICKERS = get_tickers()
    MODE = _resolve_mode()
    ANALYZE = _resolve_runner(MODE)

    today = date.today().strftime("%Y-%m-%d")
    host = socket.gethostname()

    print(f"Mode: {MODE} | Provider: {PROVIDER} | Model: {MODEL}")
    print(f"Tickers: {', '.join(TICKERS)}")

    set_status("running", tickers=TICKERS, mode=MODE, pid=os.getpid())

    for i, ticker in enumerate(TICKERS):
        set_status("running", tickers=TICKERS, current=ticker, mode=MODE, completed=i, pid=os.getpid())
        print(f"\n{'='*50}\nAnalyzing {ticker} [{MODE.upper()} MODE]...\n{'='*50}")
        t_start = time.time()
        try:
            with get_openai_callback() as cb:
                analysis, decision, extra = ANALYZE(ticker, today, PROVIDER, MODEL)
                runtime = round(time.time() - t_start, 1)

                # Agent mode bypasses langchain (raw openai client), so cb is
                # empty — pull token counts from extra. Other modes use cb.
                if MODE == "agent" and isinstance(extra, dict):
                    p_tokens = extra.get("prompt_tokens", 0)
                    c_tokens = extra.get("completion_tokens", 0)
                else:
                    p_tokens = cb.prompt_tokens
                    c_tokens = cb.completion_tokens
                total_tokens = p_tokens + c_tokens

                save_run(ticker, today, decision, analysis,
                         p_tokens, c_tokens,
                         mode=MODE, runtime_seconds=runtime,
                         model=MODEL, host=host, extra=extra)

                print(f"\n{ticker} FINAL DECISION: {decision}")
                print(f"Runtime: {runtime}s | Tokens: {total_tokens:,}")
                print(f"Cost if Sonnet 4.6: ${p_tokens/1e6*3 + c_tokens/1e6*15:.4f}")
        except Exception as e:
            err_msg = str(e)
            # Surface key/auth errors more clearly
            if "401" in err_msg or "API_KEY" in err_msg.upper() or "authentication" in err_msg.lower():
                print(f"ERROR: Invalid API key for {PROVIDER}. {err_msg[:200]}")
            else:
                print(f"ERROR analyzing {ticker}: {err_msg}")

    set_status("idle")


if __name__ == "__main__":
    main()
