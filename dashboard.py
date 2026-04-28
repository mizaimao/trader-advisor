import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import json
from db import init_db, get_runs, get_status, set_status
import os
import signal
import subprocess
from news import get_news_finnhub
from datetime import datetime, timedelta
from plotly.subplots import make_subplots
from news import days_until_earnings

from news import days_until_earnings as _days_until_earnings_raw

PROJECT_ROOT = os.path.expanduser("~/moose-trader")
PYTHON_BIN = os.path.join(PROJECT_ROOT, ".venv/bin/python")
RUNNER_PATH = os.path.join(PROJECT_ROOT, "runner.py")

@st.cache_data(ttl=3600)
def days_until_earnings_cached(ticker):
    return _days_until_earnings_raw(ticker)

@st.cache_data(ttl=3600)
def get_earnings_event_cached(ticker):
    from news import get_earnings_calendar_finnhub
    return get_earnings_calendar_finnhub(ticker)

@st.cache_data(ttl=3600)
def insider_summary_cached(ticker):
    from news import insider_summary_text
    return insider_summary_text(ticker)

@st.cache_data(ttl=3600)
def insider_transactions_cached(ticker, days_back=90):
    from news import get_insider_transactions_finnhub
    return get_insider_transactions_finnhub(ticker, days_back=days_back)

@st.cache_data(ttl=1800)
def options_summary_cached(ticker):
    from options import get_options_summary
    return get_options_summary(ticker)

@st.cache_data(ttl=1800)
def options_chain_cached(ticker, expiry):
    """Returns (calls_df, puts_df) for the given expiry as JSON-serializable dicts."""
    tk = yf.Ticker(ticker)
    chain = tk.option_chain(expiry)
    return chain.calls.to_dict("records"), chain.puts.to_dict("records")

init_db()

st.set_page_config(page_title="Trading Dashboard", layout="wide")
st.title("📈 Trading Analysis Dashboard")

TICKERS_FILE = os.path.expanduser("~/.tradingagents/tickers.txt")
os.makedirs(os.path.dirname(TICKERS_FILE), exist_ok=True)


def _escape_dollars(text):
    """Replace $ with HTML entity so Streamlit doesn't render LaTeX math.
    Streamlit interprets $...$ as inline math; this breaks any text containing
    dollar amounts (e.g. '$180 million', '$10.00 level')."""
    if not text:
        return text
    return text.replace("$", "&#36;")


def load_tickers():
    if not os.path.exists(TICKERS_FILE):
        return ["NVDA"]
    with open(TICKERS_FILE) as f:
        return [t.strip().upper() for t in f.readlines() if t.strip()]

def save_tickers(t):
    with open(TICKERS_FILE, "w") as f:
        f.write("\n".join(t))

def _abbrev_dollar(amount):
    """Format a number like 22249357 → '$22M' or 1234 → '$1K'."""
    try:
        n = float(amount)
    except:
        return "?"
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.0f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"

def insider_label(summary):
    """Compact label: emoji + abbreviated $amount + (latest date)."""
    if not summary:
        return "—"
    import re
    m = re.search(r"\$([\d,]+)", summary)
    raw = m.group(1).replace(",", "") if m else "0"
    amt = _abbrev_dollar(raw)

    date_match = re.search(r"latest:\s*(\d{4}-\d{2}-\d{2})", summary)
    date_str = ""
    if date_match:
        from datetime import datetime
        try:
            d = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            date_str = f" ({d.month}/{d.day})"
        except:
            date_str = ""

    if "buying" in summary:
        return f"🟢 {amt}{date_str}"
    if "selling" in summary:
        return f"🔴 {amt}{date_str}"
    return f"{amt}{date_str}"

def insider_color(summary):
    if not summary:
        return "color: #444444"
    if "buying" in summary:
        return "color: #00ff00"
    if "selling" in summary:
        return "color: #ff4444"
    return "color: #888"


def earnings_label(days):
    if days is None:
        return "—"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"{days}d"

def earnings_color(days):
    if days is None:
        return "color: #444444"
    if days <= 3:
        return "color: #ff4444; font-weight: 600"
    if days <= 7:
        return "color: #ffff00"
    return "color: #888"

def relative_time(date_str):
    if not date_str or str(date_str) in ("None", "nan", ""):
        return "—"
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        delta = datetime.today() - dt
        if delta.days == 0:
            return "today"
        elif delta.days == 1:
            return "yesterday"
        else:
            return f"{delta.days}d ago"
    except:
        return "—"

def time_color(date_str):
    if not date_str or str(date_str) in ("None", "nan", ""):
        return "color: #444444"
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        delta = datetime.today() - dt
        if delta.days == 0:
            return "color: #00ff00"
        elif delta.days <= 1:
            return "color: #ffff00"
        else:
            return "color: #ff4444"
    except:
        return "color: #444444"

