"""
Price Alert Bot for Telegram  (v2)
==================================

Users set price alerts with buttons or plain text; the bot watches prices and
messages them when a level is crossed. Crypto (Coinbase), US stocks, Borsa
Istanbul, gold, FX and TL prices (Yahoo Finance). It only notifies — no advice.

For users (Turkish UI, buttons everywhere):
  type  BTC              -> price
  type  BTC 70000        -> alert when BTC reaches 70,000 (direction is automatic)
  type  ETH %5           -> alert on a ±5% move
  type  altın 4500 / dolar 42 / THYAO 350 / BTCTRY 3000000
  buttons: 🔔 Alarm kur · 💱 Fiyat · 📋 Alarmlarım · 📊 Özet
  commands: /alarm /fiyat /liste /sil /ozet /yardim   (English aliases too)

For the owner (OWNER_CHAT_ID):
  /admin               stats + private-mode switch
  /duyuru <text>       message every user
  /izinver <id>, /izinkaldir <id>, /ozelmod ac|kapat
  new users and access requests arrive with ✅/❌ buttons

Environment:
  TELEGRAM_TOKEN   (required)
  OWNER_CHAT_ID    your chat id (admin panel + notifications)
  ALLOWED_CHAT_IDS comma list; if set, private mode starts ON
  RUN_MODE         once | loop (default loop)
  MAX_RUNTIME      seconds before loop mode exits (0 = never; GitHub uses ~600)
  BOT_TITLE        name shown in help (white-label), default "Fiyat Alarm Botu"
  POPULAR          quick-pick symbols, default BTC,ETH,SOL,GRAMALTIN,USDTRY,EURTRY,BIST100,THYAO.IS,AAPL
  SUMMARY_ASSETS   default BIST100,USDTRY,EURTRY,GRAMALTIN,BTC,ETH
  SUMMARY_TIME     default daily summary time, default 18:15
  LOCAL_TZ         default Europe/Istanbul
  STATE_FILE       default alerts.json
"""

import os
import re
import json
import html
import math
import time
import logging
from datetime import datetime

import requests
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("alertbot")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

VERSION = "2.0"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()
ENV_ALLOWED = {s.strip() for s in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if s.strip()}
RUN_MODE = os.environ.get("RUN_MODE", "loop")
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME") or 0)
STATE_FILE = os.environ.get("STATE_FILE", "alerts.json")
LOCAL_TZ = pytz.timezone(os.environ.get("LOCAL_TZ") or "Europe/Istanbul")
BOT_TITLE = os.environ.get("BOT_TITLE") or "Fiyat Alarm Botu"
POPULAR = [s.strip() for s in (os.environ.get("POPULAR") or
           "BTC,ETH,SOL,GRAMALTIN,USDTRY,EURTRY,BIST100,THYAO.IS,AAPL").split(",") if s.strip()]
SUMMARY_ASSETS = [s.strip() for s in (os.environ.get("SUMMARY_ASSETS") or
                  "BIST100,USDTRY,EURTRY,GRAMALTIN,BTC,ETH").split(",") if s.strip()]
SUMMARY_TIME = os.environ.get("SUMMARY_TIME") or "18:15"
NOTIFY_NEW_USERS = os.environ.get("NOTIFY_NEW_USERS", "1") != "0"

MAX_ALERTS_PER_CHAT = 20
CHECK_SECONDS = 30          # loop mode: how often prices are checked
REARM_PCT = 0.5             # repeating alert re-arms after price moves back this % past the level
PENDING_TTL = 600           # seconds a "type the price" question stays open
GRAMS_PER_OZ = 31.1035
CB_API = "https://api.exchange.coinbase.com"
HTTP_HEADERS = {"User-Agent": "price-alert-bot/2.0"}
BIST_MOVERS = ("AKBNK ASELS ASTOR BIMAS EKGYO ENKAI EREGL FROTO GARAN ISCTR KCHOL KONTR KRDMD MGROS "
               "OYAKC PETKM PGSUS SAHOL SASA SISE TAVHL TCELL THYAO TOASO TTKOM TUPRS ULKER YKBNK").split()

SPECIAL = {
    "GRAMALTIN": {"name": "Gram altın", "yahoo": "GC=F", "cur": "₺", "gram": True},
    "GRAMGUMUS": {"name": "Gram gümüş", "yahoo": "SI=F", "cur": "₺", "gram": True},
    "ONS":       {"name": "Ons altın", "yahoo": "GC=F", "cur": "$"},
    "USDTRY":    {"name": "Dolar/TL", "yahoo": "USDTRY=X", "cur": "₺"},
    "EURTRY":    {"name": "Euro/TL", "yahoo": "EURTRY=X", "cur": "₺"},
    "GBPTRY":    {"name": "Sterlin/TL", "yahoo": "GBPTRY=X", "cur": "₺"},
    "EURUSD":    {"name": "Euro/Dolar", "yahoo": "EURUSD=X", "cur": ""},
    "BIST100":   {"name": "BIST 100", "yahoo": "XU100.IS", "cur": ""},
    "BIST30":    {"name": "BIST 30", "yahoo": "XU030.IS", "cur": ""},
}
ALIASES = {
    "ALTIN": "GRAMALTIN", "GRAM": "GRAMALTIN", "GRAMALTIN": "GRAMALTIN", "GAU": "GRAMALTIN",
    "GUMUS": "GRAMGUMUS", "GRAMGUMUS": "GRAMGUMUS",
    "ONS": "ONS", "ONSALTIN": "ONS", "XAU": "ONS", "XAUUSD": "ONS",
    "DOLAR": "USDTRY", "USD": "USDTRY", "USDTRY": "USDTRY", "USDTL": "USDTRY",
    "EURO": "EURTRY", "AVRO": "EURTRY", "EUR": "EURTRY", "EURTRY": "EURTRY", "EURTL": "EURTRY",
    "STERLIN": "GBPTRY", "GBP": "GBPTRY", "GBPTRY": "GBPTRY",
    "PARITE": "EURUSD", "EURUSD": "EURUSD",
    "BIST": "BIST100", "BIST100": "BIST100", "XU100": "BIST100", "BIST30": "BIST30", "XU030": "BIST30",
}
TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

