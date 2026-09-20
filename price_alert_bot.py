"""
Price Alert Bot for Telegram
============================

Users set their own price alerts in Telegram; the bot watches prices and sends a
message when a level is crossed. Crypto (Coinbase), US stocks and Borsa Istanbul
(Yahoo Finance). It only notifies — it gives no buy/sell advice.

Commands (Turkish and English aliases):
  /alarm BTC > 70000       alert when price goes above a level   (/alert)
  /alarm AAPL < 180        alert when price goes below a level
  /alarm ETH %5            alert when price moves ±5% from now
  /fiyat BTC               current price                          (/price)
  /liste                   your alerts                            (/list)
  /sil 2   |  /sil hepsi   delete one / all alerts                (/delete 2, /delete all)
  /yardim                  help                                   (/help, /start)

Run modes (RUN_MODE):
  once  – process new messages, check prices, exit (GitHub Actions, every 5 min)
  loop  – run forever: instant replies, prices checked every LOOP_SECONDS (server/PC)

Environment:
  TELEGRAM_TOKEN      (required)  bot token from @BotFather
  ALLOWED_CHAT_IDS    (optional)  comma-separated chat ids; empty = anyone can use it
  STATE_FILE          (optional)  default alerts.json
  LOCAL_TZ            (optional)  default Europe/Podgorica
"""

import os
import re
import json
import html
import time
import logging
from datetime import datetime

import requests
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("alertbot")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ALLOWED_CHAT_IDS = {s.strip() for s in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if s.strip()}
RUN_MODE = os.environ.get("RUN_MODE", "loop")
STATE_FILE = os.environ.get("STATE_FILE", "alerts.json")
LOCAL_TZ = pytz.timezone(os.environ.get("LOCAL_TZ") or "Europe/Podgorica")
MAX_ALERTS_PER_USER = 20
LOOP_SECONDS = 30
CB_API = "https://api.exchange.coinbase.com"
HTTP_HEADERS = {"User-Agent": "price-alert-bot/1.0"}

HELP = (
    "🔔 <b>Fiyat Alarm Botu</b>\n"
    "Belirlediğin fiyata gelince haber veririm. Kripto, ABD hisseleri ve Borsa İstanbul.\n\n"
    "<b>Alarm kur</b>\n"
    "/alarm BTC &gt; 70000 — 70.000$'ı geçince\n"
    "/alarm AAPL &lt; 180 — 180$'ın altına inince\n"
    "/alarm ETH %5 — şu anki fiyattan %5 yukarı ya da aşağı giderse\n"
    "/alarm THYAO.IS &gt; 350 — Borsa İstanbul (₺)\n\n"
    "<b>Diğer</b>\n"
    "/fiyat BTC — anlık fiyat\n"
    "/liste — alarmların\n"
    "/sil 2 — 2 numaralı alarmı sil · /sil hepsi\n\n"
    "<i>Bu bot sadece haber verir, yatırım tavsiyesi vermez.</i>"
)


# ---------------------------------------------------------------- helpers
def e(x):
    return html.escape(str(x), quote=False)


def read_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        s = {}
    s.setdefault("offset", 0)
    s.setdefault("next_id", 1)
    s.setdefault("alerts", [])
    return s


def write_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=1)
    except OSError as ex:
        log.error("State could not be saved: %s", ex)


def fmt_price(x, currency="$"):
    if x >= 1000:
        s = f"{x:,.0f}" if x >= 10000 else f"{x:,.2f}"
    elif x >= 1:
        s = f"{x:,.2f}" if x >= 100 else f"{x:,.3f}"
    else:
        s = f"{x:.6g}"
    return f"{s}{currency}" if currency == "₺" else f"{currency}{s}"


