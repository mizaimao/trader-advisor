"""
Telegram bot for the trading dashboard.

Long-polling architecture (no webhooks needed). Runs as a separate process
alongside dashboard.py. Talks to trading.db directly for read operations,
spawns runner.py via subprocess for analysis triggers.
"""
import os
import sys
import re
import html as _html
import sqlite3
import socket
import subprocess
import asyncio
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, filters,
)

# Project config — model/mode aliases + per-model agent budgets.
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    resolve_model, resolve_mode, get_agent_budget,
    AGENT_BUDGETS_BY_MODEL,
    STUCK_THRESHOLD_SECONDS,
)

# ── CONFIG ───────────────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
PROJECT_ROOT = Path(__file__).parent
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
RUNNER = PROJECT_ROOT / "runner.py"
DB_PATH = os.path.expanduser("~/.tradingagents/trading.db")
TICKERS_FILE = os.path.expanduser("~/.tradingagents/tickers.txt")
TELEGRAM_MSG_LIMIT = 4000  # safe under the 4096 hard cap

# ── HELPERS ──────────────────────────────────────────────────────────────────
def auth_required(func):
    """Decorator: bot only responds to ALLOWED_USER_ID."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id != ALLOWED_USER_ID:
            if update.message:
                await update.message.reply_text("⛔ Unauthorized.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
            return
        return await func(update, ctx)
    return wrapper


def md_to_html(text):
    """Convert the agent's Markdown-ish output to Telegram-safe HTML."""
    if not text:
        return ""
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "")
    return text


def split_message(text, limit=TELEGRAM_MSG_LIMIT):
    """Split a long message into chunks at paragraph boundaries when possible."""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_idx = remaining.rfind("\n\n", 0, limit)
        if split_idx < limit // 2:
            split_idx = remaining.rfind("\n", 0, limit)
        if split_idx < limit // 2:
            split_idx = limit
        chunks.append(remaining[:split_idx].rstrip())
        remaining = remaining[split_idx:].lstrip()
    if remaining:
        chunks.append(remaining)

    total = len(chunks)
    return [f"<i>({i+1}/{total})</i>\n{chunk}" for i, chunk in enumerate(chunks)]


def check_ollama_alive(timeout=2):
    """Returns True if the configured Ollama host:port is reachable.

    Pulls the host from OLLAMA_BASE_URL (which can be either
    http://host:port or http://host:port/v1). Falls back to localhost.
    """
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    parsed = urlparse(base)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


def _ollama_root() -> tuple[str, str, int]:
    """Return (base_root_url, host, port). Strips /v1 since /api/* is at the root."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    parsed = urlparse(base)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    scheme = parsed.scheme or "http"
    return f"{scheme}://{host}:{port}", host, port


def check_server_status(timeout: float = 3.0) -> dict:
    """Probe ml60 (or whichever Ollama host is configured) for:
       - HTTP reachability (latency)
       - Currently loaded models with expires_at
       - Any error encountered

    Returns a dict — never raises. Designed for both the /server command
    and the stuck-run nudge enrichment.
    """
    import time
    import requests as _requests

    base_root, host, port = _ollama_root()
    out: dict = {"host": host, "port": port, "url": base_root}

    t0 = time.monotonic()
    try:
        r = _requests.get(f"{base_root}/api/tags", timeout=timeout)
        latency_ms = int((time.monotonic() - t0) * 1000)
        out["reachable"] = r.ok
        out["latency_ms"] = latency_ms
        if not r.ok:
            out["error"] = f"HTTP {r.status_code}"
    except _requests.exceptions.Timeout:
        out["reachable"] = False
        out["error"] = f"timed out after {timeout}s"
        return out
    except _requests.exceptions.ConnectionError as e:
        out["reachable"] = False
        out["error"] = f"connection refused / host unreachable"
        return out
    except Exception as e:
        out["reachable"] = False
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    if not out.get("reachable"):
        return out

    # /api/ps — currently loaded models
    try:
        r = _requests.get(f"{base_root}/api/ps", timeout=timeout)
        if r.ok:
            data = r.json()
            out["loaded"] = data.get("models", []) or []
        else:
            out["loaded"] = []
    except Exception as e:
        out["loaded"] = []
        out["ps_error"] = str(e)
    return out


def check_runner_proc(pid: int | None) -> dict | None:
    """Read /proc/<pid>/status to classify the runner's wait state.

    Returns None if pid is unknown or the process is gone (proc dir
    missing). Otherwise returns {pid, state_char, state_name} where
    state_char is one of:
        R  running
        S  sleeping (interruptible, usually waiting on socket)
        D  uninterruptible wait (disk I/O, or stuck in kernel)
        T  stopped
        Z  zombie (already exited, waiting for parent to reap)
    """
    if not pid:
        return None
    status_path = f"/proc/{int(pid)}/status"
    if not os.path.exists(status_path):
        return None
    state_char = "?"
    state_name = "unknown"
    try:
        with open(status_path) as f:
            for line in f:
                if line.startswith("State:"):
                    # Format: "State:  S (sleeping)"
                    parts = line.split(None, 2)
                    if len(parts) >= 2:
                        state_char = parts[1]
                    if len(parts) >= 3:
                        state_name = parts[2].strip().strip("()")
                    break
    except OSError:
        return None
    return {"pid": int(pid), "state_char": state_char, "state_name": state_name}


def _fmt_expires_at(iso_str: str | None) -> str:
    """Convert Ollama's expires_at ISO string to a friendly relative duration."""
    if not iso_str:
        return "?"
    try:
        # Ollama returns e.g. "2026-05-12T15:30:00.123-04:00"
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Strip tz so we can subtract naively against datetime.now
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            now = datetime.utcnow()
        else:
            now = datetime.now()
        secs = int((dt - now).total_seconds())
        if secs < 0:
            return "expired"
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        return f"{secs // 3600}h{(secs % 3600) // 60}m"
    except Exception:
        return iso_str[:19]


