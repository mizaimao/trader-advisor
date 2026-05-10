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


def extract_decision(text):
    for line in reversed(text.splitlines()):
        if "FINAL DECISION:" in line.upper():
            decision = line.split(":")[-1].strip()
            return decision.replace("**", "").replace("*", "").replace("_", "").strip()
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

    # Default: Ollama (or compatible local OpenAI-API server)
    from langchain_openai import ChatOpenAI
    base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    kwargs = {
        "model": model or OLLAMA_MODEL,
        "base_url": base_url,
        "api_key": "ollama",
        "temperature": 0.3,
    }
    num_ctx = OLLAMA_NUM_CTX_BY_MODE.get(mode) if mode else None
    if num_ctx is not None:
        # Ollama's OpenAI-compat layer accepts a non-standard `options` field
        # alongside the standard request body; that's how non-OpenAI engine
        # params (num_ctx, num_predict, repeat_penalty, etc.) get plumbed
        # through. langchain's ChatOpenAI exposes this via `extra_body`.
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}
    return ChatOpenAI(**kwargs)


def _normalize_content(content):
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content


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
    analysis = _normalize_content(response.content)
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
    initial_analysis = _normalize_content(initial_resp.content)
    initial_decision = extract_decision(initial_analysis)

    log_request(provider)
    advocate_resp = llm.invoke([
        SystemMessage(content=ADVOCATE_SYSTEM),
        HumanMessage(content=ADVOCATE_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis, context=context,
        )),
    ])
    advocate_analysis = _normalize_content(advocate_resp.content)

    log_request(provider)
    synthesis_resp = llm.invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM),
        HumanMessage(content=SYNTHESIS_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis,
            advocate_analysis=advocate_analysis, context=context,
        )),
    ])
    synthesis_analysis = _normalize_content(synthesis_resp.content)
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