def parse_number(text):
    """'70000', '70.000', '70,000', '1.234,5', '0.1234', '70k', '$70,5' -> float (None if invalid).
    A single '.' followed by exactly 3 digits is read as a thousands separator ('70.000' = 70000),
    except after a leading 0 ('0.123' stays 0.123). The bot echoes what it understood, so a
    misread is visible immediately."""
    s = str(text).strip().lower().replace("$", "").replace("₺", "").replace(" ", "")
    mult = 1.0
    if s.endswith("k"):
        s, mult = s[:-1], 1000.0
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", ".") if len(parts) == 2 and len(parts[1]) != 3 else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        head, tail = s.split(".")
        if len(tail) == 3 and head not in ("", "0"):
            s = head + tail
    try:
        v = float(s) * mult
    except ValueError:
        return None
    return v if v > 0 else None


def normalize_symbol(sym):
    s = sym.strip().upper()
    for suffix in ("-USDT", "-USD", "/USDT", "/USD", "USDT"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    return s if re.fullmatch(r"[A-Z0-9.\-^=]{1,15}", s) else None


# ---------------------------------------------------------------- prices
_cache = {}


def crypto_price(sym):
    try:
        r = requests.get(f"{CB_API}/products/{sym}-USD/ticker", headers=HTTP_HEADERS, timeout=10)
        if r.ok:
            p = float(r.json().get("price") or 0)
            return p if p > 0 else None
    except Exception as ex:
        log.warning("Coinbase %s: %s", sym, ex)
    return None


def stock_price(sym):
    try:
        import yfinance as yf
        t = yf.Ticker(sym)
        p = None
        try:
            p = float(t.fast_info["last_price"])
        except Exception:
            pass
        if not p or p != p:
            hist = t.history(period="5d", interval="1d")
            p = float(hist["Close"].dropna().iloc[-1]) if hist is not None and len(hist) else None
        return p if p and p > 0 else None
    except Exception as ex:
        log.warning("Yahoo %s: %s", sym, ex)
        return None


def get_price(sym):
    """(price, currency, source) or None. Crypto first (Coinbase), then Yahoo."""
    if sym in _cache:
        return _cache[sym]
    res = None
    if "." not in sym:
        p = crypto_price(sym)
        if p:
            res = (p, "$", "crypto")
    if res is None:
        p = stock_price(sym)
        if p:
            res = (p, "₺" if sym.endswith(".IS") else "$", "stock")
    _cache[sym] = res
    return res


# ---------------------------------------------------------------- Telegram
def tg(method, **params):
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN missing — %s skipped", method)
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", data=params,
                          timeout=params.get("timeout", 0) + 15)
        data = r.json()
        if not data.get("ok"):
            log.error("Telegram %s failed: %s", method, str(data)[:200])
            return None
        return data.get("result")
    except Exception as ex:
        log.error("Telegram %s error: %s", method, ex)
        return None


def send(chat_id, text):
    res = tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if res is None:                                   # fall back to plain text
        res = tg("sendMessage", chat_id=chat_id, text=html.unescape(re.sub(r"<[^>]+>", "", text)))
    return res is not None


# ---------------------------------------------------------------- commands
def user_alerts(state, chat_id):
    return [a for a in state["alerts"] if a["chat_id"] == chat_id]


def describe(a):
    cur = a.get("currency", "$")
    if a["kind"] == "above":
        return f"{e(a['symbol'])} &gt; {fmt_price(a['level'], cur)}"
    if a["kind"] == "below":
        return f"{e(a['symbol'])} &lt; {fmt_price(a['level'], cur)}"
    return f"{e(a['symbol'])} ±%{a['pct']:g} ({fmt_price(a['ref'], cur)} fiyatından)"