def _fmt_server_diagnostics(server: dict, proc_info: dict | None, status: dict) -> str:
    """Render the diagnostics for /server and for the stuck-run nudge."""
    lines: list[str] = []
    url = server.get("url", "?")
    lines.append(f"🖥 <b>Server</b>: <code>{url}</code>")

    if server.get("reachable"):
        ms = server.get("latency_ms", "?")
        lines.append(f"  ✓ Reachable ({ms}ms)")
    else:
        err = server.get("error", "unknown error")
        lines.append(f"  ✗ <b>Not reachable</b> — {err}")
        return "\n".join(lines)

    loaded = server.get("loaded", []) or []
    if loaded:
        lines.append("  📦 Loaded models:")
        for m in loaded:
            name = m.get("name", "?")
            size_vram = m.get("size_vram") or 0
            gb = size_vram / (1024 ** 3)
            exp = _fmt_expires_at(m.get("expires_at"))
            lines.append(f"     • <code>{name}</code> — {gb:.1f} GB · expires in {exp}")
    else:
        lines.append("  📦 No models loaded")

    # Active run, if any
    if status.get("status") == "running":
        cur = status.get("current") or "?"
        mode = (status.get("mode") or "?")
        pid = status.get("pid")
        lines.append(
            f"  ⚙ Active run: <b>{cur}</b> · {mode}"
            + (f" · PID {pid}" if pid else "")
        )
        if proc_info:
            lines.append(
                f"     state: <code>{proc_info['state_char']}</code> "
                f"({proc_info['state_name']})"
            )
        elif pid:
            lines.append(f"     (process /proc/{pid} not found — likely just exited)")
    else:
        lines.append("  💤 No active run")
    return "\n".join(lines)


def get_tickers_list():
    if not os.path.exists(TICKERS_FILE):
        return []
    with open(TICKERS_FILE) as f:
        return [line.strip().upper() for line in f if line.strip()]


def save_tickers_list(tickers):
    with open(TICKERS_FILE, "w") as f:
        for t in sorted(set(tickers)):
            f.write(f"{t}\n")


def get_status():
    """Read dashboard status JSON."""
    import json
    status_file = os.path.expanduser("~/.tradingagents/run_status.json")
    if not os.path.exists(status_file):
        return {"status": "idle"}
    try:
        with open(status_file) as f:
            return json.load(f)
    except Exception:
        return {"status": "unknown"}


