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
    log_request,
)
from prompts import (
    SIMPLE_SYSTEM, SIMPLE_USER,
    EARNINGS_SECTION_TEMPLATE, EARNINGS_NONE,
    INSIDER_SECTION_TEMPLATE, INSIDER_NONE,
    OPTIONS_SECTION_TEMPLATE, OPTIONS_NONE,
    SECTOR_SECTION_TEMPLATE, SECTOR_NONE,
    PRICE_CONTEXT_TEMPLATE,
    ADVOCATE_SYSTEM, ADVOCATE_USER,
    SYNTHESIS_SYSTEM, SYNTHESIS_USER,
)

# ── CONTEXT BUILDER (shared by all modes) ─────────────────────────────────────
def fetch_context(ticker, today):
    from tradingagents.dataflows.interface import route_to_vendor
    sections = []

    try:
        from prices import get_price_context
        price_text = get_price_context(ticker)
        sections.append(PRICE_CONTEXT_TEMPLATE.format(summary=price_text))
    except Exception as e:
        sections.append(f"## Price Data\nUnavailable: {e}")

    try:
        from news import days_until_earnings, get_earnings_calendar_finnhub
        days = days_until_earnings(ticker)
        if days is not None:
            event = get_earnings_calendar_finnhub(ticker)
            est = event.get("epsEstimate") if event else None
            rev_est = event.get("revenueEstimate") if event else None
            warning = " ⚠️ IMMINENT" if days <= 3 else (" (within 1 week)" if days <= 7 else "")
            sections.append(EARNINGS_SECTION_TEMPLATE.format(
                warning=warning, days=days,
                date=event.get("date", "unknown"),
                eps_est=est, rev_est=rev_est,
            ))
        else:
            sections.append(EARNINGS_NONE)
    except Exception as e:
        sections.append(f"## Upcoming Earnings\nUnavailable: {e}")

    try:
        from news import insider_summary_text
        insider = insider_summary_text(ticker)
        if insider:
            sections.append(INSIDER_SECTION_TEMPLATE.format(summary=insider))
        else:
            sections.append(INSIDER_NONE)
    except Exception as e:
        sections.append(f"## Insider Activity\nUnavailable: {e}")

    try:
        from options import options_summary_text
        opts = options_summary_text(ticker)
        if opts:
            sections.append(OPTIONS_SECTION_TEMPLATE.format(summary=opts))
        else:
            sections.append(OPTIONS_NONE)
    except Exception as e:
        sections.append(f"## Options Activity\nUnavailable: {e}")

    try:
        from sector import sector_summary_text
        sector_text = sector_summary_text(ticker)
        if sector_text:
            sections.append(SECTOR_SECTION_TEMPLATE.format(summary=sector_text))
        else:
            sections.append(SECTOR_NONE)
    except Exception as e:
        sections.append(f"## Sector & Macro Context\nUnavailable: {e}")

    for indicator in ["macd", "rsi", "close_50_sma", "close_10_ema"]:
        try:
            ind = route_to_vendor("get_indicators", ticker, indicator, today, 30)
            sections.append(f"## {indicator.upper()}\n{ind}")
        except Exception as e:
            sections.append(f"## {indicator.upper()}\nUnavailable: {e}")

    try:
        fundamentals = route_to_vendor("get_fundamentals", ticker)
        sections.append(f"## Fundamentals\n{fundamentals}")
    except Exception as e:
        sections.append(f"## Fundamentals\nUnavailable: {e}")

    try:
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        news = route_to_vendor("get_news", ticker, start, today)
        sections.append(f"## Recent News\n{news}")
    except Exception as e:
        sections.append(f"## Recent News\nUnavailable: {e}")

    return "\n\n".join(sections)


def extract_decision(text):
    for line in reversed(text.splitlines()):
        if "FINAL DECISION:" in line.upper():
            decision = line.split(":")[-1].strip()
            decision = decision.replace("**", "").replace("*", "").replace("_", "").strip()
            return decision
    return "UNKNOWN"