def cmd_alarm(state, chat_id, args):
    args = re.sub(r"^\s*(\S+)\s+([0-9.,]+)\s*%\s*$", r"\1 %\2", args or "")   # "ETH 5%" -> "ETH %5"
    m = re.fullmatch(r"\s*(\S+)\s*(>|<|%|üstü|ustu|altı|alti|above|below)\s*([0-9.,$₺kK]+)\s*%?\s*", args or "")
    if not m:
        return ("Anlayamadım. Örnekler:\n/alarm BTC &gt; 70000\n/alarm AAPL &lt; 180\n/alarm ETH %5")
    sym = normalize_symbol(m.group(1))
    op = {"üstü": ">", "ustu": ">", "above": ">", "altı": "<", "alti": "<", "below": "<"}.get(m.group(2), m.group(2))
    num = parse_number(m.group(3))
    if not sym or num is None:
        return "Sembol ya da sayı hatalı. Örnek: /alarm BTC &gt; 70000"
    if len(user_alerts(state, chat_id)) >= MAX_ALERTS_PER_USER:
        return f"En fazla {MAX_ALERTS_PER_USER} alarm kurabilirsin. /liste ile bakıp /sil ile yer açabilirsin."
    quote = get_price(sym)
    if quote is None:
        return (f"<b>{e(sym)}</b> için fiyat bulamadım. Kripto için BTC, ETH; ABD hissesi için AAPL; "
                f"Borsa İstanbul için THYAO.IS gibi yaz.")
    price, cur, _ = quote
    alert = {"id": state["next_id"], "chat_id": chat_id, "symbol": sym, "currency": cur,
             "created": time.time()}
    if op == "%":
        if not 0.1 <= num <= 100:
            return "Yüzde 0,1 ile 100 arasında olmalı. Örnek: /alarm ETH %5"
        alert.update(kind="move", pct=num, ref=price)
    else:
        alert.update(kind="above" if op == ">" else "below", level=num)
        if (op == ">" and price >= num) or (op == "<" and price <= num):
            return (f"{e(sym)} zaten {fmt_price(price, cur)}; bu alarm hemen çalışırdı. "
                    f"Seviyeyi kontrol eder misin?")
    state["alerts"].append(alert)
    state["next_id"] += 1
    note = ""
    if alert["kind"] != "move" and (num > price * 3 or num < price / 3):
        note = "\n⚠️ Seviye şu anki fiyattan çok uzak; doğru yazdığından emin ol."
    return f"✅ Alarm kuruldu: {describe(alert)}\nŞu an: {fmt_price(price, cur)}{note}"


def cmd_list(state, chat_id):
    mine = user_alerts(state, chat_id)
    if not mine:
        return "Kurulu alarmın yok. Örnek: /alarm BTC &gt; 70000"
    lines = ["📋 <b>Alarmların</b>"]
    lines += [f"{i}. {describe(a)}" for i, a in enumerate(mine, 1)]
    lines.append("\nSilmek için: /sil 1")
    return "\n".join(lines)


def cmd_delete(state, chat_id, args):
    mine = user_alerts(state, chat_id)
    arg = (args or "").strip().lower()
    if arg in ("hepsi", "tümü", "tumu", "all"):
        state["alerts"] = [a for a in state["alerts"] if a["chat_id"] != chat_id]
        return f"🗑 {len(mine)} alarm silindi."
    if not arg.isdigit() or not 1 <= int(arg) <= len(mine):
        return "Hangi alarm? Önce /liste yaz, sonra örneğin /sil 1"
    target = mine[int(arg) - 1]
    state["alerts"] = [a for a in state["alerts"] if a["id"] != target["id"]]
    return f"🗑 Silindi: {describe(target)}"


def cmd_price(args):
    sym = normalize_symbol(args or "")
    if not sym:
        return "Örnek: /fiyat BTC"
    q = get_price(sym)
    if q is None:
        return f"<b>{e(sym)}</b> için fiyat bulamadım."
    return f"💱 <b>{e(sym)}</b>: {fmt_price(q[0], q[1])}"


COMMANDS = {
    "alarm": "alarm", "alert": "alarm", "liste": "list", "list": "list", "sil": "delete", "delete": "delete",
    "fiyat": "price", "price": "price", "yardim": "help", "yardım": "help", "help": "help", "start": "help",
}