def color_decision(val):
    val = str(val).upper()
    if "BUY" in val or "OVERWEIGHT" in val:
        return "background-color: #1a4a1a; color: #00ff00"
    elif "SELL" in val or "UNDERWEIGHT" in val:
        return "background-color: #4a1a1a; color: #ff4444"
    elif val in ("—", "UNKNOWN", "NAN", ""):
        return "color: #444444"
    else:
        return "background-color: #3a3a1a; color: #ffff00"

def render_analysis(text):
    if not text:
        return
    import re

    st.markdown("""
        <style>
        .analysis-section {
            background: #1a1a2e;
            border-left: 4px solid #4a90d9;
            padding: 16px 20px;
            margin: 12px 0;
            border-radius: 6px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 16px;
            line-height: 1.75;
            color: #e8e8e8;
        }
        .analysis-section h3 {
            color: #7ab8f5;
            font-size: 18px;
            font-weight: 600;
            margin: 0 0 10px 0;
            border-bottom: 1px solid #2a4a6a;
            padding-bottom: 6px;
        }
        .analysis-section ul { margin: 8px 0; padding-left: 22px; }
        .analysis-section li { margin: 4px 0; }
        .analysis-section strong { color: #ffd966; }
        </style>
    """, unsafe_allow_html=True)

    SECTIONS = [
        "Technical Outlook",
        "Fundamental Snapshot",
        "Catalysts",
        "News Sentiment",
        "Insider Activity",
        "Sector & Macro Context",
        "Counter-Thesis",
        "Strongest Counter-Evidence",
        "What the Initial Analyst Got Wrong",
        "Key Disagreement",
        "Final Decision",
    ]

    pattern = r"(?:^|\n)\s*\**\s*(" + "|".join(re.escape(s) for s in SECTIONS) + r")\s*:?\**"
    parts = re.split(pattern, text)

    if len(parts) < 3:
        clean = _escape_dollars(text.replace("**", "").strip())
        st.markdown(f'<div class="analysis-section">{clean}</div>', unsafe_allow_html=True)
        return

    i = 1 if not parts[0].strip() else 0
    if i == 0 and parts[0].strip():
        preamble = _escape_dollars(parts[0].strip())
        st.markdown(f'<div class="analysis-section">{preamble}</div>', unsafe_allow_html=True)
        i = 1

    while i < len(parts) - 1:
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""

        body_html = _format_body(body)
        st.markdown(
            f'<div class="analysis-section"><h3>{heading}</h3>{body_html}</div>',
            unsafe_allow_html=True
        )
        i += 2