# bottom keyboard (private chats)
B_ALARM, B_PRICE, B_LIST, B_SUM, B_HELP = "🔔 Alarm kur", "💱 Fiyat", "📋 Alarmlarım", "📊 Özet", "❓ Yardım"
MAIN_KB = {"keyboard": [[B_ALARM, B_PRICE], [B_LIST, B_SUM], [B_HELP]],
           "resize_keyboard": True, "is_persistent": True}


def help_text(private=True):
    t = (f"🔔 <b>{html.escape(BOT_TITLE)}</b>\n"
         "Belirlediğin fiyata gelince haber veririm: kripto, ABD ve Borsa İstanbul hisseleri, altın ve döviz.\n\n")
    if private:
        t += ("<b>En kolayı:</b> alttaki butonları kullan ya da direkt yaz:\n"
              "• <code>BTC</code> → anlık fiyat\n"
              "• <code>BTC 70000</code> → 70.000$'a gelince haber ver\n"
              "• <code>altın 4500</code> · <code>dolar 42</code> · <code>THYAO 350</code>\n"
              "• <code>ETH %5</code> → %5 oynarsa haber ver\n"
              "• sonuna <code>tekrar</code> yazarsan alarm her geçişte çalışır\n\n")
    else:
        t += ("<b>Grupta:</b> aşağıdaki butonlar ya da komutlar\n"
              "• <code>/fiyat BTC</code> · <code>/alarm BTC 70000</code> · <code>/alarm altın 4500</code>\n\n")
    t += ("<b>Komutlar:</b> /alarm · /fiyat · /liste · /ozet · /yardim\n\n"
          "<i>Bu bot sadece haber verir, yatırım tavsiyesi vermez.</i>")
    return t


# ---------------------------------------------------------------- small helpers
def e(x):
    return html.escape(str(x), quote=False)


def now_local():
    return datetime.now(LOCAL_TZ)


def read_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        s = {}
    for k, v in (("offset", 0), ("next_id", 1), ("alerts", []), ("users", {}), ("pending", {}),
                 ("summaries", {}), ("allowed", []), ("private_mode", None), ("requests", {}),
                 ("stats", {"fired_total": 0, "day": "", "fired_today": 0}), ("cmds_v", "")):
        s.setdefault(k, v)
    if s["private_mode"] is None:
        s["private_mode"] = bool(ENV_ALLOWED)
    return s


def write_state(state):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, STATE_FILE)
    except OSError as ex:
        log.error("State could not be saved: %s", ex)


def fmt_num(x):
    if x >= 10000:
        return f"{x:,.0f}"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.3f}".rstrip("0").rstrip(".") if x < 10 else f"{x:,.2f}"
    return f"{x:.6g}"


def fmt_price(x, cur="$"):
    s = fmt_num(x)
    if cur == "₺":
        return f"{s}₺"
    return f"{cur}{s}"


def fmt_chg(c):
    if c is None:
        return ""
    arrow = "🟢" if c > 0.05 else ("🔴" if c < -0.05 else "⚪")
    return f"{arrow} %{c:+.1f}".replace("%+", "%+").replace("%-", "%−")


def nice_round(x):
    """Round to 4 significant digits: 66,321 -> 66,320 ; 4.3517 -> 4.352"""
    if x <= 0:
        return x
    m = 10 ** (math.floor(math.log10(x)) - 3)
    return round(round(x / m) * m, 10)