def get_latest_run(ticker, mode=None):
    """Returns the most recent run row for a ticker as a dict."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if mode:
        row = conn.execute(
            "SELECT * FROM runs WHERE ticker=? AND mode=? ORDER BY id DESC LIMIT 1",
            (ticker, mode),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def fmt_decision(decision):
    """Add an emoji prefix based on decision."""
    d = (decision or "").upper().strip()
    if d in ("BUY", "OVERWEIGHT"):
        return f"🟢 {d}"
    if d in ("SELL", "UNDERWEIGHT"):
        return f"🔴 {d}"
    if d == "HOLD":
        return f"🟡 {d}"
    return f"⚪ {d or 'UNKNOWN'}"


def fmt_agent_trace(row):
    """One-line-per-tool-call summary of an agent run's trace.

    Reads the JSON in `extra.trace`, ignores reasoning/tool_results, and
    renders just the call sequence. Returns None if the row isn't an
    agent run or has no trace.
    """
    import json as _json
    if (row.get("mode") or "").lower() != "agent":
        return None
    extra_raw = row.get("extra")
    if not extra_raw:
        return None
    try:
        extra = _json.loads(extra_raw) if isinstance(extra_raw, str) else extra_raw
    except (TypeError, ValueError):
        return None

    trace = extra.get("trace") or []
    if not trace:
        return None

    lines = []
    call_idx = 0
    for step in trace:
        for tc in step.get("tool_calls") or []:
            call_idx += 1
            name = tc.get("name", "?")
            args = tc.get("args") or {}
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            lines.append(f"{call_idx:>2}. <code>{_html.escape(name)}</code>({_html.escape(args_str)})")

    used = extra.get("tool_calls_used", call_idx)
    budget = extra.get("max_tool_calls", "?")
    forced = extra.get("forced_final")
    footer = f"\n<i>{used}/{budget} tool calls"
    if forced:
        footer += " · forced final (token cap hit)"
    footer += "</i>"

    if not lines:
        return f"<i>(no tool calls — agent answered directly)</i>{footer}"
    return "\n".join(lines) + footer


def fmt_run_summary(row):
    """Quick header for a run (HTML-formatted)."""
    decision = fmt_decision(row.get("decision"))
    when = row.get("run_date") or row.get("date") or "?"
    mode = row.get("mode", "?")
    runtime = row.get("runtime_seconds", "?")
    tokens = (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0)
    model = row.get("model", "?")
    host = row.get("host", "?")
    return (
        f"📊 <b>{row['ticker']}</b> — {decision}\n"
        f"{when} | {mode} mode | <code>{model}</code> on <code>{host}</code>\n"
        f"Runtime: {runtime}s | Tokens: {tokens:,}"
    )


# ── KEYBOARDS ────────────────────────────────────────────────────────────────
def main_keyboard():
    rows = [
        [KeyboardButton("/status"), KeyboardButton("/queue")],
        [KeyboardButton("/list"), KeyboardButton("/last"), KeyboardButton("/trace")],
        [KeyboardButton("/runagent"), KeyboardButton("/run")],
        [KeyboardButton("/runsolo"), KeyboardButton("/runfull")],
        [KeyboardButton("/kill"), KeyboardButton("/help")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def ticker_inline_keyboard(action, columns=4):
    tickers = get_tickers_list()
    buttons = [
        InlineKeyboardButton(t, callback_data=f"{action}:{t}")
        for t in tickers
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


# ── COMMAND HANDLERS ─────────────────────────────────────────────────────────
@auth_required
async def cmd_start(update, ctx):
    msg = (
        "📊 Trading Dashboard bot.\n\n"
        "<b>Shorthand</b> (just type a ticker, optionally with model+mode):\n"
        "• <code>nvda</code> — show today's analysis if any, else pick model/mode\n"
        "• <code>nvda agent</code> — pick model, then run agent\n"
        "• <code>nvda qwen</code> — pick mode, then run on qwen 122B\n"
        "• <code>nvda qwen agent</code> — fire immediately\n"
        "Order doesn't matter; case doesn't matter.\n\n"
        "<b>Models</b>: qwen · gpt · gemma · llama · deepseek (more aliases inside)\n"
        "<b>Modes</b>: agent · core · solo · full\n\n"
        "<b>Commands</b>:\n"
        "/last TICKER, /trace TICKER, /run TICKER, /add TICKER, /remove TICKER\n"
        "/runagent /run /runsolo /runfull · /status /queue /kill\n\n"
        "Tap a command with no arguments to pick a ticker from a list."
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard(), parse_mode="HTML")


@auth_required
async def cmd_status(update, ctx):
    s = get_status()
    if s.get("status") == "idle":
        await update.message.reply_text("💤 Idle. No job running.")
        return

    current = s.get("current", "?")
    tickers = s.get("tickers", [])
    completed = s.get("completed", 0)
    total = len(tickers)
    mode = s.get("mode", "?")
    msg = (
        f"⚙️ Running [{mode.upper()}]\n"
        f"Current: {current}\n"
        f"Progress: {completed}/{total}\n"
        f"Queue: {', '.join(tickers)}"
    )
    await update.message.reply_text(msg)


@auth_required
async def cmd_list(update, ctx):
    tickers = get_tickers_list()
    if not tickers:
        await update.message.reply_text("No tickers tracked.")
        return
    await update.message.reply_text(f"📋 Tracked ({len(tickers)}):\n{', '.join(tickers)}")


@auth_required
async def cmd_add(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /add TICKER")
        return
    tickers = get_tickers_list()
    new = [t.upper() for t in ctx.args]
    tickers.extend(new)
    save_tickers_list(tickers)
    await update.message.reply_text(f"✅ Added: {', '.join(new)}")


@auth_required
async def cmd_remove(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /remove TICKER")
        return
    tickers = get_tickers_list()
    to_remove = {t.upper() for t in ctx.args}
    new_tickers = [t for t in tickers if t not in to_remove]
    save_tickers_list(new_tickers)
    await update.message.reply_text(f"🗑 Removed: {', '.join(to_remove)}")


@auth_required
async def cmd_last(update, ctx):
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker:",
            reply_markup=ticker_inline_keyboard("last"),
        )
        return
    ticker = ctx.args[0].upper()
    await _send_last_to_chat(ctx.bot, update.effective_chat.id, ticker)


async def _send_last_to_chat(bot, chat_id, ticker, mode=None):
    """Shared: fetch latest analysis and send (split if needed) to a chat.
    If mode is given, fetch latest run for that mode specifically."""
    row = get_latest_run(ticker, mode=mode)
    if not row:
        await bot.send_message(chat_id=chat_id, text=f"No analyses found for {ticker}.")
        return

    header = fmt_run_summary(row)
    analysis = row.get("analysis") or "(no analysis text)"
    analysis_html = md_to_html(analysis)
    full_text = f"{header}\n\n{'─' * 30}\n\n{analysis_html}"

    for chunk in split_message(full_text):
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


@auth_required
async def cmd_run(update, ctx):
    """Default = core mode."""
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker to run (core):",
            reply_markup=ticker_inline_keyboard("run"),
        )
        return
    await _start_run(ctx.bot, update.effective_chat.id, [t.upper() for t in ctx.args], "core")


@auth_required
async def cmd_runfull(update, ctx):
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker to run (full):",
            reply_markup=ticker_inline_keyboard("runfull"),
        )
        return
    await _start_run(ctx.bot, update.effective_chat.id, [t.upper() for t in ctx.args], "full")


@auth_required
async def cmd_runsolo(update, ctx):
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker to run (solo, fast):",
            reply_markup=ticker_inline_keyboard("runsolo"),
        )
        return
    await _start_run(ctx.bot, update.effective_chat.id, [t.upper() for t in ctx.args], "solo")


@auth_required
async def cmd_trace(update, ctx):
    """Show the latest agent run's tool-call sequence for a ticker."""
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker:",
            reply_markup=ticker_inline_keyboard("trace"),
        )
        return
    ticker = ctx.args[0].upper()
    await _send_trace_to_chat(ctx.bot, update.effective_chat.id, ticker)