def _make_llm(provider):
    """Build an LLM client for the given provider."""
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0.3)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, api_key="ollama", temperature=0.3)


def _normalize_content(content):
    """Some providers return a list of parts; flatten to a single string."""
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content


# ── SOLO MODE (single LLM call) ──────────────────────────────────────────────
def run_solo(ticker, today, provider, model):
    from langchain_core.messages import SystemMessage, HumanMessage

    llm = _make_llm(provider)
    context = fetch_context(ticker, today)

    log_request(provider)
    response = llm.invoke([
        SystemMessage(content=SIMPLE_SYSTEM),
        HumanMessage(content=SIMPLE_USER.format(ticker=ticker, today=today, context=context))
    ])
    analysis = _normalize_content(response.content)
    return analysis, extract_decision(analysis), None  # third value: extra payload (none for solo)


# ── CORE MODE (3-call adversarial pipeline) ──────────────────────────────────
def run_core(ticker, today, provider, model):
    from langchain_core.messages import SystemMessage, HumanMessage

    llm = _make_llm(provider)
    context = fetch_context(ticker, today)

    # Call 1: Initial analyst
    log_request(provider)
    initial_resp = llm.invoke([
        SystemMessage(content=SIMPLE_SYSTEM),
        HumanMessage(content=SIMPLE_USER.format(ticker=ticker, today=today, context=context))
    ])
    initial_analysis = _normalize_content(initial_resp.content)
    initial_decision = extract_decision(initial_analysis)

    # Call 2: Devil's advocate
    log_request(provider)
    advocate_resp = llm.invoke([
        SystemMessage(content=ADVOCATE_SYSTEM),
        HumanMessage(content=ADVOCATE_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis,
            context=context,
        ))
    ])
    advocate_analysis = _normalize_content(advocate_resp.content)

    # Call 3: Synthesizer
    log_request(provider)
    synthesis_resp = llm.invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM),
        HumanMessage(content=SYNTHESIS_USER.format(
            ticker=ticker, today=today,
            initial_analysis=initial_analysis,
            advocate_analysis=advocate_analysis,
            context=context,
        ))
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


# ── FULL MODE (TradingAgents 7-agent graph) ──────────────────────────────────
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

    config = DEFAULT_CONFIG.copy()
    if provider == "gemini":
        config["llm_provider"] = "google"
        config["backend_url"] = None
    else:
        config["llm_provider"] = "ollama"
    config["deep_think_llm"] = model
    config["quick_think_llm"] = model
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    ta = TradingAgentsGraph(debug=True, config=config)
    state, decision = ta.propagate(ticker, today)
    analysis = "\n\n".join([
        msg.content for msg in state["messages"]
        if hasattr(msg, "content") and len(msg.content) > 100
    ])
    return analysis, decision, None


# ── MAIN ──────────────────────────────────────────────────────────────────────
def _resolve_mode():
    """CLI mode selection. Default: core. Flags: --solo, --full."""
    if "--full" in sys.argv:
        return "full"
    if "--solo" in sys.argv:
        return "solo"
    return "core"


def _resolve_runner(mode):
    return {
        "solo": run_solo,
        "core": run_core,
        "full": run_full,
    }[mode]


def main():
    init_db()

    PROVIDER = get_provider()
    MODEL = get_model(PROVIDER)
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

                save_run(ticker, today, decision, analysis,
                         cb.prompt_tokens, cb.completion_tokens,
                         mode=MODE, runtime_seconds=runtime,
                         model=MODEL, host=host, extra=extra)

                print(f"\n{ticker} FINAL DECISION: {decision}")
                print(f"Runtime: {runtime}s | Tokens: {cb.total_tokens:,}")
                print(f"Cost if Sonnet 4.6: ${cb.prompt_tokens/1e6*3 + cb.completion_tokens/1e6*15:.4f}")
        except Exception as e:
            print(f"ERROR analyzing {ticker}: {e}")

    set_status("idle")


if __name__ == "__main__":
    main()