def parse_number(text):
    """'70000', '70.000', '70,000', '1.234,5', '0.1234', '70k', '$70,5' -> float (None if invalid)."""
    s = str(text).strip().lower().replace("$", "").replace("₺", "").replace("tl", "").replace(" ", "")
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
    s = str(sym).translate(TR_MAP).strip().upper().replace(" ", "").lstrip("$#")
    if s in ALIASES:
        return ALIASES[s]
    s = s.replace("-TRY", "TRY").replace("/TRY", "TRY")
    for suffix in ("-USDT", "-USD", "/USDT", "/USD", "USDT", "USD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    if s in ALIASES:
        return ALIASES[s]
    if not re.fullmatch(r"[A-Z0-9.\-^=]{1,15}", s) or not re.search(r"[A-Z]", s):
        return None
    return s


# ---------------------------------------------------------------- prices
_cache = {}


def crypto_raw(sym):
    """(last, open_24h) from Coinbase or None."""
    ck = ("cb", sym)
    if ck in _cache:
        return _cache[ck]
    res = None
    try:
        r = requests.get(f"{CB_API}/products/{sym}-USD/stats", headers=HTTP_HEADERS, timeout=10)
        if r.ok:
            d = r.json()
            last, opn = float(d.get("last") or 0), float(d.get("open") or 0)
            if last > 0:
                res = (last, opn if opn > 0 else None)
    except Exception as ex:
        log.warning("Coinbase %s: %s", sym, ex)
    _cache[ck] = res
    return res


def yahoo_raw(ticker):
    """(last, previous_close) from Yahoo Finance or None."""
    ck = ("yf", ticker)
    if ck in _cache:
        return _cache[ck]
    res = None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        last = prev = None
        try:
            fi = t.fast_info
            last = float(fi["last_price"])
            try:
                prev = float(fi["previous_close"])
            except Exception:
                prev = None
        except Exception:
            pass
        if not last or last != last:
            hist = t.history(period="5d", interval="1d")
            closes = hist["Close"].dropna() if hist is not None and len(hist) else []
            if len(closes):
                last = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        if last and last > 0 and last == last:
            res = (last, prev if prev and prev == prev and prev > 0 else None)
    except Exception as ex:
        log.warning("Yahoo %s: %s", ticker, ex)
    _cache[ck] = res
    return res


def _chg(raw):
    return (raw[0] / raw[1] - 1) * 100 if raw and raw[1] else None


def _combine(c1, c2):
    return None if c1 is None or c2 is None else ((1 + c1 / 100) * (1 + c2 / 100) - 1) * 100


def get_quote(sym):
    """dict(key, name, price, cur, chg) or None. Accepts user input or a stored key."""
    key = normalize_symbol(sym) if sym else None
    if not key:
        return None
    ck = ("q", key)
    if ck in _cache:
        return _cache[ck]
    q = None
    if key in SPECIAL:
        sp = SPECIAL[key]
        r = yahoo_raw(sp["yahoo"])
        if r:
            if sp.get("gram"):
                fx = yahoo_raw("USDTRY=X")
                if fx:
                    q = dict(key=key, name=sp["name"], price=r[0] * fx[0] / GRAMS_PER_OZ, cur="₺",
                             chg=_combine(_chg(r), _chg(fx)))
            else:
                q = dict(key=key, name=sp["name"], price=r[0], cur=sp["cur"], chg=_chg(r))
    elif key.endswith("TRY") and len(key) > 3 and "." not in key:
        base = get_quote(key[:-3])
        fx = yahoo_raw("USDTRY=X")
        if base and base["cur"] == "$" and fx:
            q = dict(key=key, name=f"{base['name']}/TL", price=base["price"] * fx[0], cur="₺",
                     chg=_combine(base["chg"], _chg(fx)))
    else:
        if not re.search(r"[.=^]", key):
            r = crypto_raw(key)
            if r:
                q = dict(key=key, name=key, price=r[0], cur="$", chg=_chg(r))
        if q is None:
            r = yahoo_raw(key)
            if r:
                q = dict(key=key, name=key.replace(".IS", ""), price=r[0],
                         cur="₺" if key.endswith(".IS") else "$", chg=_chg(r))
        if q is None and "." not in key:
            r = yahoo_raw(key + ".IS")
            if r:
                q = dict(key=key + ".IS", name=key, price=r[0], cur="₺", chg=_chg(r))
    _cache[ck] = q
    return q


def tl_equiv(q):
    if q["cur"] != "$":
        return ""
    fx = yahoo_raw("USDTRY=X")
    return f"\n≈ {fmt_price(q['price'] * fx[0], '₺')}" if fx else ""


# ---------------------------------------------------------------- Telegram
def tg(method, **params):
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN missing — %s skipped", method)
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=params,
                          timeout=params.get("timeout", 0) + 15)
        data = r.json()
        if not data.get("ok"):
            desc = str(data.get("description", data))
            if "not modified" in desc:
                return True
            log.error("Telegram %s failed: %s", method, desc[:200])
            return None
        return data.get("result")
    except Exception as ex:
        log.error("Telegram %s error: %s", method, ex)
        return None


def ikb(rows):
    """[[(text, data), ...], ...] -> inline keyboard"""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows if row]}


def send(chat_id, text, kb=None):
    p = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if kb:
        p["reply_markup"] = kb
    res = tg("sendMessage", **p)
    if res is None:
        p.pop("parse_mode")
        p["text"] = html.unescape(re.sub(r"<[^>]+>", "", text))
        res = tg("sendMessage", **p)
    return res is not None


def edit(chat_id, message_id, text, kb=None):
    p = dict(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
             disable_web_page_preview=True)
    if kb:
        p["reply_markup"] = kb
    if tg("editMessageText", **p) is None:
        send(chat_id, text, kb)


def is_group_admin(chat_id, user_id):
    if OWNER_CHAT_ID and str(user_id) == OWNER_CHAT_ID:
        return True
    m = tg("getChatMember", chat_id=chat_id, user_id=user_id)
    return bool(m) and m.get("status") in ("creator", "administrator")


def set_commands(state):
    if state.get("cmds_v") == VERSION:
        return
    ok = tg("setMyCommands", commands=[
        {"command": "alarm", "description": "Alarm kur"},
        {"command": "fiyat", "description": "Anlık fiyat"},
        {"command": "liste", "description": "Alarmlarım"},
        {"command": "ozet", "description": "Günlük piyasa özeti"},
        {"command": "yardim", "description": "Nasıl kullanılır"},
    ])
    if ok:
        state["cmds_v"] = VERSION