async def _send_trace_to_chat(bot, chat_id, ticker):
    row = get_latest_run(ticker, mode="agent")
    if not row:
        await bot.send_message(
            chat_id=chat_id,
            text=f"No agent runs found for {ticker}. Try /runagent {ticker}.",
        )
        return
    trace_text = fmt_agent_trace(row)
    if trace_text is None:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Run #{row['id']} for {ticker} has no trace data.",
        )
        return
    decision = fmt_decision(row.get("decision"))
    when = row.get("run_date") or "?"
    header = (
        f"🛠 <b>{ticker}</b> agent trace — {decision}\n"
        f"<i>{when} · run #{row['id']}</i>\n"
    )
    full = f"{header}\n{trace_text}"
    for chunk in split_message(full):
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


@auth_required
async def cmd_runagent(update, ctx):
    """Agent mode — autonomous tool-calling loop. Ollama only."""
    if not ctx.args:
        await update.message.reply_text(
            "Pick a ticker to run (agent):",
            reply_markup=ticker_inline_keyboard("runagent"),
        )
        return
    await _start_run(ctx.bot, update.effective_chat.id, [t.upper() for t in ctx.args], "agent")


async def _start_run(bot, chat_id, tickers, mode, model=None):
    """mode: 'solo' | 'core' | 'full' | 'agent'.

    model: optional Ollama model id (e.g. "qwen3.5:122b"). When None,
    runner.py uses the project default (config.OLLAMA_MODEL). When set,
    we also pull the matching per-model agent budget from config and
    pass --max-tool-calls / --max-tokens / --num-ctx accordingly.
    """
    s = get_status()
    if s.get("status") == "running":
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ A job is already running ({s.get('current')}). Use /kill first."
        )
        return

    provider = os.getenv("LLM_PROVIDER", "ollama")
    if provider == "ollama":
        if not check_ollama_alive():
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ Ollama server is unreachable.\n\n"
                    "Either start the server, or switch provider to gemini in the dashboard."
                ),
            )
            return

    model_note = f" on <code>{model}</code>" if model else ""
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚀 Starting <b>{mode}</b> analysis for {', '.join(tickers)}{model_note}...\n"
            f"You'll get the full analysis when each ticker completes."
        ),
        parse_mode="HTML",
    )

    cmd = [str(PYTHON), str(RUNNER), "--tickers", ",".join(tickers)]
    if model:
        cmd.extend(["--model", model])
    if mode == "full":
        cmd.append("--full")
    elif mode == "solo":
        cmd.append("--solo")
    elif mode == "agent":
        # Per-model agent budget — picks max_tool_calls / max_tokens /
        # num_ctx tuned to fit each model's natural context (so Ollama
        # doesn't reload between runs).
        budget = get_agent_budget(model) if model else get_agent_budget("")
        cmd.extend([
            "--agent",
            "--max-tool-calls", str(budget["max_tool_calls"]),
            "--max-tokens",     str(budget["max_tokens"]),
            "--num-ctx",        str(budget["num_ctx"]),
        ])
    # core needs no flag, it's the default

    log_path = os.path.expanduser("~/.tradingagents/bot_run.log")
    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=logf, stderr=subprocess.STDOUT,
        )

    asyncio.create_task(_watch_and_notify(proc, tickers, mode, chat_id, bot))


