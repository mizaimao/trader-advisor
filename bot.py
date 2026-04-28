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
from datetime import datetime
from pathlib import Path
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


def check_ml39_alive(timeout=2):
    """Returns True if ml39's Ollama port is reachable."""
    try:
        with socket.create_connection(("ml39.local", 11434), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


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
        [KeyboardButton("/list"), KeyboardButton("/last")],
        [KeyboardButton("/run"), KeyboardButton("/runsolo"), KeyboardButton("/runfull")],
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
        "Use the keyboard below for quick commands, or type:\n"
        "/last TICKER, /run TICKER, /add TICKER, /remove TICKER\n\n"
        "Modes:\n"
        "• /run — core (3-call adversarial panel, default)\n"
        "• /runsolo — solo (single fast call)\n"
        "• /runfull — full (TradingAgents 7-agent graph)\n\n"
        "Tap a command with no arguments to pick a ticker from a list."
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard())


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


async def _start_run(bot, chat_id, tickers, mode):
    """mode: 'solo' | 'core' | 'full'"""
    s = get_status()
    if s.get("status") == "running":
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ A job is already running ({s.get('current')}). Use /kill first."
        )
        return

    provider = os.getenv("PROVIDER", "ollama")
    if provider == "ollama":
        if not check_ml39_alive():
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ ml39 is unreachable (Ollama server offline).\n\n"
                    "Either start ml39, or switch provider to gemini in the dashboard."
                ),
            )
            return

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚀 Starting <b>{mode}</b> analysis for {', '.join(tickers)}...\n"
            f"You'll get the full analysis when each ticker completes."
        ),
        parse_mode="HTML",
    )

    cmd = [str(PYTHON), str(RUNNER), "--tickers"] + tickers
    if mode == "full":
        cmd.append("--full")
    elif mode == "solo":
        cmd.append("--solo")
    # core needs no flag, it's the default

    log_path = os.path.expanduser("~/.tradingagents/bot_run.log")
    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=logf, stderr=subprocess.STDOUT,
        )

    asyncio.create_task(_watch_and_notify(proc, tickers, mode, chat_id, bot))


async def _watch_and_notify(proc, tickers, mode_label, chat_id, bot):
    """Wait for runner subprocess to finish, then send the full analysis for each ticker."""
    while proc.poll() is None:
        await asyncio.sleep(2)

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

    if ":" not in data:
        return

    action, payload = data.split(":", 1)

    if action == "last":
        await query.edit_message_text(f"📊 Loading {payload}...")
        await _send_last_to_chat(ctx.bot, chat_id, payload)

    elif action in ("run", "runfull", "runsolo"):
        mode = {"run": "core", "runfull": "full", "runsolo": "solo"}[action]
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
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("runfull", cmd_runfull))
    app.add_handler(CommandHandler("runsolo", cmd_runsolo))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.run_polling()


if __name__ == "__main__":
    main()