# ---------------------------------------------------------------- views
def asset_picker(prefix):
    rows, row = [], []
    for s in POPULAR:
        key = normalize_symbol(s)
        if not key:
            continue
        label = SPECIAL[key]["name"] if key in SPECIAL else key.replace(".IS", "")
        row.append((label, f"{prefix}|{key}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    rows.append(row)
    rows.append([("✏️ Başka bir şey yazacağım", f"{prefix}|*")])
    return ikb(rows)


def price_view(q):
    text = f"💱 <b>{e(q['name'])}</b>: {fmt_price(q['price'], q['cur'])}"
    if q["chg"] is not None:
        text += f"  {fmt_chg(q['chg'])} <i>(günlük)</i>"
    text += tl_equiv(q)
    kb = ikb([[("🔔 Alarm kur", f"aa|{q['key']}"), ("🔄 Yenile", f"pq|{q['key']}")]])
    return text, kb


def level_picker(q):
    p, cur, k = q["price"], q["cur"], q["key"]
    text = (f"<b>{e(q['name'])}</b> şu an {fmt_price(p, cur)}"
            + (f" ({fmt_chg(q['chg'])} bugün)" if q["chg"] is not None else "")
            + "\nNe zaman haber vereyim?")
    up = [(f"📈 +%{n} → {fmt_price(nice_round(p * (1 + n / 100)), cur)}", f"al|{k}|u|{n}") for n in (2, 5, 10)]
    dn = [(f"📉 −%{n} → {fmt_price(nice_round(p * (1 - n / 100)), cur)}", f"al|{k}|d|{n}") for n in (2, 5, 10)]
    kb = ikb([up[:2], [up[2], dn[0]], dn[1:],
              [("↕️ %3 oynarsa", f"am|{k}|3"), ("↕️ %5 oynarsa", f"am|{k}|5")],
              [("✏️ Fiyatı ben yazacağım", f"aw|{k}")]])
    return text, kb


def describe(a):
    cur, name = a.get("currency", "$"), e(a.get("name") or a["symbol"])
    rep = "🔁 " if a.get("repeat") else ""
    if a["kind"] == "above":
        return f"{rep}{name} ≥ {fmt_price(a['level'], cur)}"
    if a["kind"] == "below":
        return f"{rep}{name} ≤ {fmt_price(a['level'], cur)}"
    return f"{rep}{name} ±%{a['pct']:g} ({fmt_price(a['ref'], cur)} fiyatından)"


def alert_kb(a):
    return ikb([[("1️⃣ Tek seferlik yap" if a.get("repeat") else "🔁 Her geçişte haber ver", f"rp|{a['id']}"),
                 ("🗑 İptal", f"dl|{a['id']}")]])


def user_alerts(state, chat_id):
    return [a for a in state["alerts"] if a["chat_id"] == chat_id]


def list_view(state, chat_id):
    mine = user_alerts(state, chat_id)
    if not mine:
        return ("Kurulu alarmın yok.\nKurmak için <b>🔔 Alarm kur</b> butonuna bas ya da "
                "<code>BTC 70000</code> gibi yaz.", ikb([[("➕ Alarm kur", "m|alarm")]]))
    lines = [f"📋 <b>Alarmların</b> ({len(mine)})"] + [f"{i}. {describe(a)}" for i, a in enumerate(mine, 1)]
    lines.append("\n<i>Silmek için numarasına bas.</i>")
    btns = [(f"🗑 {i}", f"dl|{a['id']}|L") for i, a in enumerate(mine, 1)]
    rows = [btns[i:i + 5] for i in range(0, len(btns), 5)]
    rows.append([("🗑 Hepsini sil", "dla"), ("➕ Yeni alarm", "m|alarm")])
    return "\n".join(lines), ikb(rows)


def summary_kb(state, chat_id):
    sub = state["summaries"].get(str(chat_id))
    if sub:
        return ikb([[(f"🔕 Günlük özeti durdur ({sub['time']})", "ss|off")]])
    return ikb([[(f"🔔 Her gün {SUMMARY_TIME}'da gönder", "ss|on")]])


def build_summary():
    now = now_local()
    lines = [f"📊 <b>Piyasa özeti</b> · {now.strftime('%d.%m.%Y %H:%M')}", ""]
    for s in SUMMARY_ASSETS:
        q = get_quote(s)
        if q:
            lines.append(f"{e(q['name'])}: <b>{fmt_price(q['price'], q['cur'])}</b>  {fmt_chg(q['chg'])}")
    if "BIST100" in [normalize_symbol(s) for s in SUMMARY_ASSETS]:
        movers = []
        for t in BIST_MOVERS:
            c = _chg(yahoo_raw(t + ".IS"))
            if c is not None:
                movers.append((c, t))
        if len(movers) >= 5:
            movers.sort(reverse=True)
            up = " · ".join(f"{t} %{c:+.1f}" for c, t in movers[:3] if c > 0)
            dn = " · ".join(f"{t} %{c:+.1f}" for c, t in movers[::-1][:3] if c < 0)
            lines.append("")
            if up:
                lines.append(f"🚀 <b>Büyük hisselerde yükselenler:</b> {up}")
            if dn:
                lines.append(f"🔻 <b>Düşenler:</b> {dn}")
    lines.append("\n<i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>")
    return "\n".join(lines)


def admin_view(state):
    users = state["users"]
    groups = sum(1 for u in users.values() if u.get("type") != "private")
    st = state["stats"]
    rep = sum(1 for a in state["alerts"] if a.get("repeat"))
    text = (f"🛠 <b>Yönetim paneli</b> · v{VERSION}\n\n"
            f"👥 Kullanıcı: <b>{len(users) - groups}</b> kişi, <b>{groups}</b> grup\n"
            f"🔔 Aktif alarm: <b>{len(state['alerts'])}</b> ({rep} tekrarlı)\n"
            f"📊 Günlük özet abonesi: <b>{len(state['summaries'])}</b>\n"
            f"✅ Tetiklenen alarm: bugün <b>{st.get('fired_today', 0)}</b>, toplam <b>{st.get('fired_total', 0)}</b>\n"
            f"🔒 Özel mod: <b>{'AÇIK' if state['private_mode'] else 'kapalı'}</b>"
            f" (izinli: {len(set(state['allowed']) | ENV_ALLOWED)})\n\n"
            "<b>Komutlar</b>\n"
            "/duyuru metin — herkese mesaj\n"
            "/izinver 12345 · /izinkaldir 12345\n"
            "/ozelmod ac · /ozelmod kapat")
    kb = ikb([[("🔒 Özel modu kapat" if state["private_mode"] else "🔒 Özel modu aç", "ad|pm"),
               ("🔄 Yenile", "ad|st")]])
    return text, kb


# ---------------------------------------------------------------- actions
def parse_alarm_args(args):
    """-> (symbol_text, kind, value, repeat) or None. kind: above | below | auto | move"""
    s = (args or "").strip()
    repeat = False
    s2 = re.sub(r"\s*\b(tekrar\w*|repeat|her\s*seferinde)\b\s*", " ", s, flags=re.I).strip()
    if s2 != s:
        repeat, s = True, s2
    s = re.sub(r"^(.+?)\s+([0-9.,]+)\s*%\s*$", r"\1 %\2", s)            # "ETH 5%" -> "ETH %5"
    m = re.fullmatch(r"(.+?)\s*(>=|<=|>|<|%|üstü|ustu|üstüne|ustune|altı|alti|altına|altina|above|below)?"
                     r"\s*(\$?[0-9][0-9.,]*\s*[kK]?)\s*(?:tl|TL|₺|\$)?", s)
    if not m:
        return None
    op = (m.group(2) or "").lower()
    kind = {">": "above", ">=": "above", "üstü": "above", "ustu": "above", "üstüne": "above", "ustune": "above",
            "above": "above", "<": "below", "<=": "below", "altı": "below", "alti": "below", "altına": "below",
            "altina": "below", "below": "below", "%": "move"}.get(op, "auto")
    val = parse_number(m.group(3))
    if val is None:
        return None
    return m.group(1).strip(), kind, val, repeat


def add_alert(state, chat_id, sym, kind, value, repeat=False):
    """-> (text, kb)"""
    if len(user_alerts(state, chat_id)) >= MAX_ALERTS_PER_CHAT:
        return (f"En fazla {MAX_ALERTS_PER_CHAT} alarm kurabilirsin. Yer açmak için 📋 Alarmlarım.",
                ikb([[("📋 Alarmlarım", "m|list")]]))
    q = get_quote(sym)
    if q is None:
        return (f"<b>{e(sym)}</b> için fiyat bulamadım.\nÖrnekler: BTC, ETH, AAPL, THYAO, altın, dolar",
                None)
    price, cur = q["price"], q["cur"]
    a = {"id": state["next_id"], "chat_id": chat_id, "symbol": q["key"], "name": q["name"], "currency": cur,
         "created": time.time(), "repeat": bool(repeat), "armed": True, "fired": 0}
    if kind == "move":
        if not 0.1 <= value <= 100:
            return "Yüzde 0,1 ile 100 arasında olmalı. Örnek: <code>ETH %5</code>", None
        a.update(kind="move", pct=value, ref=price)
    else:
        if kind == "auto":
            if abs(value / price - 1) < 0.0005:
                return (f"{e(q['name'])} zaten {fmt_price(price, cur)} civarında. "
                        f"Biraz daha yukarı ya da aşağı bir seviye yazar mısın?", None)
            kind = "above" if value > price else "below"
        if (kind == "above" and price >= value) or (kind == "below" and price <= value):
            return (f"{e(q['name'])} zaten {fmt_price(price, cur)}; bu alarm hemen çalışırdı. "
                    f"Seviyeyi kontrol eder misin?", None)
        a.update(kind=kind, level=value)
    state["alerts"].append(a)
    state["next_id"] += 1
    note = ""
    if a["kind"] != "move" and (value > price * 3 or value < price / 3):
        note = "\n⚠️ Seviye şu anki fiyattan çok uzak; doğru yazdığından emin ol."
    return f"✅ <b>Alarm kuruldu:</b> {describe(a)}\nŞu an: {fmt_price(price, cur)}{note}", alert_kb(a)


def set_pending(state, chat_id, action, symbol=None):
    state["pending"][str(chat_id)] = {"action": action, "symbol": symbol, "ts": time.time()}


def pop_pending(state, chat_id):
    p = state["pending"].pop(str(chat_id), None)
    return p if p and time.time() - p.get("ts", 0) < PENDING_TTL else None


def reply_price(chat_id, sym):
    q = get_quote(sym)
    if q is None:
        send(chat_id, f"<b>{e(sym)}</b> için fiyat bulamadım.\nÖrnekler: BTC, ETH, AAPL, THYAO, altın, dolar")
        return
    send(chat_id, *price_view(q))


def reply_help(chat_id, private):
    if private:
        send(chat_id, help_text(True), MAIN_KB)
    else:
        send(chat_id, help_text(False), ikb([[("🔔 Alarm kur", "m|alarm"), ("💱 Fiyat", "m|price")],
                                             [("📋 Alarmlar", "m|list"), ("📊 Özet", "m|sum")]]))


def menu_action(state, chat_id, what, private=True):
    if what == "alarm":
        send(chat_id, "🔔 Hangisi için alarm kuralım?", asset_picker("aa"))
    elif what == "price":
        send(chat_id, "💱 Hangisinin fiyatına bakalım?", asset_picker("pa"))
    elif what == "list":
        send(chat_id, *list_view(state, chat_id))
    elif what == "sum":
        send(chat_id, build_summary(), summary_kb(state, chat_id))
    else:
        reply_help(chat_id, private)


def subscribe_summary(state, chat_id, on, hhmm=None):
    cid = str(chat_id)
    if not on:
        state["summaries"].pop(cid, None)
        return "🔕 Günlük özet kapatıldı."
    hhmm = hhmm or SUMMARY_TIME
    now = now_local()
    state["summaries"][cid] = {"time": hhmm,
                               "last": now.strftime("%Y-%m-%d") if now.strftime("%H:%M") >= hhmm else ""}
    return f"🔔 Günlük özet açıldı: her gün <b>{hhmm}</b>'da gönderirim.\nKapatmak için: /ozet kapat"


BUTTON_TEXTS = {B_ALARM: "alarm", B_PRICE: "price", B_LIST: "list", B_SUM: "sum", B_HELP: "help"}
COMMANDS = {
    "alarm": "alarm", "alert": "alarm", "fiyat": "price", "price": "price", "liste": "list", "list": "list",
    "alarmlar": "list", "sil": "delete", "delete": "delete", "ozet": "sum", "özet": "sum", "summary": "sum",
    "yardim": "help", "yardım": "help", "help": "help", "start": "help", "menu": "help", "menü": "help",
    "id": "id", "admin": "admin", "duyuru": "broadcast", "izinver": "allow", "izinkaldir": "disallow", "ozelmod": "pmode",
}


def handle_text(state, ctx, text):
    chat_id, private = ctx["chat_id"], ctx["type"] == "private"
    if not text.startswith("/"):
        if not private:
            return
        if text in BUTTON_TEXTS:
            pop_pending(state, chat_id)
            return menu_action(state, chat_id, BUTTON_TEXTS[text])
        p = pop_pending(state, chat_id)
        if p and p["action"] == "alarm_level":
            if "%" in text:
                v = parse_number(text.replace("%", ""))
                kind = "move"
            else:
                v, kind = parse_number(text), "auto"
                if v is None:
                    parsed = parse_alarm_args(f"{p['symbol']} {text}")
                    if parsed:
                        _, kind, v, _ = parsed
            if v is None:
                set_pending(state, chat_id, "alarm_level", p["symbol"])
                return send(chat_id, "Sadece fiyatı yaz, örneğin <code>70000</code> ya da <code>%5</code>")
            return send(chat_id, *add_alert(state, chat_id, p["symbol"], kind, v,
                                            repeat=bool(re.search(r"tekrar", text, re.I))))
        if p and p["action"] == "alarm_sym":
            parsed = parse_alarm_args(text)
            if parsed:
                s, kind, v, rep = parsed
                return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
            q = get_quote(text)
            if not q:
                return send(chat_id, f"<b>{e(text)}</b> bulunamadı. Örnek: SOL, TSLA, ASELS, altın")
            return send(chat_id, *level_picker(q))
        if p and p["action"] == "price_sym":
            return reply_price(chat_id, text)
        parsed = parse_alarm_args(text) if re.search(r"\d", text) else None
        if parsed:
            s, kind, v, rep = parsed
            return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
        if normalize_symbol(text) and len(text) <= 20:
            return reply_price(chat_id, text)
        return send(chat_id, "Anlayamadım 🙂 Örnek: <code>BTC</code> ya da <code>BTC 70000</code>", MAIN_KB)

    m = re.match(r"^/([A-Za-zçğıöşüÇĞİÖŞÜ]+)(?:@\w+)?\s*(.*)$", text, re.S)
    cmd = COMMANDS.get(m.group(1).lower()) if m else None
    args = (m.group(2) if m else "").strip()
    is_owner = bool(OWNER_CHAT_ID) and str(ctx["user_id"]) == OWNER_CHAT_ID
    if cmd == "alarm":
        if not args:
            return menu_action(state, chat_id, "alarm")
        parsed = parse_alarm_args(args)
        if not parsed:
            return send(chat_id, "Anlayamadım. Örnekler:\n<code>/alarm BTC 70000</code>\n"
                                 "<code>/alarm altın 4500</code>\n<code>/alarm ETH %5</code>")
        s, kind, v, rep = parsed
        return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
    if cmd == "price":
        return reply_price(chat_id, args) if args else menu_action(state, chat_id, "price")
    if cmd == "list":
        return menu_action(state, chat_id, "list")
    if cmd == "delete":
        mine = user_alerts(state, chat_id)
        a = args.lower()
        if a in ("hepsi", "tümü", "tumu", "all"):
            state["alerts"] = [x for x in state["alerts"] if x["chat_id"] != chat_id]
            return send(chat_id, f"🗑 {len(mine)} alarm silindi.")
        if not a.isdigit() or not 1 <= int(a) <= len(mine):
            return send(chat_id, *list_view(state, chat_id))
        target = mine[int(a) - 1]
        state["alerts"] = [x for x in state["alerts"] if x["id"] != target["id"]]
        return send(chat_id, f"🗑 Silindi: {describe(target)}")
    if cmd == "sum":
        parts = args.lower().split()
        if parts and parts[0] in ("ac", "aç", "on"):
            if not private and not is_group_admin(chat_id, ctx["user_id"]):
                return send(chat_id, "Günlük özeti sadece grup yöneticileri açıp kapatabilir.")
            hhmm = parts[1] if len(parts) > 1 and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", parts[1]) else None
            return send(chat_id, subscribe_summary(state, chat_id, True, hhmm))
        if parts and parts[0] in ("kapat", "off"):
            if not private and not is_group_admin(chat_id, ctx["user_id"]):
                return send(chat_id, "Günlük özeti sadece grup yöneticileri açıp kapatabilir.")
            return send(chat_id, subscribe_summary(state, chat_id, False))
        return menu_action(state, chat_id, "sum")
    if cmd == "id":
        return send(chat_id, f"🆔 Bu sohbetin id'si: <code>{chat_id}</code>"
                             + (f"\nSenin kullanıcı id'n: <code>{ctx['user_id']}</code>" if not private else ""))
    if cmd in ("admin", "broadcast", "allow", "disallow", "pmode"):
        if not is_owner:
            return reply_help(chat_id, private)
        if cmd == "admin":
            return send(chat_id, *admin_view(state))
        if cmd == "broadcast":
            if not args:
                return send(chat_id, "Kullanım: /duyuru Yeni özellik geldi! ...")
            ok = sum(send(int(cid), f"📢 {e(args)}") for cid in list(state["users"]))
            return send(chat_id, f"📢 Duyuru {ok}/{len(state['users'])} sohbete gönderildi.")
        if cmd in ("allow", "disallow"):
            if not re.fullmatch(r"-?\d+", args):
                return send(chat_id, "Kullanım: /izinver 123456789")
            allowed = set(state["allowed"])
            (allowed.add if cmd == "allow" else allowed.discard)(args)
            state["allowed"] = sorted(allowed)
            if cmd == "allow":
                state["requests"].pop(args, None)
                send(int(args), "✅ Erişimin açıldı! Başlamak için /start")
            return send(chat_id, f"{'✅ İzin verildi' if cmd == 'allow' else '🚫 İzin kaldırıldı'}: {args}")
        if cmd == "pmode":
            state["private_mode"] = args.lower() in ("ac", "aç", "on")
            return send(chat_id, *admin_view(state))
    return reply_help(chat_id, private)


def handle_callback(state, cb):
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id, mid = chat.get("id"), msg.get("message_id")
    user_id = (cb.get("from") or {}).get("id")
    private = chat.get("type", "private") == "private"
    is_owner = bool(OWNER_CHAT_ID) and str(user_id) == OWNER_CHAT_ID
    parts = data.split("|")
    op = parts[0]
    toast = None

    if op == "m":
        menu_action(state, chat_id, parts[1], private)
    elif op in ("aa", "pa"):
        if parts[1] == "*" and not private:
            send(chat_id, "Grupta yazarak kullan: <code>/fiyat SOL</code> · <code>/alarm SOL 150</code>")
        elif parts[1] == "*":
            set_pending(state, chat_id, "alarm_sym" if op == "aa" else "price_sym")
            send(chat_id, "✏️ Yaz bakalım: örneğin <code>SOL</code>, <code>TSLA</code>, <code>ASELS</code>, "
                          "<code>gümüş</code>, <code>BTCTRY</code>")
        else:
            q = get_quote(parts[1])
            if not q:
                toast = "Fiyat şu an alınamadı, biraz sonra dene"
            elif op == "aa":
                send(chat_id, *level_picker(q))
            else:
                send(chat_id, *price_view(q))
    elif op == "pq":
        q = get_quote(parts[1])
        if q:
            edit(chat_id, mid, *price_view(q))
            toast = "Güncellendi"
        else:
            toast = "Fiyat şu an alınamadı"
    elif op == "al":
        q = get_quote(parts[1])
        if q:
            n = float(parts[3])
            level = nice_round(q["price"] * (1 + n / 100 if parts[2] == "u" else 1 - n / 100))
            send(chat_id, *add_alert(state, chat_id, parts[1], "above" if parts[2] == "u" else "below", level))
        else:
            toast = "Fiyat şu an alınamadı"
    elif op == "am":
        send(chat_id, *add_alert(state, chat_id, parts[1], "move", float(parts[2])))
    elif op == "aw" and not private:
        send(chat_id, f"Grupta yazarak kur: <code>/alarm {e(parts[1].replace('.IS', ''))} 12345</code>")
    elif op == "aw":
        q = get_quote(parts[1])
        set_pending(state, chat_id, "alarm_level", parts[1])
        now_s = f" (şu an {fmt_price(q['price'], q['cur'])})" if q else ""
        send(chat_id, f"✏️ <b>{e(q['name'] if q else parts[1])}</b> için fiyatı yaz{now_s}.\n"
                      f"Örnek: <code>70000</code> ya da <code>%5</code>")
    elif op == "re":
        kind = {"a": "above", "b": "below", "m": "move"}[parts[2]]
        send(chat_id, *add_alert(state, chat_id, parts[1], kind, float(parts[3])))
    elif op == "rp":
        a = next((x for x in state["alerts"] if x["id"] == int(parts[1]) and x["chat_id"] == chat_id), None)
        if a:
            a["repeat"], a["armed"] = not a.get("repeat"), True
            edit(chat_id, mid, f"✅ <b>Alarm:</b> {describe(a)}\n"
                               + ("🔁 Fiyat her seviyeyi geçtiğinde haber vereceğim." if a["repeat"]
                                  else "1️⃣ Bir kez haber verip silinecek."), alert_kb(a))
        else:
            toast = "Bu alarm artık yok"
    elif op == "dl":
        before = len(state["alerts"])
        state["alerts"] = [x for x in state["alerts"] if not (x["id"] == int(parts[1]) and x["chat_id"] == chat_id)]
        toast = "🗑 Silindi" if len(state["alerts"]) < before else "Bu alarm zaten yok"
        if len(parts) > 2:
            edit(chat_id, mid, *list_view(state, chat_id))
        else:
            edit(chat_id, mid, "🗑 Alarm iptal edildi.")
    elif op == "dla":
        n = len(user_alerts(state, chat_id))
        state["alerts"] = [x for x in state["alerts"] if x["chat_id"] != chat_id]
        edit(chat_id, mid, f"🗑 {n} alarm silindi.", ikb([[("➕ Yeni alarm", "m|alarm")]]))
    elif op == "ss":
        if not private and not is_group_admin(chat_id, user_id):
            toast = "Bunu sadece grup yöneticileri değiştirebilir"
        else:
            send(chat_id, subscribe_summary(state, chat_id, parts[1] == "on"))
    elif op in ("ok", "no") and is_owner:
        cid = parts[1]
        if op == "ok":
            state["allowed"] = sorted(set(state["allowed"]) | {cid})
            state["requests"].pop(cid, None)
            send(int(cid), "✅ Erişimin açıldı! Başlamak için /start")
            edit(chat_id, mid, f"✅ İzin verildi: {cid}")
        else:
            state["requests"][cid] = "denied"
            send(int(cid), "Erişim isteğin şu an kabul edilmedi.")
            edit(chat_id, mid, f"❌ Reddedildi: {cid}")
    elif op == "ad" and is_owner:
        if parts[1] == "pm":
            state["private_mode"] = not state["private_mode"]
        edit(chat_id, mid, *admin_view(state))
    tg("answerCallbackQuery", callback_query_id=cb.get("id"), **({"text": toast} if toast else {}))


# ---------------------------------------------------------------- access + updates
def allowed(state, chat_id, user_id):
    if OWNER_CHAT_ID and OWNER_CHAT_ID in (str(chat_id), str(user_id)):
        return True
    if not state["private_mode"]:
        return True
    return str(chat_id) in (set(state["allowed"]) | ENV_ALLOWED)


def who(user, chat):
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or chat.get("title") or "?"
    if user.get("username"):
        name += f" (@{user['username']})"
    if chat.get("type") != "private":
        name += f" · grup: {chat.get('title', '')}"
    return name


def register(state, chat, user):
    cid = str(chat["id"])
    if cid in state["users"]:
        return
    state["users"][cid] = {"name": who(user, chat), "type": chat.get("type", "private"), "since": int(time.time())}
    if NOTIFY_NEW_USERS and OWNER_CHAT_ID and cid != OWNER_CHAT_ID:
        send(OWNER_CHAT_ID, f"👤 Yeni kullanıcı: {e(state['users'][cid]['name'])}\nid: <code>{cid}</code>")


def deny(state, chat, user):
    cid = str(chat["id"])
    if state["requests"].get(cid) == "denied":
        return
    first = cid not in state["requests"]
    state["requests"][cid] = "pending"
    if first:
        send(chat["id"], "🔒 Bu bot şu an özel kullanımda. Erişim isteğin bot sahibine iletildi.")
        if OWNER_CHAT_ID:
            send(OWNER_CHAT_ID, f"🔑 Erişim isteği: {e(who(user, chat))}\nid: <code>{cid}</code>",
                 ikb([[("✅ İzin ver", f"ok|{cid}"), ("❌ Reddet", f"no|{cid}")]]))


def process_updates(state, timeout=0):
    updates = tg("getUpdates", offset=state["offset"] + 1, timeout=timeout,
                 allowed_updates=["message", "callback_query"]) or []
    for u in updates:
        state["offset"] = max(state["offset"], int(u.get("update_id", 0)))
        try:
            if "callback_query" in u:
                cb = u["callback_query"]
                chat = (cb.get("message") or {}).get("chat") or {}
                user = cb.get("from") or {}
                if chat.get("id") is None:
                    continue
                if not allowed(state, chat["id"], user.get("id")):
                    tg("answerCallbackQuery", callback_query_id=cb.get("id"), text="Erişim yok")
                    continue
                handle_callback(state, cb)
                continue
            msg = u.get("message") or {}
            chat, user = msg.get("chat") or {}, msg.get("from") or {}
            text = (msg.get("text") or "").strip()
            if chat.get("id") is None or not text:
                continue
            ctx = {"chat_id": chat["id"], "user_id": user.get("id"), "type": chat.get("type", "private")}
            if ctx["type"] != "private" and not text.startswith("/"):
                continue                                   # in groups, only react to commands
            if not allowed(state, chat["id"], user.get("id")):
                deny(state, chat, user)
                continue
            register(state, chat, user)
            handle_text(state, ctx, text)
        except Exception as ex:
            log.exception("Update failed: %s", ex)
            try:
                cid = ((u.get("message") or {}).get("chat") or {}).get("id") or \
                      (((u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")
                if cid:
                    send(cid, "Bir hata oldu, biraz sonra tekrar dener misin?")
            except Exception:
                pass
    return len(updates)


# ---------------------------------------------------------------- checking
def check_alerts(state):
    _cache.clear()
    fired, keep = 0, []
    now = now_local()
    today = now.strftime("%Y-%m-%d")
    st = state["stats"]
    if st.get("day") != today:
        st["day"], st["fired_today"] = today, 0
    for a in state["alerts"]:
        q = get_quote(a["symbol"])
        if q is None:
            keep.append(a)
            continue
        price, cur = q["price"], a.get("currency", q["cur"])
        if a.get("repeat") and not a.get("armed", True):
            lvl = a.get("level")
            if a["kind"] == "above" and price <= lvl * (1 - REARM_PCT / 100):
                a["armed"] = True
            elif a["kind"] == "below" and price >= lvl * (1 + REARM_PCT / 100):
                a["armed"] = True
            keep.append(a)
            continue
        head = None
        name = e(a.get("name") or a["symbol"])
        if a["kind"] == "above" and price >= a["level"]:
            head = f"🔔 <b>{name}</b> {fmt_price(a['level'], cur)} seviyesine ulaştı! 📈"
        elif a["kind"] == "below" and price <= a["level"]:
            head = f"🔔 <b>{name}</b> {fmt_price(a['level'], cur)} seviyesine indi! 📉"
        elif a["kind"] == "move":
            chg = (price / a["ref"] - 1) * 100
            if abs(chg) >= a["pct"]:
                head = (f"🔔 <b>{name}</b> %{chg:+.1f} {'yükseldi 📈' if chg > 0 else 'düştü 📉'}\n"
                        f"{fmt_price(a['ref'], cur)} → {fmt_price(price, cur)}")
        if not head:
            keep.append(a)
            continue
        text = f"{head}\nŞu an: <b>{fmt_price(price, cur)}</b> ({now.strftime('%H:%M')})\n"
        if a.get("repeat"):
            text += "<i>🔁 Tekrarlı alarm: yine geçerse yine haber vereceğim.</i>"
            kb = ikb([[("🗑 Alarmı sil", f"dl|{a['id']}"), ("💱 Fiyat", f"pq|{a['symbol']}")]])
        else:
            text += "<i>Alarm tamamlandı ve silindi.</i>"
            k = {"above": "a", "below": "b", "move": "m"}[a["kind"]]
            v = a["pct"] if a["kind"] == "move" else a["level"]
            kb = ikb([[("🔁 Aynısını tekrar kur", f"re|{a['symbol']}|{k}|{v:g}"),
                       ("💱 Fiyat", f"pq|{a['symbol']}")]])
        if not send(a["chat_id"], text, kb):
            keep.append(a)
            continue
        fired += 1
        st["fired_today"] = st.get("fired_today", 0) + 1
        st["fired_total"] = st.get("fired_total", 0) + 1
        if a.get("repeat"):
            a["fired"] = a.get("fired", 0) + 1
            if a["kind"] == "move":
                a["ref"] = price
            else:
                a["armed"] = False
            keep.append(a)
    state["alerts"] = keep
    return fired


def maybe_send_summaries(state):
    now = now_local()
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    due = [cid for cid, s in state["summaries"].items() if s.get("last") != today and hhmm >= s.get("time", "99")]
    if not due:
        return 0
    text = build_summary()
    for cid in due:
        send(int(cid), text, summary_kb(state, int(cid)))
        state["summaries"][cid]["last"] = today
    return len(due)


# ---------------------------------------------------------------- main
def run_once():
    state = read_state()
    try:
        set_commands(state)
        process_updates(state)
        fired = check_alerts(state)
        maybe_send_summaries(state)
        log.info("Alerts: %d active, %d fired, users %d", len(state["alerts"]), fired, len(state["users"]))
    finally:
        write_state(state)


def run_loop(max_runtime=MAX_RUNTIME):
    state = read_state()
    start, last_check = time.time(), 0.0
    set_commands(state)
    log.info("Loop mode started (max runtime %ss)", max_runtime or "∞")
    try:
        while True:
            left = max_runtime - (time.time() - start) if max_runtime else 1e9
            if left <= 3:
                break
            try:
                _cache.clear()
                if process_updates(state, timeout=int(max(1, min(25, left - 3)))):
                    write_state(state)
                if time.time() - last_check >= CHECK_SECONDS:
                    check_alerts(state)
                    maybe_send_summaries(state)
                    write_state(state)
                    last_check = time.time()
            except Exception as ex:
                log.exception("Loop error: %s", ex)
                time.sleep(5)
    finally:
        write_state(state)
        log.info("Loop finished: %d alerts, %d users", len(state["alerts"]), len(state["users"]))


if __name__ == "__main__":
    run_once() if RUN_MODE == "once" else run_loop()