# ── Natural-language handler + cascade ──────────────────────────────────────
# Tokens the user types: a ticker (uppercase 1-6 letters), optionally a
# model alias and/or a mode keyword. Order-independent. Examples:
#   "nvda"             → look up today's run, cascade if missing
#   "nvda agent"       → cascade for model, then fire (skip lookup)
#   "nvda qwen"        → cascade for mode, then fire
#   "nvda qwen agent"  → fire immediately
_TICKER_RE = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z]{1,3})?$")


def _parse_msg(text: str) -> tuple[str | None, str | None, str | None]:
    """Tokenize a user message and resolve (ticker, model, mode).

    Returns (None, None, None) if no ticker is identifiable.
    """
    # Split on whitespace and common separators; drop empties.
    tokens = [t for t in re.split(r"[\s,;/|]+", text.strip()) if t]
    ticker: str | None = None
    model: str | None = None
    mode: str | None = None
    for raw in tokens:
        if not raw:
            continue
        # Try resolve as mode first (cheap exact-match lookup)
        m = resolve_mode(raw)
        if m and mode is None:
            mode = m
            continue
        # Try resolve as model (handles "qwen", "gpt-oss:20b" etc.)
        mod = resolve_model(raw)
        if mod and model is None:
            model = mod
            continue
        # Anything left that looks like a ticker
        up = raw.upper()
        if ticker is None and _TICKER_RE.match(up):
            ticker = up
    return ticker, model, mode


def get_today_latest(ticker: str) -> dict | None:
    """Latest run for `ticker` with run_date == today, or None."""
    today_str = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM runs WHERE ticker=? AND run_date=? "
        "ORDER BY id DESC LIMIT 1",
        (ticker, today_str),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# Unique canonical model ids ordered by recommended pick. The cascade
# picker shows these as buttons in 2 columns.
_CASCADE_MODELS: list[tuple[str, str]] = [
    ("qwen3.5:122b",   "qwen 122B"),
    ("gpt-oss:120b",   "gpt-oss 120B"),
    ("qwen3.6:35b",    "qwen 35B"),
    ("qwen3:32b",      "qwen 32B"),
    ("llama3.3:70b",   "llama 70B"),
    ("deepseek-r1:32b","deepseek-r1 32B"),
    ("gemma4:31b",     "gemma 31B"),
    ("gemma4:26b",     "gemma 26B"),
    ("gpt-oss:20b",    "gpt-oss 20B"),
]

_CASCADE_MODES: list[tuple[str, str]] = [
    ("agent", "agent"),
    ("core",  "core"),
    ("solo",  "solo"),
    ("full",  "full"),
]


def _cascade_cb(ticker: str, model: str | None, mode: str | None) -> str:
    """Encode cascade state into a callback_data string.

    Format: cas|<ticker>|<model_or_->|<mode_or_->
    Length stays under Telegram's 64-byte limit for realistic inputs.
    """
    return f"cas|{ticker}|{model or '-'}|{mode or '-'}"