def handle_message(state, chat_id, text):
    text = (text or "").strip()
    m = re.match(r"^/?([A-Za-zçğıöşüÇĞİÖŞÜ]+)(?:@\w+)?\s*(.*)$", text, re.S)
    cmd = COMMANDS.get(m.group(1).lower()) if m else None
    args = m.group(2) if m else ""
    if cmd == "alarm":
        return cmd_alarm(state, chat_id, args)
    if cmd == "list":
        return cmd_list(state, chat_id)
    if cmd == "delete":
        return cmd_delete(state, chat_id, args)
    if cmd == "price":
        return cmd_price(args)
    return HELP


def process_updates(state, timeout=0):
    updates = tg("getUpdates", offset=state["offset"] + 1, timeout=timeout,
                 allowed_updates=json.dumps(["message"])) or []
    for u in updates:
        state["offset"] = max(state["offset"], int(u.get("update_id", 0)))
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id, text = chat.get("id"), (msg.get("text") or "").strip()
        if chat_id is None or not text:
            continue
        if chat.get("type", "private") != "private" and not text.startswith("/"):
            continue                                   # in groups, only react to commands
        if ALLOWED_CHAT_IDS and str(chat_id) not in ALLOWED_CHAT_IDS:
            send(chat_id, "Bu bot özel kullanım için. Erişim için sahibine yaz.")
            continue
        try:
            reply = handle_message(state, chat_id, text)
        except Exception as ex:
            log.exception("Command failed: %s", ex)
            reply = "Bir hata oldu, biraz sonra tekrar dener misin?"
        send(chat_id, reply)
    return len(updates)


# ---------------------------------------------------------------- checking
def check_alerts(state):
    _cache.clear()
    fired, keep = 0, []
    now_local = datetime.now(LOCAL_TZ).strftime("%H:%M")
    for a in state["alerts"]:
        q = get_price(a["symbol"])
        if q is None:
            keep.append(a)
            continue
        price, cur = q[0], a.get("currency", q[1])
        hit, head = False, ""
        if a["kind"] == "above" and price >= a["level"]:
            hit, head = True, f"🔔 <b>{e(a['symbol'])}</b> {fmt_price(a['level'], cur)} seviyesini geçti!"
        elif a["kind"] == "below" and price <= a["level"]:
            hit, head = True, f"🔔 <b>{e(a['symbol'])}</b> {fmt_price(a['level'], cur)} seviyesinin altına indi!"
        elif a["kind"] == "move":
            chg = (price / a["ref"] - 1) * 100
            if abs(chg) >= a["pct"]:
                hit = True
                head = (f"🔔 <b>{e(a['symbol'])}</b> %{chg:+.1f} {'yükseldi' if chg > 0 else 'düştü'} "
                        f"({fmt_price(a['ref'], cur)} → {fmt_price(price, cur)})")
        if hit and send(a["chat_id"], f"{head}\nŞu an: {fmt_price(price, cur)} ({now_local})\n"
                                      f"<i>Alarm: {describe(a)} — silindi. Yenisi için /alarm</i>"):
            fired += 1
            continue
        keep.append(a)
    state["alerts"] = keep
    return fired


# ---------------------------------------------------------------- main
def run_once():
    state = read_state()
    try:
        process_updates(state)
        fired = check_alerts(state)
        log.info("Alerts: %d active, %d fired", len(state["alerts"]), fired)
    finally:
        write_state(state)


def run_loop():
    state = read_state()
    last_check = 0.0
    log.info("Loop mode started")
    while True:
        try:
            if process_updates(state, timeout=LOOP_SECONDS):
                write_state(state)
            if time.time() - last_check >= LOOP_SECONDS:
                check_alerts(state)
                write_state(state)
                last_check = time.time()
        except Exception as ex:
            log.exception("Loop error: %s", ex)
            time.sleep(5)


if __name__ == "__main__":
    run_once() if RUN_MODE == "once" else run_loop()