def _format_body(body):
    """Convert markdown-ish body text to HTML with bullets and bold."""
    import re
    # Escape $ so Streamlit doesn't interpret as LaTeX math mode
    body = body.replace("$", "&#36;")
    # Bold **text**
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    # Strip any leftover ** or * that didn't get paired
    body = body.replace("**", "").replace("__", "")
    # Detect bullet lines (starting with *, -, or numbered)
    lines = body.split("\n")
    out = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[\*\-•]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = re.sub(r"^[\*\-•]\s+", "", stripped)
            item = re.sub(r"^\d+\.\s+", "", item)
            out.append(f"<li>{item}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if stripped:
                out.append(f"<p style='margin: 8px 0'>{stripped}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def render_panel(extra_json):
    """Render the 3-section breakdown for core mode runs.
    extra_json is the JSON string from the runs.extra column."""
    if not extra_json:
        st.info("No panel breakdown available for this run.")
        return
    try:
        extra = json.loads(extra_json)
    except (json.JSONDecodeError, TypeError):
        st.warning("Could not parse panel breakdown.")
        return

    initial_decision = extra.get("initial_decision") or "—"
    synthesis_decision = extra.get("synthesis_decision") or "—"

    # Show whether the panel changed its mind
    if initial_decision != synthesis_decision:
        st.markdown(
            f"<div style='padding:10px 14px;background:#2a2a3e;border-left:4px solid #ffd966;"
            f"border-radius:4px;margin-bottom:14px'>"
            f"⚖️ <b>Panel changed its mind:</b> "
            f"<span style='color:#888'>Initial: {initial_decision}</span> → "
            f"<span style='color:#ffd966'>Synthesis: {synthesis_decision}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding:10px 14px;background:#1a2a1a;border-left:4px solid #00ff00;"
            f"border-radius:4px;margin-bottom:14px'>"
            f"✅ <b>Panel agreed:</b> {synthesis_decision}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Synthesis (the final answer) — open by default
    with st.expander(f"🎯 Synthesis (final) — {synthesis_decision}", expanded=True):
        render_analysis(extra.get("synthesis_analysis") or "")

    # Initial analyst — collapsed
    with st.expander(f"📋 Initial Analyst — {initial_decision}", expanded=False):
        render_analysis(extra.get("initial_analysis") or "")

    # Devil's advocate — collapsed
    with st.expander("😈 Devil's Advocate", expanded=False):
        render_analysis(extra.get("advocate_analysis") or "")


def render_news(news_text):
    if not news_text:
        return
    current = {}
    for line in news_text.split("\n"):
        line = line.strip()
        if line.startswith("###"):
            if current.get("title"):
                _render_news_card(current)
                current = {}
            current["title"] = line.replace("###", "").strip()
        elif line.startswith("Date:"):
            current["date"] = line.replace("Date:", "").strip()
        elif line.startswith("Link:"):
            current["link"] = line.replace("Link:", "").strip()
        elif line and not line.startswith("##") and current.get("title"):
            current["summary"] = current.get("summary", "") + " " + line
    if current.get("title"):
        _render_news_card(current)

def _render_news_card(article):
    title = _escape_dollars(article.get("title", ""))
    date = article.get("date", "")
    link = article.get("link", "")
    summary = _escape_dollars(article.get("summary", "").strip())
    st.markdown(
        f'''<div style="background:#1a1a2e;border-left:3px solid #2a6496;padding:12px 16px;margin:8px 0;border-radius:4px">
<div style="font-size:15px;font-weight:600;color:#7ab8f5;margin-bottom:4px">{title}</div>
<div style="font-size:12px;color:#888;margin-bottom:6px">{date}</div>
<div style="font-size:14px;color:#cccccc;line-height:1.6;margin-bottom:8px">{summary}</div>
<a href="{link}" target="_blank" style="font-size:12px;color:#4a90d9">Read more →</a>
</div>''',
        unsafe_allow_html=True
    )

managed_tickers = load_tickers()
all_runs = get_runs(limit=1000)
df = pd.DataFrame(all_runs) if all_runs else pd.DataFrame()

# ── Clear queue flag (must run before widgets render) ─────────────────────────
if st.session_state.get("clear_queue"):
    for t in managed_tickers:
        st.session_state[f"chk_{t}"] = False
    st.session_state["clear_queue"] = False

# ── Session state ─────────────────────────────────────────────────────────────
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = managed_tickers[0] if managed_tickers else None

# ── Job Status Banner ─────────────────────────────────────────────────────────
status = get_status()
if status["status"] == "running":
    completed = status.get("completed", 0)
    total = status.get("total", 0)
    current = status.get("current", "—")
    done = status.get("tickers", [])[:completed]
    remaining = status.get("tickers", [])[completed+1:]
    st.warning(
        f"⚙️ **[{status.get('mode','').upper()}] Running** — "
        f"**{current}** ({completed + 1} of {total}) | "
        f"Done: {', '.join(done) if done else 'none'} | "
        f"Remaining: {', '.join(remaining) if remaining else 'none'} | "
        f"Started: {status.get('started_at', '—')}"
    )
    col_refresh, col_kill, _ = st.columns([1, 1, 6])
    col_refresh.button("🔄 Refresh Status", key="refresh_btn")
    if col_kill.button("🛑 Kill Job", type="primary", key="kill_btn"):
        pid = status.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                set_status("idle")
                st.success(f"Killed PID {pid}")
                st.rerun()
            except (ProcessLookupError, OSError):
                set_status("idle")
                st.success(f"PID {pid} was already dead. Status cleared.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to kill: {e}")
        else:
            set_status("idle")
            st.success("Status forcibly cleared.")
            st.rerun()
else:
    st.success("✅ Idle — no jobs running")

st.divider()

# ── Top metrics ───────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Tickers Tracked", len(managed_tickers))
if not df.empty:
    col2.metric("Total Runs", len(df))
    col3.metric("Total Tokens", f"{df['total_tokens'].sum():,}")
    col4.metric("Est. Cost (Sonnet)", f"${df['cost_sonnet'].sum():.4f}")
else:
    col2.metric("Total Runs", 0)
    col3.metric("Total Tokens", 0)
    col4.metric("Est. Cost (Sonnet)", "$0.00")

st.divider()

# ── Ticker Management ─────────────────────────────────────────────────────────
with st.expander("⚙️ Manage Tickers"):
    col_add, col_remove, col_list = st.columns([1, 1, 2])
    with col_add:
        new_ticker = st.text_input("Add ticker").strip().upper()
        if st.button("Add") and new_ticker:
            if new_ticker not in managed_tickers:
                managed_tickers.append(new_ticker)
                save_tickers(managed_tickers)
                st.success(f"Added {new_ticker}")
                st.rerun()
            else:
                st.warning(f"{new_ticker} already exists")
    with col_remove:
        remove_ticker = st.selectbox("Remove ticker", managed_tickers)
        if st.button("Remove"):
            managed_tickers.remove(remove_ticker)
            save_tickers(managed_tickers)
            st.success(f"Removed {remove_ticker}")
            st.rerun()
    with col_list:
        st.markdown("**Current tickers:**")
        st.write(", ".join(managed_tickers))

st.divider()

# ── Build master ticker table ─────────────────────────────────────────────────
TABLE_MODES = ["solo", "core", "full"]

rows = []
for ticker in managed_tickers:
    row = {"ticker": ticker}
    try:
        row["earnings_days"] = days_until_earnings_cached(ticker)
    except:
        row["earnings_days"] = None
    try:
        row["insider"] = insider_summary_cached(ticker)
    except:
        row["insider"] = None

    for mode in TABLE_MODES:
        if not df.empty:
            match = df[(df["ticker"] == ticker) & (df["mode"] == mode)]
            if not match.empty:
                latest = match.sort_values("run_date").iloc[-1]
                row[f"{mode}_decision"] = latest["decision"]
                row[f"{mode}_date"] = latest["run_date"]
                row[f"{mode}_runtime"] = latest.get("runtime_seconds", 0)
                row[f"{mode}_model"] = latest.get("model", "—")
            else:
                row[f"{mode}_decision"] = "—"
                row[f"{mode}_date"] = None
                row[f"{mode}_runtime"] = 0
                row[f"{mode}_model"] = "—"
        else:
            row[f"{mode}_decision"] = "—"
            row[f"{mode}_date"] = None
            row[f"{mode}_runtime"] = 0
            row[f"{mode}_model"] = "—"
    rows.append(row)

master_df = pd.DataFrame(rows)

# ── Master ticker table ───────────────────────────────────────────────────────
st.subheader("Ticker Overview")

col_selall, col_clrall, _ = st.columns([1, 1, 6])
if col_selall.button("☑ Select All"):
    for t in managed_tickers:
        st.session_state[f"chk_{t}"] = True
    st.rerun()
if col_clrall.button("☐ Clear All"):
    for t in managed_tickers:
        st.session_state[f"chk_{t}"] = False
    st.rerun()

# Layout: [check, ticker, earn, insider, solo, last, time, core, last, time, full, last, time, →]
COL_WEIGHTS = [0.4, 1.1, 0.8, 1.4, 1.5, 1.3, 0.8, 1.5, 1.3, 0.8, 1.5, 1.3, 0.8, 0.5]
HEADERS = ["☐", "Ticker", "Earn", "Insider",
           "Solo", "Last", "Time",
           "Core", "Last", "Time",
           "Full", "Last", "Time",
           "→"]

header_cols = st.columns(COL_WEIGHTS)
for col, label in zip(header_cols, HEADERS):
    col.markdown(f"**{label}**")

for _, row in master_df.iterrows():
    ticker = row["ticker"]
    is_running = status["status"] == "running" and status["current"] == ticker
    cols = st.columns(COL_WEIGHTS)

    cols[0].checkbox("q", key=f"chk_{ticker}", label_visibility="hidden")

    label = f"⚙️ {ticker}" if is_running else ticker
    if cols[1].button(label, key=f"tk_{ticker}", use_container_width=True):
        st.session_state.selected_ticker = ticker
        st.session_state["scroll_to_deep_dive"] = True
        st.rerun()

    edays = row.get("earnings_days")
    cols[2].markdown(f'<span style="{earnings_color(edays)}">{earnings_label(edays)}</span>', unsafe_allow_html=True)

    insider = row.get("insider")
    cols[3].markdown(
        f'<span style="{insider_color(insider)}" title="{insider or "no recent activity"}">{insider_label(insider)}</span>',
        unsafe_allow_html=True
    )

    # Solo
    cols[4].markdown(f'<span style="{color_decision(row["solo_decision"])};padding:2px 6px;border-radius:4px">{row["solo_decision"]}</span>', unsafe_allow_html=True)
    cols[5].markdown(f'<span style="{time_color(row["solo_date"])}">{relative_time(row["solo_date"])}</span>', unsafe_allow_html=True)
    cols[6].markdown(f'<span style="color:#888">{f"{row["solo_runtime"]}s" if row["solo_runtime"] else "—"}</span>', unsafe_allow_html=True)

    # Core
    cols[7].markdown(f'<span style="{color_decision(row["core_decision"])};padding:2px 6px;border-radius:4px">{row["core_decision"]}</span>', unsafe_allow_html=True)
    cols[8].markdown(f'<span style="{time_color(row["core_date"])}">{relative_time(row["core_date"])}</span>', unsafe_allow_html=True)
    cols[9].markdown(f'<span style="color:#888">{f"{row["core_runtime"]}s" if row["core_runtime"] else "—"}</span>', unsafe_allow_html=True)

    # Full
    cols[10].markdown(f'<span style="{color_decision(row["full_decision"])};padding:2px 6px;border-radius:4px">{row["full_decision"]}</span>', unsafe_allow_html=True)
    cols[11].markdown(f'<span style="{time_color(row["full_date"])}">{relative_time(row["full_date"])}</span>', unsafe_allow_html=True)
    cols[12].markdown(f'<span style="color:#888">{f"{row["full_runtime"]}s" if row["full_runtime"] else "—"}</span>', unsafe_allow_html=True)

    if cols[13].button("→", key=f"view_{ticker}"):
        st.session_state.selected_ticker = ticker
        st.session_state["scroll_to_deep_dive"] = True
        st.rerun()

st.divider()

# ── Queue + Run ───────────────────────────────────────────────────────────────
st.subheader("Run Queue")

queued = [t for t in managed_tickers if st.session_state.get(f"chk_{t}", False)]

col_queue, col_mode, col_provider, col_btn = st.columns([3, 1.2, 1.2, 1])
with col_queue:
    st.write(f"Queued: {', '.join(queued)}" if queued else "No tickers queued.")
with col_mode:
    run_mode = st.radio("Mode", ["core", "solo", "full"], index=0)
with col_provider:
    run_provider = st.radio("Provider", ["ollama (ml39)", "gemini (cloud)"], index=0)
with col_btn:
    if st.button("🚀 Run", type="primary"):
        if not queued:
            st.warning("Queue is empty.")
        elif status["status"] == "running":
            st.error("A job is already running.")
        else:
            tickers_arg = ",".join(queued)
            provider_arg = "gemini" if "gemini" in run_provider else "ollama"
            mode_args = []
            if run_mode == "full":
                mode_args = ["--full"]
            elif run_mode == "solo":
                mode_args = ["--solo"]
            try:
                os.makedirs(os.path.expanduser("~/.tradingagents"), exist_ok=True)
                log_file = open(os.path.expanduser("~/.tradingagents/popen.log"), "w")
                proc = subprocess.Popen(
                    [PYTHON_BIN, RUNNER_PATH,
                     "--tickers", tickers_arg,
                     "--provider", provider_arg,
                     *mode_args],
                    cwd=PROJECT_ROOT,
                    env=os.environ.copy(),
                    stdout=log_file,
                    stderr=log_file
                )
                st.session_state["clear_queue"] = True
                st.success(f"Job started (PID {proc.pid})")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

st.divider()


# ── Earnings Calendar Overview ────────────────────────────────────────────────
with st.expander("📅 Earnings Calendar (next 30 days)", expanded=False):
    upcoming = []
    for ticker in managed_tickers:
        try:
            days = days_until_earnings_cached(ticker)
            if days is not None and days <= 30:
                event = get_earnings_event_cached(ticker)
                if event:
                    upcoming.append({
                        "ticker": ticker,
                        "days": days,
                        "date": event.get("date", "—"),
                        "eps_estimate": event.get("epsEstimate"),
                        "revenue_estimate": event.get("revenueEstimate"),
                        "hour": event.get("hour", "—"),
                    })
        except:
            pass

    if upcoming:
        upcoming.sort(key=lambda x: x["days"])
        cal_df = pd.DataFrame(upcoming)
        cal_df["countdown"] = cal_df["days"].apply(lambda d: earnings_label(d))

        display_df = cal_df[["ticker", "countdown", "date", "hour", "eps_estimate", "revenue_estimate"]]
        display_df.columns = ["Ticker", "In", "Date", "Time", "EPS Est.", "Revenue Est."]
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No earnings scheduled within the next 30 days for tracked tickers.")

# ── Deep Dive ─────────────────────────────────────────────────────────────────
ticker_pick = st.session_state.selected_ticker

if ticker_pick and not df.empty:
    if st.session_state.get("scroll_to_deep_dive"):
        st.session_state["scroll_to_deep_dive"] = False
        import streamlit.components.v1 as components
        import time
        nonce = int(time.time() * 1000)
        components.html(f"""
            <script>
            // nonce: {nonce}
            const tryScroll = () => {{
                const doc = window.parent.document;
                const el = doc.getElementById("deep-dive-anchor")
                    || Array.from(doc.querySelectorAll('h2,h3'))
                        .find(h => h.textContent.includes("Deep Dive"));
                if (el) {{
                    el.scrollIntoView({{behavior: "smooth", block: "start"}});
                    return true;
                }}
                return false;
            }};
            let attempts = 0;
            const interval = setInterval(() => {{
                if (tryScroll() || attempts++ > 20) clearInterval(interval);
            }}, 100);
            </script>
        """, height=0)
    st.subheader(f"Deep Dive — {ticker_pick}")
    ticker_runs_all = df[df["ticker"] == ticker_pick].sort_values("id", ascending=False)

    if ticker_runs_all.empty:
        st.info(f"No runs yet for {ticker_pick}.")
    else:
        col_window, col_run = st.columns([1, 3])
        with col_window:
            window = st.selectbox(
                "History window",
                ["Last 7 days", "Last 30 days", "All time"],
                index=0,
                key="history_window"
            )

        cutoff_days = {"Last 7 days": 7, "Last 30 days": 30, "All time": 99999}[window]
        cutoff_date = (datetime.today() - timedelta(days=cutoff_days)).strftime("%Y-%m-%d")
        ticker_runs = ticker_runs_all[ticker_runs_all["run_date"] >= cutoff_date].sort_values("id", ascending=False).reset_index(drop=True)

        if ticker_runs.empty:
            st.info(f"No runs in {window.lower()}. Try a wider window.")
        else:
            ticker_runs["run_label"] = ticker_runs.apply(
                lambda r: f"#{r['id']} | {r['run_date']} | {r['mode']} | {str(r.get('created_at', ''))[:16]}",
                axis=1
            )
            with col_run:
                run_label_pick = st.selectbox(
                    "Select Run",
                    ticker_runs["run_label"].tolist(),
                    index=0,
                )
            row = ticker_runs[ticker_runs["run_label"] == run_label_pick].iloc[0]

            st.markdown("**Run History**")
            history = ticker_runs[["run_date", "mode", "decision", "total_tokens", "cost_sonnet", "runtime_seconds", "model"]]
            st.dataframe(
                history.style.map(color_decision, subset=["decision"]),
                use_container_width=True,
                hide_index=True,
            )

            st.divider()

            col_left, col_right = st.columns([1, 4])
            with col_left:
                decision_str = str(row["decision"]).upper()
                badge = "🟢" if ("BUY" in decision_str or "OVERWEIGHT" in decision_str) else "🔴" if ("SELL" in decision_str or "UNDERWEIGHT" in decision_str) else "🟡"
                st.markdown(f"### {badge} {row['decision']}")
                st.markdown(f"**Date:** {row['run_date']}")
                st.markdown(f"**Mode:** {row.get('mode', '—')}")
                st.markdown(f"**Model:** {row.get('model', '—')}")
                st.markdown(f"**Host:** {row.get('host', '—')}")
                st.markdown(f"**Runtime:** {row.get('runtime_seconds', '—')}s")
                st.markdown(f"**Tokens:** {row['total_tokens']:,}")
                st.markdown(f"**Cost (Claude Sonnet):** ${row['cost_sonnet']:.4f}")
                st.markdown(f"**Cost (Claude Opus):** ${row['cost_opus']:.4f}")
                st.markdown(f"**Cost (GPT-5.4):** ${row.get('cost_openai', row['prompt_tokens']/1e6*2.5 + row['completion_tokens']/1e6*15):.4f}")
                st.markdown(f"**Cost (Gemini 3.1):** ${row['cost_gemini']:.4f}")

            with col_right:
                hist = yf.Ticker(ticker_pick).history(period="6mo")
                if not hist.empty:
                    hist["MA50"] = hist["Close"].rolling(50).mean()
                    hist["MA200"] = hist["Close"].rolling(200).mean()
                    exp12 = hist["Close"].ewm(span=12).mean()
                    exp26 = hist["Close"].ewm(span=26).mean()
                    hist["MACD"] = exp12 - exp26
                    hist["Signal"] = hist["MACD"].ewm(span=9).mean()
                    hist["Histogram"] = hist["MACD"] - hist["Signal"]
                    delta = hist["Close"].diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = -delta.clip(upper=0).rolling(14).mean()
                    rs = gain / loss
                    hist["RSI"] = 100 - (100 / (1 + rs))

                    fig2 = make_subplots(
                        rows=4, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.15, 0.2, 0.15],
                        vertical_spacing=0.03,
                        subplot_titles=("Price", "Volume", "MACD", "RSI")
                    )
                    fig2.add_trace(go.Candlestick(
                        x=hist.index, open=hist["Open"], high=hist["High"],
                        low=hist["Low"], close=hist["Close"],
                        name="Price", showlegend=False
                    ), row=1, col=1)
                    fig2.add_trace(go.Scatter(x=hist.index, y=hist["MA50"], line=dict(color="orange", width=1), name="MA50"), row=1, col=1)
                    fig2.add_trace(go.Scatter(x=hist.index, y=hist["MA200"], line=dict(color="blue", width=1), name="MA200"), row=1, col=1)
                    vol_colors = ["green" if c >= o else "red" for c, o in zip(hist["Close"], hist["Open"])]
                    fig2.add_trace(go.Bar(x=hist.index, y=hist["Volume"], marker_color=vol_colors, name="Volume", showlegend=False), row=2, col=1)
                    macd_colors = ["green" if v >= 0 else "red" for v in hist["Histogram"]]
                    fig2.add_trace(go.Bar(x=hist.index, y=hist["Histogram"], marker_color=macd_colors, name="Histogram", showlegend=False), row=3, col=1)
                    fig2.add_trace(go.Scatter(x=hist.index, y=hist["MACD"], line=dict(color="blue", width=1), name="MACD"), row=3, col=1)
                    fig2.add_trace(go.Scatter(x=hist.index, y=hist["Signal"], line=dict(color="orange", width=1), name="Signal"), row=3, col=1)
                    fig2.add_trace(go.Scatter(x=hist.index, y=hist["RSI"], line=dict(color="purple", width=1), name="RSI", showlegend=False), row=4, col=1)
                    fig2.add_hline(y=70, line=dict(color="red", dash="dash", width=1), row=4, col=1)
                    fig2.add_hline(y=30, line=dict(color="green", dash="dash", width=1), row=4, col=1)
                    fig2.update_layout(height=600, margin=dict(l=0, r=0, t=30, b=0), xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.05))
                    fig2.update_yaxes(title_text="RSI", row=4, col=1, range=[0, 100])
                    st.plotly_chart(fig2, use_container_width=True)

            st.divider()
            st.subheader("Analysis")

            # ── Mode-aware rendering ────────────────────────────────────────
            run_mode = (row.get("mode") or "").lower()
            extra_payload = row.get("extra")

            if run_mode == "core" and extra_payload:
                render_panel(extra_payload)
            else:
                render_analysis(row.get("analysis"))

            # ── Insider activity chart ────────────────────────────────────
            st.markdown("**Insider Activity (last 90 days)**")
            insider_data = insider_transactions_cached(ticker_pick, days_back=90)
            transactions = insider_data.get("transactions", [])
            if transactions:
                tx_df = pd.DataFrame([
                    {
                        "date": tx.get("transactionDate"),
                        "value": (tx.get("change", 0) or 0) * (tx.get("transactionPrice", 0) or 0),
                        "name": tx.get("name", "?"),
                        "code": tx.get("transactionCode", "?"),
                        "shares": tx.get("change", 0) or 0,
                        "price": tx.get("transactionPrice", 0) or 0,
                    }
                    for tx in transactions
                ])
                tx_df = tx_df[tx_df["date"].notna()]
                tx_df["date"] = pd.to_datetime(tx_df["date"])
                tx_df["direction"] = tx_df["value"].apply(lambda v: "Buy" if v > 0 else "Sell")
                daily = tx_df.groupby([tx_df["date"].dt.date, "direction"])["value"].sum().reset_index()
                daily.columns = ["date", "direction", "value"]
                daily["abs_value"] = daily["value"].abs()

                fig_insider = go.Figure()
                buys = daily[daily["direction"] == "Buy"]
                sells = daily[daily["direction"] == "Sell"]
                if not buys.empty:
                    fig_insider.add_trace(go.Bar(
                        x=buys["date"], y=buys["abs_value"],
                        name="Buy", marker_color="#1a8a1a",
                        hovertemplate="%{x}<br>Buy: $%{y:,.0f}<extra></extra>"
                    ))
                if not sells.empty:
                    fig_insider.add_trace(go.Bar(
                        x=sells["date"], y=sells["abs_value"],
                        name="Sell", marker_color="#a01a1a",
                        hovertemplate="%{x}<br>Sell: $%{y:,.0f}<extra></extra>"
                    ))
                end_date = datetime.today()
                start_date = end_date - timedelta(days=90)

                fig_insider.update_layout(
                    height=250,
                    margin=dict(l=0, r=0, t=10, b=0),
                    barmode="group",
                    yaxis_title="USD",
                    legend=dict(orientation="h", y=1.1),
                    xaxis=dict(
                        type="date",
                        range=[start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
                    ),
                )
                st.plotly_chart(fig_insider, use_container_width=True)

                with st.expander("Transaction details"):
                    show_df = tx_df[["date", "name", "code", "shares", "price", "value"]].copy()
                    show_df["date"] = show_df["date"].dt.strftime("%Y-%m-%d")
                    show_df = show_df.sort_values("date", ascending=False)
                    st.dataframe(show_df, use_container_width=True, hide_index=True)
            else:
                st.info("No insider transactions in last 90 days.")

            st.divider()

            # ── Options activity panel ────────────────────────────────────
            st.markdown("**Options Snapshot**")
            opts = options_summary_cached(ticker_pick)
            if opts.get("error"):
                st.info(f"Options unavailable: {opts['error']}")
            else:
                opt_col1, opt_col2, opt_col3, opt_col4 = st.columns(4)

                pc = opts.get("put_call_ratio")
                if pc is not None:
                    sentiment = "Bearish" if pc > 1.0 else "Bullish" if pc < 0.7 else "Neutral"
                    pc_color = "#ff4444" if pc > 1.0 else "#00ff00" if pc < 0.7 else "#ffff00"
                    opt_col1.markdown(
                        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
                        f"<div style='font-size:11px;color:#888'>P/C Ratio</div>"
                        f"<div style='font-size:18px;color:{pc_color};font-weight:600'>{pc}</div>"
                        f"<div style='font-size:11px;color:#888'>{sentiment}</div>"
                        f"</div>", unsafe_allow_html=True
                    )

                iv = opts.get("atm_iv")
                if iv:
                    iv_pct = iv * 100
                    iv_color = "#ff4444" if iv_pct > 50 else "#ffff00" if iv_pct > 30 else "#888"
                    opt_col2.markdown(
                        f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
                        f"<div style='font-size:11px;color:#888'>ATM IV</div>"
                        f"<div style='font-size:18px;color:{iv_color};font-weight:600'>{iv_pct:.1f}%</div>"
                        f"<div style='font-size:11px;color:#888'>Implied Vol</div>"
                        f"</div>", unsafe_allow_html=True
                    )

                vol_total = opts.get("total_call_volume", 0) + opts.get("total_put_volume", 0)
                unusual = opts.get("unusual_volume")
                vol_color = "#ff4444" if unusual else "#888"
                vol_label = "⚠️ Unusual" if unusual else "Normal"
                opt_col3.markdown(
                    f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
                    f"<div style='font-size:11px;color:#888'>Volume</div>"
                    f"<div style='font-size:18px;color:{vol_color};font-weight:600'>{vol_total:,}</div>"
                    f"<div style='font-size:11px;color:#888'>{vol_label}</div>"
                    f"</div>", unsafe_allow_html=True
                )

                expiry = opts.get("near_expiry", "—")
                opt_col4.markdown(
                    f"<div style='padding:8px;background:#1a1a2e;border-radius:6px'>"
                    f"<div style='font-size:11px;color:#888'>Near Expiry</div>"
                    f"<div style='font-size:18px;color:#7ab8f5;font-weight:600'>{expiry}</div>"
                    f"<div style='font-size:11px;color:#888'>Calls/Puts: {opts.get('total_call_volume', 0):,} / {opts.get('total_put_volume', 0):,}</div>"
                    f"</div>", unsafe_allow_html=True
                )

                expiry = opts.get("near_expiry")
                if expiry:
                    try:
                        calls_records, puts_records = options_chain_cached(ticker_pick, expiry)
                        calls_df = pd.DataFrame(calls_records)
                        puts_df = pd.DataFrame(puts_records)

                        spot_hist = yf.Ticker(ticker_pick).history(period="1d")
                        spot = float(spot_hist["Close"].iloc[-1]) if not spot_hist.empty else None

                        if not calls_df.empty and not puts_df.empty:
                            if spot:
                                lo, hi = spot * 0.7, spot * 1.3
                                calls_df = calls_df[(calls_df["strike"] >= lo) & (calls_df["strike"] <= hi)]
                                puts_df = puts_df[(puts_df["strike"] >= lo) & (puts_df["strike"] <= hi)]

                            calls_df = calls_df.fillna(0)
                            puts_df = puts_df.fillna(0)

                            fig_opts = go.Figure()
                            fig_opts.add_trace(go.Bar(
                                x=calls_df["strike"],
                                y=calls_df["volume"],
                                name="Calls",
                                marker_color="#1a8a1a",
                                hovertemplate="Strike: $%{x}<br>Call Vol: %{y:,.0f}<extra></extra>"
                            ))
                            fig_opts.add_trace(go.Bar(
                                x=puts_df["strike"],
                                y=puts_df["volume"],
                                name="Puts",
                                marker_color="#a01a1a",
                                hovertemplate="Strike: $%{x}<br>Put Vol: %{y:,.0f}<extra></extra>"
                            ))
                            if spot:
                                fig_opts.add_vline(
                                    x=spot, line=dict(color="#ffff00", dash="dash", width=1),
                                    annotation_text=f"Spot ${spot:.2f}",
                                    annotation_position="top"
                                )
                            fig_opts.update_layout(
                                height=300,
                                margin=dict(l=0, r=0, t=30, b=0),
                                barmode="group",
                                xaxis_title=f"Strike (expiry {expiry})",
                                yaxis_title="Volume",
                                legend=dict(orientation="h", y=1.1),
                                title=dict(text="Options Volume by Strike", font=dict(size=14)),
                            )
                            st.plotly_chart(fig_opts, use_container_width=True)
                    except Exception as e:
                        st.caption(f"Volume chart unavailable: {e}")

            st.divider()
            with st.expander("📰 Latest News", expanded=True):
                days_back = st.slider("Days back", 1, 14, 3)
                end = datetime.today().strftime("%Y-%m-%d")
                start = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                render_news(get_news_finnhub(ticker_pick, start, end))