def _model_keyboard(ticker: str, mode: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for model_id, label in _CASCADE_MODELS:
        row.append(InlineKeyboardButton(
            label, callback_data=_cascade_cb(ticker, model_id, mode),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def _mode_keyboard(ticker: str, model: str | None) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(label, callback_data=_cascade_cb(ticker, model, mode_id))
        for mode_id, label in _CASCADE_MODES
    ]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("✖ Cancel", callback_data="cancel")]])


def _save_prompt_cb(choice: str, ticker: str, model: str | None, mode: str | None) -> str:
    """Encode the save-prompt decision into callback_data.

    choice: 'y' (save & run), 'n' (run only). Cancel uses the generic
    'cancel' callback already handled at the top of on_button.
    """
    return f"save|{choice}|{ticker}|{model or '-'}|{mode or '-'}"


async def _maybe_prompt_save_and_run(bot, chat_id, ticker, mode, model=None):
    """Prompt to save the ticker if it's not in tickers.txt; else just run.

    This is the chokepoint between all "we're about to fire a run" paths
    (direct fire from cmd_text, end of cascade) and the actual subprocess
    launch. Centralizing the gate here means all new-ticker analyses go
    through the same Save/Run/Cancel decision without each caller needing
    to remember.
    """
    tracked = set(get_tickers_list())
    if ticker.upper() in tracked:
        await _start_run(bot, chat_id, [ticker], mode, model=model)
        return

    # Build a small "details" line so the user can confirm what they're
    # about to fire on top of the save decision.
    details = f"<code>{model or 'default'}</code> · <b>{mode}</b>"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💾 Save & Run",
                callback_data=_save_prompt_cb("y", ticker, model, mode),
            ),
            InlineKeyboardButton(
                "Run Only",
                callback_data=_save_prompt_cb("n", ticker, model, mode),
            ),
        ],
        [InlineKeyboardButton("✖ Cancel", callback_data="cancel")],
    ])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⚠️ <b>{ticker}</b> isn't in your tracked list yet "
            f"({details}).\n\nAdd it before running?"
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )


async def _next_cascade_step(bot, chat_id, ticker, model, mode):
    """Dispatch the next cascade step: show picker, or fire."""
    if model and mode:
        await _maybe_prompt_save_and_run(bot, chat_id, ticker, mode, model=model)
        return
    if model and not mode:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Pick a mode for <b>{ticker}</b> on <code>{model}</code>:",
            parse_mode="HTML",
            reply_markup=_mode_keyboard(ticker, model),
        )
        return
    # Either both missing, or only mode set — show model picker either way.
    title = (
        f"Pick a model for <b>{ticker}</b> · <code>{mode}</code>:"
        if mode else
        f"📊 No analysis today for <b>{ticker}</b>.\nPick a model:"
    )
    await bot.send_message(
        chat_id=chat_id,
        text=title,
        parse_mode="HTML",
        reply_markup=_model_keyboard(ticker, mode),
    )


@auth_required
async def cmd_text(update, ctx):
    """Free-text handler. Parses 'nvda [model] [mode]' shorthand."""
    text = (update.message.text or "").strip()
    if not text:
        return
    ticker, model, mode = _parse_msg(text)
    if not ticker:
        await update.message.reply_text(
            "I didn't see a ticker in that. Try `nvda`, `nvda agent`, or "
            "`nvda qwen agent`. Send /start for help.",
        )
        return

    chat_id = update.effective_chat.id

    # Fully specified → fire (the busy-guard inside _start_run rejects
    # if another job is already in flight). _maybe_prompt_save_and_run
    # interjects a Save/Run/Cancel prompt if the ticker isn't yet tracked.
    if model and mode:
        await _maybe_prompt_save_and_run(ctx.bot, chat_id, ticker, mode, model=model)
        return

    # Partial qualifier(s) → cascade the missing piece(s), no lookup.
    if model or mode:
        await _next_cascade_step(ctx.bot, chat_id, ticker, model, mode)
        return

    # Bare ticker → lookup today's run first. Fall through to cascade
    # only if nothing today.
    row = get_today_latest(ticker)
    if row:
        await _send_last_to_chat(ctx.bot, chat_id, ticker)
        return
    await _next_cascade_step(ctx.bot, chat_id, ticker, None, None)


def _stuck_verdict(server: dict, proc_info: dict | None) -> str:
    """One-line read on whether the run is actually stuck.

    Signals:
      - Server unreachable        → almost certainly stuck (network/host)
      - Server up, no models      → Ollama purged the model; our request died
      - Process state D           → uninterruptible wait, often genuine hang
      - Process state S + alive   → waiting on socket reply, probably just slow
      - Process state Z           → already dead, parent hasn't reaped
    """
    if not server.get("reachable"):
        return "❌ Ollama unreachable — almost certainly stuck. Kill recommended."
    loaded = server.get("loaded") or []
    if not loaded:
        return (
            "⚠️ Ollama is up but no models are loaded — your request "
            "probably timed out on the server side. Kill recommended."
        )
    if proc_info:
        sc = proc_info["state_char"]
        if sc == "Z":
            return "❌ Runner is a zombie — already dead. Kill to reap."
        if sc == "D":
            return (
                "⚠️ Runner is in uninterruptible wait (state D) — often a "
                "genuine hang (network/disk). Kill recommended."
            )
        if sc == "S":
            return (
                "✓ Looks healthy — runner waiting on Ollama's reply (state S), "
                "model is loaded. Probably just slow. Wait if you can."
            )
        if sc == "R":
            return "✓ Runner actively running (state R). Probably fine, just slow."
    return "Ambiguous — diagnostics above. Your call."


async def _watch_and_notify(proc, tickers, mode_label, chat_id, bot):
    """Wait for runner subprocess to finish, then send the full analysis for
    each ticker.

    While the subprocess runs, we also watch for stuck tickers. Threshold
    is per-mode (config.STUCK_THRESHOLD_SECONDS) and is reset each time the
    runner advances to a new ticker — so a healthy multi-ticker batch where
    each ticker takes 30s doesn't trigger a false alarm at total elapsed.
    The nudge fires at most once per run.
    """
    import time
    threshold = STUCK_THRESHOLD_SECONDS.get(mode_label, 300)
    last_current: str | None = None
    ticker_start: float = time.monotonic()
    nudged: bool = False

    while proc.poll() is None:
        await asyncio.sleep(2)
        if nudged:
            continue
        # Track per-ticker elapsed by watching status.current. When the
        # runner advances, reset the per-ticker clock.
        s = get_status()
        cur = s.get("current")
        if cur != last_current:
            last_current = cur
            ticker_start = time.monotonic()
        if not cur:
            continue
        elapsed = time.monotonic() - ticker_start
        if elapsed > threshold:
            nudged = True
            # Probe ml60 + read /proc state so the user has more to go on
            # than just "elapsed > threshold".
            server = check_server_status()
            proc_info = check_runner_proc(proc.pid)
            diag = _fmt_server_diagnostics(server, proc_info, s)

            # Heuristic verdict — combine the signals into a one-line read
            verdict = _stuck_verdict(server, proc_info)

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "☠️ Kill", callback_data=f"killrun|{proc.pid}",
                ),
                InlineKeyboardButton("⏳ Wait", callback_data="cancel"),
            ]])
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ The <b>{mode_label}</b> run on <b>{cur}</b> has been "
                    f"going {int(elapsed)}s — typical {mode_label} runs "
                    f"finish in under {threshold}s.\n\n"
                    f"{diag}\n\n"
                    f"<b>Read</b>: {verdict}"
                ),
                parse_mode="HTML",
                reply_markup=kb,
            )

    if proc.returncode != 0:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Run failed (exit code {proc.returncode}). Check the dashboard for details.",
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text="✅ <b>Run complete.</b>",
        parse_mode="HTML",
    )

    for ticker in tickers:
        await _send_last_to_chat(bot, chat_id, ticker, mode=mode_label)


@auth_required
async def cmd_queue(update, ctx):
    s = get_status()
    if s.get("status") != "running":
        await update.message.reply_text("No active queue.")
        return
    tickers = s.get("tickers", [])
    completed = s.get("completed", 0)
    msg = f"Queue ({completed}/{len(tickers)}):\n"
    for i, t in enumerate(tickers):
        prefix = "✅" if i < completed else ("⏳" if i == completed else "⏸")
        msg += f"{prefix} {t}\n"
    await update.message.reply_text(msg)


@auth_required
async def cmd_server(update, ctx):
    """Probe the Ollama server + show any active run's process state."""
    status = get_status()
    server = check_server_status()
    proc_info = check_runner_proc(status.get("pid"))
    text = _fmt_server_diagnostics(server, proc_info, status)
    await update.message.reply_text(text, parse_mode="HTML")


@auth_required
async def cmd_kill(update, ctx):
    s = get_status()
    pid = s.get("pid")
    if not pid:
        await update.message.reply_text("No running job to kill.")
        return
    try:
        os.kill(pid, 15)
        await update.message.reply_text(f"☠️ Sent kill signal to PID {pid}.")
    except ProcessLookupError:
        await update.message.reply_text(f"PID {pid} not found (already dead?).")
    except Exception as e:
        await update.message.reply_text(f"Kill failed: {e}")


@auth_required
async def cmd_unknown(update, ctx):
    await update.message.reply_text(
        "Unknown command. Try /start to see available commands."
    )


# ── INLINE BUTTON CALLBACK ───────────────────────────────────────────────────
@auth_required
async def on_button(update, ctx):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    chat_id = query.message.chat.id

    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    # Stuck-run kill button: callback sent from the watcher's nudge.
    # Format: killrun|<pid>
    if data.startswith("killrun|"):
        parts = data.split("|", 1)
        pid_str = parts[1] if len(parts) == 2 else ""
        try:
            pid = int(pid_str)
            os.kill(pid, 15)  # SIGTERM — runner closes DB cleanly on this
            await query.edit_message_text(
                f"☠️ Sent kill signal to PID {pid}. The watcher will report "
                f"the failed exit shortly.",
            )
        except (ValueError, ProcessLookupError):
            await query.edit_message_text(
                "Process already gone — likely finished or was killed already.",
            )
        except Exception as e:
            await query.edit_message_text(f"Kill failed: {e}")
        return

    # Save-prompt callbacks: user chose Save & Run / Run Only.
    # Format: save|<y|n>|<ticker>|<model_or_->|<mode_or_->
    if data.startswith("save|"):
        parts = data.split("|", 4)
        if len(parts) != 5:
            return
        _, choice, ticker, model_field, mode_field = parts
        model = None if model_field == "-" else model_field
        mode = None if mode_field == "-" else mode_field

        if choice == "y":
            existing = set(get_tickers_list())
            if ticker.upper() not in existing:
                save_tickers_list(list(existing | {ticker.upper()}))
            await query.edit_message_text(
                f"💾 Saved <b>{ticker}</b> to your tracked list. Starting run...",
                parse_mode="HTML",
            )
        else:
            await query.edit_message_text(
                f"⏭ Running <b>{ticker}</b> (not saved).",
                parse_mode="HTML",
            )
        await _start_run(ctx.bot, chat_id, [ticker], mode, model=model)
        return

    # Cascade callbacks use "|" as field delimiter because canonical model
    # ids contain colons (e.g. "qwen3.5:122b") which would clash with the
    # legacy "action:payload" colon-split.
    if data.startswith("cas|"):
        parts = data.split("|", 3)
        if len(parts) != 4:
            return
        _, ticker, model_field, mode_field = parts
        model = None if model_field == "-" else model_field
        mode = None if mode_field == "-" else mode_field
        if model and mode:
            await query.edit_message_text(
                f"🚀 {ticker} · <code>{model}</code> · <b>{mode}</b>...",
                parse_mode="HTML",
            )
            await _start_run(ctx.bot, chat_id, [ticker], mode, model=model)
        else:
            # Still missing a piece — replace the current picker with the next.
            await query.delete_message()
            await _next_cascade_step(ctx.bot, chat_id, ticker, model, mode)
        return

    if ":" not in data:
        return

    action, payload = data.split(":", 1)

    if action == "last":
        await query.edit_message_text(f"📊 Loading {payload}...")
        await _send_last_to_chat(ctx.bot, chat_id, payload)

    elif action == "trace":
        await query.edit_message_text(f"🛠 Loading trace for {payload}...")
        await _send_trace_to_chat(ctx.bot, chat_id, payload)

    elif action in ("run", "runfull", "runsolo", "runagent"):
        mode = {
            "run": "core",
            "runfull": "full",
            "runsolo": "solo",
            "runagent": "agent",
        }[action]
        await query.edit_message_text(
            f"🚀 Triggered {mode} run on {payload}..."
        )
        await _start_run(ctx.bot, chat_id, [payload], mode)


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not ALLOWED_USER_ID:
        print("ERROR: TELEGRAM_ALLOWED_USER_ID not set in .env")
        sys.exit(1)

    print(f"Starting bot. Allowed user: {ALLOWED_USER_ID}")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(CommandHandler("trace", cmd_trace))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("runfull", cmd_runfull))
    app.add_handler(CommandHandler("runsolo", cmd_runsolo))
    app.add_handler(CommandHandler("runagent", cmd_runagent))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("server", cmd_server))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CallbackQueryHandler(on_button))
    # Free-text shorthand handler — MUST come before the COMMAND catch-all
    # below; otherwise text that doesn't start with "/" gets matched by
    # COMMAND first. (filters.TEXT excludes commands, so the order would
    # technically be safe either way — but explicit is better.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_text))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.run_polling()


if __name__ == "__main__":
    main()