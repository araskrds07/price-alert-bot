"""
Price Alert Bot for Telegram  (v3 — Turkish / English, region aware)
===================================================================

Users set price alerts with buttons or plain text; the bot watches prices and
messages them when a level is crossed. Crypto (Coinbase), stocks, indices,
gold and FX (Yahoo Finance). It only notifies — it gives no advice.

First contact: the user picks a language (Türkçe / English) and a region
(Türkiye / USA / Europe / Other). The region sets the quick-pick buttons, the
local-currency equivalent (₺ / €), the time zone, the daily summary and what
"gold" means (gram in ₺ for Türkiye, troy ounce in $ elsewhere).
Both can be changed any time with ⚙️ Settings (/ayarlar, /settings).

For users
  type  BTC · BTC 90000 · ETH 5% · gold 4500 · SP500 7000 · THYAO 300
  buttons: 🔔 Alert · 💱 Price · 📋 My alerts · 📊 Summary · ⚙️ Settings
  commands (tr / en): /alarm /alert · /fiyat /price · /liste /list · /ozet /summary
                      /ayarlar /settings · /yardim /help

For the owner (OWNER_CHAT_ID)
  /admin · /duyuru /broadcast · /izinver /allow · /izinkaldir /disallow
  /ozelmod /private · /uzat /extend · /bitir /end · /kullanicilar /users

Environment
  TELEGRAM_TOKEN   (required)
  OWNER_CHAT_ID    your chat id (admin panel + notifications)
  DEFAULT_LANG     tr | en              (default tr)   used for groups and before onboarding
  DEFAULT_REGION   tr | us | eu | global (default tr)
  ONBOARDING       1 = ask language + region on first contact (default), 0 = use the defaults
  ALLOWED_CHAT_IDS comma list; if set, private mode starts ON
  TRIAL_DAYS       free days per user from their first message (0 = off)
  TRIAL_UNTIL      YYYY-MM-DD: the whole bot stops after this date
  TRIAL_CONTACT    shown when a trial ends (e.g. a Fiverr link or @name)
  RUN_MODE         once | loop (default loop) · MAX_RUNTIME seconds (0 = forever)
  BOT_TITLE        name in the help text (white label)
  POPULAR          quick-pick override for every region, e.g. BTC,ETH,AAPL
  SUMMARY_ASSETS   summary override for every region
  SUMMARY_TIME     default daily summary time (18:15), in each chat's own time zone
  LOCAL_TZ         time zone override for DEFAULT_REGION
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

VERSION = "4.0"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()
ENV_ALLOWED = {s.strip() for s in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if s.strip()}
RUN_MODE = os.environ.get("RUN_MODE", "loop")
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME") or 0)
STATE_FILE = os.environ.get("STATE_FILE", "alerts.json")
BOT_TITLE = os.environ.get("BOT_TITLE") or ""
DEFAULT_LANG = (os.environ.get("DEFAULT_LANG") or "tr").strip().lower()
DEFAULT_REGION = (os.environ.get("DEFAULT_REGION") or "tr").strip().lower()
ONBOARDING = os.environ.get("ONBOARDING", "1") != "0"
ENV_POPULAR = os.environ.get("POPULAR") or ""
ENV_SUMMARY = os.environ.get("SUMMARY_ASSETS") or ""
SUMMARY_TIME = os.environ.get("SUMMARY_TIME") or "18:15"
NOTIFY_NEW_USERS = os.environ.get("NOTIFY_NEW_USERS", "1") != "0"
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS") or 0)
TRIAL_UNTIL = (os.environ.get("TRIAL_UNTIL") or "").strip()
TRIAL_CONTACT = os.environ.get("TRIAL_CONTACT") or ""
WARN_BEFORE_DAYS = 2

MAX_ALERTS_PER_CHAT = 20
CHECK_SECONDS = 30
REARM_PCT = 0.5
PENDING_TTL = 600
RATE_LIMIT = int(os.environ.get("RATE_LIMIT") or 40)
PREMIUM_STARS = int(os.environ.get("PREMIUM_STARS") or 0)       # >0 turns on the free plan + paid Premium
PREMIUM_DAYS = int(os.environ.get("PREMIUM_DAYS") or 30)
FREE_ALERTS = int(os.environ.get("FREE_ALERTS") or 3)
MAX_POSITIONS = 30
TECH_CHECK_SECONDS = 600
GRAMS_PER_OZ = 31.1035
CB_API = "https://api.exchange.coinbase.com"
HTTP_HEADERS = {"User-Agent": "price-alert-bot/3.0"}

LANGS = ("tr", "en")
REGIONS = ("tr", "us", "eu", "global")
if DEFAULT_LANG not in LANGS:
    DEFAULT_LANG = "tr"
if DEFAULT_REGION not in REGIONS:
    DEFAULT_REGION = "tr"

# ---------------------------------------------------------------- regions
REGION_TZ = {"tr": "Europe/Istanbul", "us": "America/New_York", "eu": "Europe/Berlin", "global": "UTC"}
if os.environ.get("LOCAL_TZ"):
    REGION_TZ[DEFAULT_REGION] = os.environ["LOCAL_TZ"]

REGION_POPULAR = {
    "tr": "BTC,ETH,SOL,GRAMALTIN,USDTRY,EURTRY,BIST100,THYAO.IS,ASELS.IS",
    "us": "BTC,ETH,SOL,SP500,NASDAQ,ONS,AAPL,NVDA,TSLA",
    "eu": "BTC,ETH,SOL,EURUSD,ONS,DAX,EUROSTOXX,ASML,SAP",
    "global": "BTC,ETH,SOL,XRP,ONS,SP500,EURUSD,AAPL,NVDA",
}
REGION_SUMMARY = {
    "tr": "BIST100,USDTRY,EURTRY,GRAMALTIN,BTC,ETH",
    "us": "SP500,NASDAQ,DOW,ONS,BTC,ETH",
    "eu": "EUROSTOXX,DAX,EURUSD,ONS,BTC,ETH",
    "global": "SP500,EURUSD,ONS,BTC,ETH",
}
REGION_MOVERS = {
    "tr": [t + ".IS" for t in ("AKBNK ASELS ASTOR BIMAS EKGYO ENKAI EREGL FROTO GARAN ISCTR KCHOL KONTR "
                               "KRDMD MGROS OYAKC PETKM PGSUS SAHOL SASA SISE TAVHL TCELL THYAO TOASO "
                               "TTKOM TUPRS ULKER YKBNK").split()],
    "us": "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA NFLX AMD COST WMT LLY XOM".split(),
}
BIST_MOVERS = [t[:-3] for t in REGION_MOVERS["tr"]]          # kept for backwards compatibility

SPECIAL = {
    "GRAMALTIN": {"name": {"tr": "Gram altın", "en": "Gold (gram, TRY)"}, "yahoo": "GC=F", "cur": "₺", "gram": True},
    "GRAMGUMUS": {"name": {"tr": "Gram gümüş", "en": "Silver (gram, TRY)"}, "yahoo": "SI=F", "cur": "₺", "gram": True},
    "ONS":       {"name": {"tr": "Ons altın", "en": "Gold (oz)"}, "yahoo": "GC=F", "cur": "$"},
    "ONSGUMUS":  {"name": {"tr": "Ons gümüş", "en": "Silver (oz)"}, "yahoo": "SI=F", "cur": "$"},
    "USDTRY":    {"name": {"tr": "Dolar/TL", "en": "USD/TRY"}, "yahoo": "USDTRY=X", "cur": "₺"},
    "EURTRY":    {"name": {"tr": "Euro/TL", "en": "EUR/TRY"}, "yahoo": "EURTRY=X", "cur": "₺"},
    "GBPTRY":    {"name": {"tr": "Sterlin/TL", "en": "GBP/TRY"}, "yahoo": "GBPTRY=X", "cur": "₺"},
    "EURUSD":    {"name": {"tr": "Euro/Dolar", "en": "EUR/USD"}, "yahoo": "EURUSD=X", "cur": ""},
    "BIST100":   {"name": {"tr": "BIST 100", "en": "BIST 100"}, "yahoo": "XU100.IS", "cur": ""},
    "BIST30":    {"name": {"tr": "BIST 30", "en": "BIST 30"}, "yahoo": "XU030.IS", "cur": ""},
    "SP500":     {"name": {"tr": "S&P 500", "en": "S&P 500"}, "yahoo": "^GSPC", "cur": ""},
    "NASDAQ":    {"name": {"tr": "Nasdaq", "en": "Nasdaq"}, "yahoo": "^IXIC", "cur": ""},
    "DOW":       {"name": {"tr": "Dow Jones", "en": "Dow Jones"}, "yahoo": "^DJI", "cur": ""},
    "DAX":       {"name": {"tr": "DAX", "en": "DAX"}, "yahoo": "^GDAXI", "cur": ""},
    "EUROSTOXX": {"name": {"tr": "Euro Stoxx 50", "en": "Euro Stoxx 50"}, "yahoo": "^STOXX50E", "cur": ""},
}
ALIASES = {
    "GRAM": "GRAMALTIN", "GAU": "GRAMALTIN", "ONSALTIN": "ONS", "XAU": "ONS", "XAUUSD": "ONS",
    "XAG": "ONSGUMUS", "XAGUSD": "ONSGUMUS", "USDTL": "USDTRY", "EURTL": "EURTRY", "STERLIN": "GBPTRY",
    "PARITE": "EURUSD", "BIST": "BIST100", "XU100": "BIST100", "XU030": "BIST30",
    "SPX": "SP500", "S&P500": "SP500", "S&P": "SP500", "GSPC": "SP500", "IXIC": "NASDAQ",
    "DJI": "DOW", "DOWJONES": "DOW", "GDAXI": "DAX", "STOXX50": "EUROSTOXX", "SX5E": "EUROSTOXX",
    "EUROSTOXX50": "EUROSTOXX",
}
# words whose meaning depends on the user's region
REGION_ALIASES = {
    "tr": {"ALTIN": "GRAMALTIN", "GOLD": "GRAMALTIN", "GUMUS": "GRAMGUMUS", "SILVER": "GRAMGUMUS",
           "DOLAR": "USDTRY", "USD": "USDTRY", "EURO": "EURTRY", "AVRO": "EURTRY", "EUR": "EURTRY"},
    "*":  {"ALTIN": "ONS", "GOLD": "ONS", "GUMUS": "ONSGUMUS", "SILVER": "ONSGUMUS",
           "DOLAR": "USDTRY", "EURO": "EURUSD", "AVRO": "EURUSD", "EUR": "EURUSD"},
}
TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

# ---------------------------------------------------------------- text
LANG_NAME = {"tr": "Türkçe", "en": "English"}
REGION_NAME = {
    "tr": {"tr": "🇹🇷 Türkiye", "us": "🇺🇸 ABD", "eu": "🇪🇺 Avrupa", "global": "🌍 Diğer"},
    "en": {"tr": "🇹🇷 Turkey", "us": "🇺🇸 USA", "eu": "🇪🇺 Europe", "global": "🌍 Other"},
}
EX_HELP = {
    ("tr", "tr"): "altın 7000 · dolar 50 · THYAO 300", ("tr", "us"): "altın 4500 · AAPL 350 · SP500 7000",
    ("tr", "eu"): "altın 4500 · EURUSD 1,2 · DAX 25000", ("tr", "global"): "altın 4500 · AAPL 350 · EURUSD 1,2",
    ("en", "tr"): "gold 7000 · USDTRY 50 · THYAO 300", ("en", "us"): "gold 4500 · AAPL 350 · SP500 7000",
    ("en", "eu"): "gold 4500 · EURUSD 1.2 · DAX 25000", ("en", "global"): "gold 4500 · AAPL 350 · EURUSD 1.2",
}
EX_SHORT = {
    ("tr", "tr"): "BTC, ETH, AAPL, THYAO, altın, dolar", ("tr", "us"): "BTC, ETH, AAPL, NVDA, SP500, altın",
    ("tr", "eu"): "BTC, ETH, EURUSD, DAX, altın", ("tr", "global"): "BTC, ETH, AAPL, EURUSD, altın",
    ("en", "tr"): "BTC, ETH, THYAO, gold, USDTRY", ("en", "us"): "BTC, ETH, AAPL, NVDA, SP500, gold",
    ("en", "eu"): "BTC, ETH, EURUSD, DAX, gold", ("en", "global"): "BTC, ETH, AAPL, EURUSD, gold",
}
EX_TYPE = {
    ("tr", "tr"): "<code>SOL</code>, <code>TSLA</code>, <code>ASELS</code>, <code>gümüş</code>, <code>BTCTRY</code>",
    ("tr", "*"): "<code>SOL</code>, <code>TSLA</code>, <code>NVDA</code>, <code>gümüş</code>, <code>EURUSD</code>",
    ("en", "tr"): "<code>SOL</code>, <code>TSLA</code>, <code>ASELS</code>, <code>silver</code>, <code>BTCTRY</code>",
    ("en", "*"): "<code>SOL</code>, <code>TSLA</code>, <code>NVDA</code>, <code>silver</code>, <code>EURUSD</code>",
}

S = {
    "title": {"tr": "Fiyat Alarm Botu", "en": "Price Alert Bot"},
    "intro": {"tr": "Belirlediğin fiyata gelince haber veririm: kripto, hisseler, altın ve döviz.",
              "en": "I'll ping you when a price hits your level: crypto, stocks, gold and currencies."},
    "howto": {"tr": "<b>En kolayı:</b> alttaki butonları kullan ya da direkt yaz:\n"
                    "• <code>BTC</code> → anlık fiyat\n"
                    "• <code>BTC 90000</code> → 90.000$'a gelince haber ver\n"
                    "• <code>{ex}</code>\n"
                    "• <code>ETH %5</code> → %5 oynarsa haber ver\n"
                    "• sonuna <code>tekrar</code> yazarsan alarm her geçişte çalışır\n"
                    "• <code>BTC grafik</code> → grafik · <code>BTC teknik</code> → RSI, ortalama, 52 hafta alarmları\n"
                    "• <code>/ekle BTC 0.5 60000</code> → portföyüne ekle, kâr/zararını takip et",
              "en": "<b>Easiest:</b> use the buttons below or just type:\n"
                    "• <code>BTC</code> → live price\n"
                    "• <code>BTC 90000</code> → ping me at $90,000\n"
                    "• <code>{ex}</code>\n"
                    "• <code>ETH 5%</code> → ping me on a ±5% move\n"
                    "• add <code>repeat</code> to get pinged on every cross\n"
                    "• <code>BTC chart</code> → chart · <code>BTC tech</code> → RSI, moving average, 52-week alerts\n"
                    "• <code>/add BTC 0.5 60000</code> → track it in your portfolio with profit/loss"},
    "howto_group": {"tr": "<b>Grupta:</b> aşağıdaki butonlar ya da komutlar\n"
                          "• <code>/fiyat BTC</code> · <code>/alarm BTC 90000</code>",
                    "en": "<b>In groups:</b> use the buttons below or commands\n"
                          "• <code>/price BTC</code> · <code>/alert BTC 90000</code>"},
    "cmds": {"tr": "<b>Komutlar:</b> /alarm · /fiyat · /liste · /portfoy · /ozet · /ayarlar · /yardim",
             "en": "<b>Commands:</b> /alert · /price · /list · /portfolio · /summary · /settings · /help"},
    "disclaimer": {"tr": "<i>Bu bot sadece haber verir, yatırım tavsiyesi vermez.</i>",
                   "en": "<i>This bot only sends notifications. It is not investment advice.</i>"},
    # reply keyboard
    "b_alarm": {"tr": "🔔 Alarm kur", "en": "🔔 Set alert"},
    "b_price": {"tr": "💱 Fiyat", "en": "💱 Price"},
    "b_list": {"tr": "📋 Alarmlarım", "en": "📋 My alerts"},
    "b_sum": {"tr": "📊 Özet", "en": "📊 Summary"},
    "b_settings": {"tr": "⚙️ Ayarlar", "en": "⚙️ Settings"},
    "b_help": {"tr": "❓ Yardım", "en": "❓ Help"},
    # onboarding / settings
    "choose_lang": {"tr": "🌐 Dil seç · Choose your language", "en": "🌐 Choose your language · Dil seç"},
    "choose_region": {"tr": "📍 Hangi piyasaları takip ediyorsun?\nHızlı butonları, para birimini ve saati buna "
                            "göre ayarlayacağım.",
                      "en": "📍 Which markets do you follow?\nI'll set the quick buttons, currency and time "
                            "zone to match."},
    "saved": {"tr": "✅ Hazır! Dil: <b>{lang}</b> · Bölge: <b>{region}</b>\nİstediğin zaman ⚙️ Ayarlar'dan "
                    "değiştirebilirsin.",
              "en": "✅ All set! Language: <b>{lang}</b> · Region: <b>{region}</b>\nYou can change this any "
                    "time in ⚙️ Settings."},
    "settings": {"tr": "⚙️ <b>Ayarlar</b>\nDil: <b>{lang}</b>\nBölge: <b>{region}</b>\nSaat dilimi: {tz}",
                 "en": "⚙️ <b>Settings</b>\nLanguage: <b>{lang}</b>\nRegion: <b>{region}</b>\nTime zone: {tz}"},
    "btn_lang": {"tr": "🌐 Dili değiştir", "en": "🌐 Change language"},
    "btn_region": {"tr": "📍 Bölgeyi değiştir", "en": "📍 Change region"},
    "group_admin_only": {"tr": "Bu grubun ayarlarını sadece yöneticiler değiştirebilir.",
                         "en": "Only group admins can change this group's settings."},
    # pickers
    "pick_alarm": {"tr": "🔔 Hangisi için alarm kuralım?", "en": "🔔 Which one should I watch?"},
    "pick_price": {"tr": "💱 Hangisinin fiyatına bakalım?", "en": "💱 Which price do you want?"},
    "btn_other": {"tr": "✏️ Başka bir şey yazacağım", "en": "✏️ I'll type another one"},
    "type_symbol": {"tr": "✏️ Yaz bakalım: örneğin {ex}", "en": "✏️ Type it, for example {ex}"},
    "group_type_hint": {"tr": "Grupta yazarak kullan: <code>/fiyat SOL</code> · <code>/alarm SOL 150</code>",
                        "en": "In groups, type it: <code>/price SOL</code> · <code>/alert SOL 150</code>"},
    "group_level_hint": {"tr": "Grupta yazarak kur: <code>/alarm {sym} 12345</code>",
                         "en": "In groups, type it: <code>/alert {sym} 12345</code>"},
    # prices
    "today_tag": {"tr": "(günlük)", "en": "(today)"},
    "delayed": {"tr": "<i>Borsa, altın ve döviz fiyatları ~15 dk gecikmeli.</i>",
                "en": "<i>Stock, gold and FX prices are ~15 min delayed.</i>"},
    "btn_set_alert": {"tr": "🔔 Alarm kur", "en": "🔔 Set alert"},
    "btn_refresh": {"tr": "🔄 Yenile", "en": "🔄 Refresh"},
    "not_found": {"tr": "<b>{sym}</b> için fiyat bulamadım.\nÖrnekler: {ex}",
                  "en": "I couldn't find a price for <b>{sym}</b>.\nExamples: {ex}"},
    "lp_now": {"tr": "<b>{name}</b> şu an {price}", "en": "<b>{name}</b> is at {price}"},
    "lp_today": {"tr": " ({chg} bugün)", "en": " ({chg} today)"},
    "lp_ask": {"tr": "Ne zaman haber vereyim?", "en": "When should I ping you?"},
    "btn_move": {"tr": "↕️ %{n} oynarsa", "en": "↕️ ±{n}% move"},
    "btn_write": {"tr": "✏️ Fiyatı ben yazacağım", "en": "✏️ I'll type the price"},
    "write_level": {"tr": "✏️ <b>{name}</b> için fiyatı yaz{now}.\nÖrnek: <code>70000</code> ya da <code>%5</code>",
                    "en": "✏️ Type the price for <b>{name}</b>{now}.\nExample: <code>70000</code> or <code>5%</code>"},
    "now_paren": {"tr": " (şu an {p})", "en": " (now {p})"},
    "only_price": {"tr": "Sadece fiyatı yaz, örneğin <code>70000</code> ya da <code>%5</code>",
                   "en": "Just type the price, e.g. <code>70000</code> or <code>5%</code>"},
    # alerts
    "move_desc": {"tr": "{rep}{name} ±%{pct} ({ref} fiyatından)", "en": "{rep}{name} ±{pct}% (from {ref})"},
    "btn_once": {"tr": "1️⃣ Tek seferlik yap", "en": "1️⃣ Make it one-time"},
    "btn_repeat": {"tr": "🔁 Her geçişte haber ver", "en": "🔁 Ping me every time"},
    "btn_cancel": {"tr": "🗑 İptal", "en": "🗑 Cancel"},
    "max_alerts": {"tr": "En fazla {n} alarm kurabilirsin. Yer açmak için 📋 Alarmlarım.",
                   "en": "You can have up to {n} alerts. Free up space in 📋 My alerts."},
    "btn_my_alerts": {"tr": "📋 Alarmlarım", "en": "📋 My alerts"},
    "pct_range": {"tr": "Yüzde 0,1 ile 100 arasında olmalı. Örnek: <code>ETH %5</code>",
                  "en": "The percentage must be between 0.1 and 100. Example: <code>ETH 5%</code>"},
    "already_at": {"tr": "{name} zaten {price} civarında. Biraz daha yukarı ya da aşağı bir seviye yazar mısın?",
                   "en": "{name} is already around {price}. Try a level a bit higher or lower."},
    "would_fire": {"tr": "{name} zaten {price}; bu alarm hemen çalışırdı. Seviyeyi kontrol eder misin?",
                   "en": "{name} is already at {price}, so this alert would fire right away. "
                         "Double-check the level?"},
    "far_warn": {"tr": "\n⚠️ Seviye şu anki fiyattan çok uzak; doğru yazdığından emin ol.",
                 "en": "\n⚠️ That level is far from the current price — make sure it's right."},
    "alert_set": {"tr": "✅ <b>Alarm kuruldu:</b> {desc}\nŞu an: {price}{note}",
                  "en": "✅ <b>Alert set:</b> {desc}\nNow: {price}{note}"},
    "alert_label": {"tr": "✅ <b>Alarm:</b> {desc}", "en": "✅ <b>Alert:</b> {desc}"},
    "repeat_on": {"tr": "🔁 Fiyat her seviyeyi geçtiğinde haber vereceğim.",
                  "en": "🔁 I'll ping you every time the price crosses the level."},
    "repeat_off": {"tr": "1️⃣ Bir kez haber verip silinecek.", "en": "1️⃣ I'll ping you once, then remove it."},
    "alert_gone": {"tr": "Bu alarm artık yok", "en": "This alert no longer exists"},
    "deleted": {"tr": "🗑 Silindi", "en": "🗑 Deleted"},
    "cancelled": {"tr": "🗑 Alarm iptal edildi.", "en": "🗑 Alert cancelled."},
    "n_deleted": {"tr": "🗑 {n} alarm silindi.", "en": "🗑 {n} alerts deleted."},
    "deleted_desc": {"tr": "🗑 Silindi: {desc}", "en": "🗑 Deleted: {desc}"},
    "btn_new": {"tr": "➕ Yeni alarm", "en": "➕ New alert"},
    "no_alerts": {"tr": "Kurulu alarmın yok.\nKurmak için <b>🔔 Alarm kur</b> butonuna bas ya da "
                        "<code>BTC 90000</code> gibi yaz.",
                  "en": "You have no alerts yet.\nTap <b>🔔 Set alert</b> or type something like "
                        "<code>BTC 90000</code>."},
    "btn_add": {"tr": "➕ Alarm kur", "en": "➕ Set alert"},
    "list_title": {"tr": "📋 <b>Alarmların</b> ({n})", "en": "📋 <b>Your alerts</b> ({n})"},
    "list_hint": {"tr": "\n<i>Silmek için numarasına bas.</i>", "en": "\n<i>Tap a number to delete it.</i>"},
    "btn_del_all": {"tr": "🗑 Hepsini sil", "en": "🗑 Delete all"},
    # fired
    "fired_above": {"tr": "🔔 <b>{name}</b> {level} seviyesine ulaştı! 📈", "en": "🔔 <b>{name}</b> reached {level}! 📈"},
    "fired_below": {"tr": "🔔 <b>{name}</b> {level} seviyesine indi! 📉", "en": "🔔 <b>{name}</b> dropped to {level}! 📉"},
    "fired_up": {"tr": "🔔 <b>{name}</b> {chg} yükseldi 📈\n{ref} → {price}", "en": "🔔 <b>{name}</b> is up {chg} 📈\n{ref} → {price}"},
    "fired_down": {"tr": "🔔 <b>{name}</b> {chg} düştü 📉\n{ref} → {price}", "en": "🔔 <b>{name}</b> is down {chg} 📉\n{ref} → {price}"},
    "fired_now": {"tr": "Şu an: <b>{price}</b> ({time})", "en": "Now: <b>{price}</b> ({time})"},
    "fired_repeat": {"tr": "<i>🔁 Tekrarlı alarm: yine geçerse yine haber vereceğim.</i>",
                     "en": "<i>🔁 Repeating alert: I'll ping you again on the next cross.</i>"},
    "fired_once": {"tr": "<i>Alarm tamamlandı ve silindi.</i>", "en": "<i>Alert done and removed.</i>"},
    "btn_del_alert": {"tr": "🗑 Alarmı sil", "en": "🗑 Delete alert"},
    "btn_price": {"tr": "💱 Fiyat", "en": "💱 Price"},
    "btn_again": {"tr": "🔁 Aynısını tekrar kur", "en": "🔁 Set it again"},
    # summary
    "sum_title": {"tr": "📊 <b>Piyasa özeti</b> · {dt}", "en": "📊 <b>Market summary</b> · {dt}"},
    "movers_up": {"tr": "🚀 <b>Büyük hisselerde yükselenler:</b> {x}", "en": "🚀 <b>Top gainers:</b> {x}"},
    "movers_dn": {"tr": "🔻 <b>Düşenler:</b> {x}", "en": "🔻 <b>Top losers:</b> {x}"},
    "sum_footer": {"tr": "\n<i>Borsa, altın ve döviz ~15 dk gecikmeli. Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>",
                   "en": "\n<i>Stock, gold and FX data is ~15 min delayed. For information only, not investment advice.</i>"},
    "btn_sum_on": {"tr": "🔔 Günlük özeti aç · her gün {t}", "en": "🔔 Daily summary · every day at {t}"},
    "btn_sum_off": {"tr": "🔕 Günlük özeti durdur · {t}", "en": "🔕 Stop daily summary · {t}"},
    "sum_on": {"tr": "🔔 Günlük özet açık.\nGönderim saati: <b>{t}</b> (her gün)\nKapatmak için: /ozet kapat",
               "en": "🔔 Daily summary is on.\nSent every day at <b>{t}</b>\nTo stop it: /summary off"},
    "sum_off": {"tr": "🔕 Günlük özet kapatıldı.", "en": "🔕 Daily summary stopped."},
    "sum_admin": {"tr": "Günlük özeti sadece grup yöneticileri açıp kapatabilir.",
                  "en": "Only group admins can turn the daily summary on or off."},
    "toast_admin": {"tr": "Bunu sadece grup yöneticileri değiştirebilir", "en": "Only group admins can change this"},
    # misc
    "bad_alarm": {"tr": "Anlayamadım. Örnekler:\n<code>/alarm BTC 90000</code>\n<code>/alarm {gold} 4500</code>\n"
                        "<code>/alarm ETH %5</code>",
                  "en": "I didn't get that. Examples:\n<code>/alert BTC 90000</code>\n<code>/alert gold 4500</code>\n"
                        "<code>/alert ETH 5%</code>"},
    "what": {"tr": "Ne yapmamı istersin? 🙂\n• <code>BTC</code> → fiyat\n• <code>BTC 90000</code> → alarm\n"
                   "• <code>{ex}</code>\nYa da aşağıdaki butonları kullan.",
             "en": "What would you like to do? 🙂\n• <code>BTC</code> → price\n• <code>BTC 90000</code> → alert\n"
                   "• <code>{ex}</code>\nOr use the buttons below."},
    "error": {"tr": "Bir hata oldu, biraz sonra tekrar dener misin?", "en": "Something went wrong. Please try again in a moment."},
    "no_price": {"tr": "Fiyat şu an alınamadı, biraz sonra dene", "en": "Couldn't get the price right now, try again soon"},
    "updated": {"tr": "Güncellendi", "en": "Updated"},
    "slow": {"tr": "Biraz yavaş 🙂", "en": "Slow down a bit 🙂"},
    "id": {"tr": "🆔 Bu sohbetin id'si: <code>{cid}</code>", "en": "🆔 This chat's id: <code>{cid}</code>"},
    "id_user": {"tr": "\nSenin kullanıcı id'n: <code>{uid}</code>", "en": "\nYour user id: <code>{uid}</code>"},
    # access / trial
    "private_bot": {"tr": "🔒 Bu bot şu an özel kullanımda. Erişim isteğin bot sahibine iletildi.",
                    "en": "🔒 This bot is private right now. Your access request has been sent to the owner."},
    "granted": {"tr": "✅ Erişimin açıldı! Başlamak için /start", "en": "✅ You now have access! Send /start to begin."},
    "refused": {"tr": "Erişim isteğin şu an kabul edilmedi.", "en": "Your access request wasn't approved."},
    "no_access": {"tr": "Erişim yok", "en": "No access"},
    "contact": {"tr": "\nDevam etmek için: {c}", "en": "\nTo continue: {c}"},
    "trial_over": {"tr": "⏳ <b>Deneme süresi doldu.</b>{contact}", "en": "⏳ <b>Your trial has ended.</b>{contact}"},
    "trial_end": {"tr": "⏳ <b>Deneme süren doldu.</b>\nAlarmların artık çalışmıyor.{contact}",
                  "en": "⏳ <b>Your free trial has ended.</b>\nYour alerts are paused.{contact}"},
    "trial_warn": {"tr": "⏳ Ücretsiz denemenin bitmesine <b>{d} gün</b> kaldı. Alarmların o zamana kadar çalışmaya "
                         "devam eder.{contact}",
                   "en": "⏳ Your free trial ends in <b>{d} day(s)</b>. Your alerts keep working until then.{contact}"},
    "trial_toast": {"tr": "Deneme süresi doldu", "en": "Trial ended"},
    "closed": {"tr": "⏳ <b>Erişimin kapandı.</b>{contact}", "en": "⏳ <b>Your access has been closed.</b>{contact}"},
    "extended": {"tr": "✅ Süren uzatıldı: {d} gün daha. Alarmların yine çalışıyor.",
                 "en": "✅ Your trial was extended by {d} days. Your alerts are active again."},
    "unlimited": {"tr": "✅ Erişimin açıldı, süre sınırı yok. Alarmların yine çalışıyor.",
                  "en": "✅ Your access is now unlimited. Your alerts are active again."},
    # owner
    "new_user": {"tr": "👤 Yeni kullanıcı: {name}\nid: <code>{cid}</code>", "en": "👤 New user: {name}\nid: <code>{cid}</code>"},
    "access_req": {"tr": "🔑 Erişim isteği: {name}\nid: <code>{cid}</code>", "en": "🔑 Access request: {name}\nid: <code>{cid}</code>"},
    "btn_approve": {"tr": "✅ İzin ver", "en": "✅ Approve"},
    "btn_deny": {"tr": "❌ Reddet", "en": "❌ Deny"},
    "approved": {"tr": "✅ İzin verildi: {cid}", "en": "✅ Approved: {cid}"},
    "denied": {"tr": "❌ Reddedildi: {cid}", "en": "❌ Denied: {cid}"},
    "removed": {"tr": "🚫 İzin kaldırıldı: {cid}", "en": "🚫 Access removed: {cid}"},
    "admin": {"tr": "🛠 <b>Yönetim paneli</b> · v{v}\n\n"
                    "👥 Kullanıcı: <b>{p}</b> kişi, <b>{g}</b> grup\n"
                    "🌐 Dil: {langs}\n"
                    "🔔 Aktif alarm: <b>{n}</b> ({r} tekrarlı)\n"
                    "📊 Günlük özet abonesi: <b>{subs}</b>\n"
                    "✅ Tetiklenen alarm: bugün <b>{fd}</b>, toplam <b>{ft}</b>\n"
                    "{trial}"
                    "🔒 Özel mod: <b>{pm}</b> (izinli: {al})\n\n"
                    "<b>Komutlar</b>\n"
                    "/duyuru metin — herkese mesaj\n"
                    "/izinver 12345 · /izinkaldir 12345\n"
                    "/uzat 12345 · /uzat 12345 sinirsiz · /bitir 12345\n"
                    "/kullanicilar — kim, ne zaman başladı, kaç gün kaldı\n"
                    "/ozelmod ac · /ozelmod kapat",
              "en": "🛠 <b>Admin panel</b> · v{v}\n\n"
                    "👥 Users: <b>{p}</b> people, <b>{g}</b> groups\n"
                    "🌐 Languages: {langs}\n"
                    "🔔 Active alerts: <b>{n}</b> ({r} repeating)\n"
                    "📊 Daily summary subscribers: <b>{subs}</b>\n"
                    "✅ Alerts fired: today <b>{fd}</b>, total <b>{ft}</b>\n"
                    "{trial}"
                    "🔒 Private mode: <b>{pm}</b> (allowed: {al})\n\n"
                    "<b>Commands</b>\n"
                    "/broadcast text — message everyone\n"
                    "/allow 12345 · /disallow 12345\n"
                    "/extend 12345 · /extend 12345 unlimited · /end 12345\n"
                    "/users — who started when, days left\n"
                    "/private on · /private off"},
    "adm_trial": {"tr": "⏳ Deneme: <b>{d} gün</b> (kişi başı) · ♾ süresiz: <b>{u}</b>\n",
                  "en": "⏳ Trial: <b>{d} days</b> per user · ♾ unlimited: <b>{u}</b>\n"},
    "adm_until": {"tr": "⏳ Bot son kullanma: <b>{d}</b>\n", "en": "⏳ Bot expires: <b>{d}</b>\n"},
    "on": {"tr": "AÇIK", "en": "ON"},
    "off": {"tr": "kapalı", "en": "off"},
    "btn_pm_on": {"tr": "🔒 Özel modu aç", "en": "🔒 Turn private mode on"},
    "btn_pm_off": {"tr": "🔒 Özel modu kapat", "en": "🔒 Turn private mode off"},
    "bc_usage": {"tr": "Kullanım: /duyuru Yeni özellik geldi! ...", "en": "Usage: /broadcast New feature is live! ..."},
    "bc_done": {"tr": "📢 Duyuru {ok}/{n} sohbete gönderildi.", "en": "📢 Broadcast sent to {ok}/{n} chats."},
    "allow_usage": {"tr": "Kullanım: /izinver 123456789", "en": "Usage: /allow 123456789"},
    "ext_usage": {"tr": "Kullanım:\n<code>/uzat 12345678</code> — süreyi baştan başlatır\n"
                        "<code>/uzat 12345678 sinirsiz</code> — süresiz yapar",
                  "en": "Usage:\n<code>/extend 12345678</code> — restarts the trial\n"
                        "<code>/extend 12345678 unlimited</code> — removes the time limit"},
    "ext_unlimited": {"tr": "♾ {cid} artık süresiz.", "en": "♾ {cid} is now unlimited."},
    "ext_done": {"tr": "⏳ {cid} için süre baştan başladı ({d} gün).", "en": "⏳ Trial restarted for {cid} ({d} days)."},
    "end_usage": {"tr": "Kullanım: <code>/bitir 12345678</code> — o kişiye botu kapatır",
                  "en": "Usage: <code>/end 12345678</code> — closes the bot for that person"},
    "end_done": {"tr": "🚫 {cid} kapatıldı. Geri açmak için: <code>/uzat {cid}</code>",
                 "en": "🚫 {cid} closed. To reopen: <code>/extend {cid}</code>"},
    "no_users": {"tr": "Henüz kullanıcı yok.", "en": "No users yet."},
    "users_title": {"tr": "👥 <b>Kullanıcılar</b> (en yeniden eskiye)", "en": "👥 <b>Users</b> (newest first)"},
    "users_row": {"tr": "• <b>{name}</b>\n  <code>{cid}</code> · başlangıç {start} · {status} · {n} alarm · {lr}",
                  "en": "• <b>{name}</b>\n  <code>{cid}</code> · started {start} · {status} · {n} alerts · {lr}"},
    "users_foot": {"tr": "\n\n<code>/uzat id</code> · <code>/uzat id sinirsiz</code> · <code>/bitir id</code>",
                   "en": "\n\n<code>/extend id</code> · <code>/extend id unlimited</code> · <code>/end id</code>"},
    "st_closed": {"tr": "🚫 kapalı", "en": "🚫 closed"},
    "st_unlimited": {"tr": "♾ süresiz", "en": "♾ unlimited"},
    "st_expired": {"tr": "⏳ doldu", "en": "⏳ expired"},
    "st_left": {"tr": "⏳ {d:.1f} gün", "en": "⏳ {d:.1f} days"},
    # ---- v4: charts
    "b_port": {"tr": "💼 Portföy", "en": "💼 Portfolio"},
    "b_prem": {"tr": "⭐ Premium", "en": "⭐ Premium"},
    "btn_chart": {"tr": "📈 Grafik", "en": "📈 Chart"},
    "btn_tech": {"tr": "📐 Teknik alarm", "en": "📐 Technical alert"},
    "btn_pf_add": {"tr": "➕ Ekle", "en": "➕ Add"},
    "btn_to_pf": {"tr": "💼 Portföye ekle", "en": "💼 Add to portfolio"},
    "chart_cap": {"tr": "📈 <b>{name}</b> · {span} · {price}  {chg}", "en": "📈 <b>{name}</b> · {span} · {price}  {chg}"},
    "chart_fail": {"tr": "Bu varlık için şu an grafik verisi alınamadı.", "en": "Couldn't get chart data for this asset right now."},
    "chart_wait": {"tr": "Grafik hazırlanıyor…", "en": "Drawing the chart…"},
    # ---- v4: technical alerts
    "tech_pick": {"tr": "📐 <b>{name}</b> için hangi durumda haber vereyim?\n"
                        "<i>Günlük grafikten hesaplanır, 10 dakikada bir kontrol edilir. Silene kadar çalışır.</i>",
                  "en": "📐 Which signal should I watch on <b>{name}</b>?\n"
                        "<i>Calculated from the daily chart and checked every 10 minutes. Stays on until you delete it.</i>"},
    "sig_rsi_lo": {"tr": "RSI 30'un altına inerse (aşırı satım)", "en": "RSI drops below 30 (oversold)"},
    "sig_rsi_hi": {"tr": "RSI 70'in üstüne çıkarsa (aşırı alım)", "en": "RSI rises above 70 (overbought)"},
    "sig_ma": {"tr": "50/200 günlük ortalama kesişimi", "en": "50/200-day moving average cross"},
    "sig_hi52": {"tr": "52 haftanın zirvesi kırılırsa", "en": "New 52-week high"},
    "sig_lo52": {"tr": "52 haftanın dibi kırılırsa", "en": "New 52-week low"},
    "sig_vol": {"tr": "Hacim patlaması (ortalamanın 2 katı)", "en": "Volume spike (2× average)"},
    "short_rsi_lo": {"tr": "RSI < 30", "en": "RSI < 30"},
    "short_rsi_hi": {"tr": "RSI > 70", "en": "RSI > 70"},
    "short_ma": {"tr": "50/200 ort. kesişimi", "en": "50/200 MA cross"},
    "short_hi52": {"tr": "52 hafta zirvesi", "en": "52-week high"},
    "short_lo52": {"tr": "52 hafta dibi", "en": "52-week low"},
    "short_vol": {"tr": "hacim 2×", "en": "volume 2×"},
    "tech_desc": {"tr": "📐 {name} · {sig}", "en": "📐 {name} · {sig}"},
    "tech_set": {"tr": "✅ <b>Teknik alarm kuruldu:</b> {desc}\n{now}\n"
                       "<i>Bu durum her oluştuğunda haber veririm.</i>",
                 "en": "✅ <b>Technical alert set:</b> {desc}\n{now}\n"
                       "<i>I'll ping you every time this happens.</i>"},
    "tech_dup": {"tr": "Bu teknik alarm zaten kurulu.", "en": "This technical alert is already set."},
    "tech_nodata": {"tr": "Bu varlık için yeterli geçmiş veri yok, bu teknik alarm kurulamadı.",
                    "en": "Not enough price history for this asset, so this technical alert can't be set."},
    "ts_rsi": {"tr": "Şu an RSI: <b>{v}</b>", "en": "RSI now: <b>{v}</b>"},
    "ts_ma": {"tr": "50 günlük ort. {a} · 200 günlük ort. {b} (50'lik şu an {pos})",
              "en": "50-day avg {a} · 200-day avg {b} (50-day is {pos} now)"},
    "ts_above": {"tr": "üstte", "en": "above"},
    "ts_below": {"tr": "altta", "en": "below"},
    "ts_hi": {"tr": "52 haftalık zirve: {v}", "en": "52-week high: {v}"},
    "ts_lo": {"tr": "52 haftalık dip: {v}", "en": "52-week low: {v}"},
    "ts_vol": {"tr": "Bugünkü hacim ortalamanın {x} katı", "en": "Today's volume is {x}× the average"},
    "tf_rsi_lo": {"tr": "📐 <b>{name}</b>: RSI {v} — aşırı satım bölgesine girdi (30 altı).",
                  "en": "📐 <b>{name}</b>: RSI {v} — entered oversold territory (below 30)."},
    "tf_rsi_hi": {"tr": "📐 <b>{name}</b>: RSI {v} — aşırı alım bölgesine girdi (70 üstü).",
                  "en": "📐 <b>{name}</b>: RSI {v} — entered overbought territory (above 70)."},
    "tf_gc": {"tr": "📐 <b>{name}</b>: Altın kesişim — 50 günlük ortalama 200 günlüğün üstüne çıktı.",
              "en": "📐 <b>{name}</b>: Golden cross — the 50-day average moved above the 200-day."},
    "tf_dc": {"tr": "📐 <b>{name}</b>: Ölüm kesişimi — 50 günlük ortalama 200 günlüğün altına indi.",
              "en": "📐 <b>{name}</b>: Death cross — the 50-day average moved below the 200-day."},
    "tf_hi52": {"tr": "📐 <b>{name}</b> son 52 haftanın en yükseğinde!", "en": "📐 <b>{name}</b> just hit a 52-week high!"},
    "tf_lo52": {"tr": "📐 <b>{name}</b> son 52 haftanın en düşüğünde!", "en": "📐 <b>{name}</b> just hit a 52-week low!"},
    "tf_vol": {"tr": "📐 <b>{name}</b>: bugünkü hacim 20 günlük ortalamanın {x} katı.",
               "en": "📐 <b>{name}</b>: today's volume is {x}× the 20-day average."},
    "tech_footer": {"tr": "<i>📐 Teknik alarm: tekrar olursa yine haber veririm. Sinyaldir, yatırım tavsiyesi değildir.</i>",
                    "en": "<i>📐 Technical alert: I'll ping you again next time. A signal, not investment advice.</i>"},
    # ---- v4: portfolio
    "pf_empty": {"tr": "💼 <b>Portföyün boş.</b>\n<b>➕ Ekle</b>'ye bas ya da şöyle yaz:\n"
                       "<code>/ekle BTC 0.5 60000</code> → 0,5 BTC, 60.000$'dan alındı\n"
                       "<code>/ekle THYAO 100</code> → alış fiyatı yazmazsan bugünkü fiyat kullanılır",
                 "en": "💼 <b>Your portfolio is empty.</b>\nTap <b>➕ Add</b> or type:\n"
                       "<code>/add BTC 0.5 60000</code> → 0.5 BTC bought at $60,000\n"
                       "<code>/add AAPL 10</code> → without a price, today's price is used"},
    "pf_title": {"tr": "💼 <b>Portföyün</b> · {t}", "en": "💼 <b>Your portfolio</b> · {t}"},
    "pf_row": {"tr": "{i}. <b>{name}</b> · {qty} × {cost} → {price}\n     Değer {value} · K/Z {pl} ({plp})",
               "en": "{i}. <b>{name}</b> · {qty} × {cost} → {price}\n     Value {value} · P/L {pl} ({plp})"},
    "pf_nopx": {"tr": "{i}. <b>{name}</b> · {qty} × {cost} · <i>fiyat alınamadı</i>",
                "en": "{i}. <b>{name}</b> · {qty} × {cost} · <i>price unavailable</i>"},
    "pf_total": {"tr": "<b>Toplam ({cur}):</b> {value} · K/Z {pl} ({plp})",
                 "en": "<b>Total ({cur}):</b> {value} · P/L {pl} ({plp})"},
    "pf_grand": {"tr": "≈ Hepsi birlikte: <b>{v}</b>", "en": "≈ All together: <b>{v}</b>"},
    "pf_hint": {"tr": "\n<i>Silmek için numarasına bas.</i>", "en": "\n<i>Tap a number to remove it.</i>"},
    "pf_ask": {"tr": "Ne ekleyelim? Sembol, miktar ve istersen alış fiyatı:\n"
                     "<code>BTC 0.5 60000</code> · <code>THYAO 100 280</code> · <code>altın 10</code>",
               "en": "What should I add? Symbol, amount and optionally the buy price:\n"
                     "<code>BTC 0.5 60000</code> · <code>AAPL 10 180</code> · <code>gold 2</code>"},
    "pf_ask_qty": {"tr": "Kaç <b>{name}</b> aldın? Miktar ve istersen alış fiyatı yaz:\n"
                         "<code>0.5</code> ya da <code>0.5 {p}</code>",
                   "en": "How much <b>{name}</b> did you buy? Type the amount and optionally the price:\n"
                         "<code>0.5</code> or <code>0.5 {p}</code>"},
    "pf_bad": {"tr": "Anlayamadım. Örnek: <code>BTC 0.5 60000</code>", "en": "I didn't get that. Example: <code>BTC 0.5 60000</code>"},
    "pf_added": {"tr": "✅ Portföye eklendi: <b>{name}</b> {qty} × {cost}", "en": "✅ Added to portfolio: <b>{name}</b> {qty} × {cost}"},
    "pf_max": {"tr": "Portföye en fazla {n} varlık ekleyebilirsin.", "en": "You can add up to {n} assets."},
    "pf_sum": {"tr": "💼 <b>Portföyün:</b> {x}", "en": "💼 <b>Your portfolio:</b> {x}"},
    "pf_gone": {"tr": "Bu varlık portföyde yok", "en": "Not in your portfolio"},
    # ---- v4: premium / Telegram Stars
    "prem_need": {"tr": "⭐ <b>Bu bir Premium özelliği.</b>\n{what}\n\n"
                        "Premium ile: sınırsız fiyat alarmı, teknik alarmlar (RSI, ortalama kesişimi, "
                        "52 hafta zirve/dip, hacim) ve portföy takibi.\n{price}",
                  "en": "⭐ <b>This is a Premium feature.</b>\n{what}\n\n"
                        "Premium gives you unlimited price alerts, technical alerts (RSI, moving-average cross, "
                        "52-week high/low, volume) and portfolio tracking.\n{price}"},
    "prem_why_alerts": {"tr": "Ücretsiz planda en fazla {n} fiyat alarmı kurabilirsin.",
                        "en": "The free plan includes up to {n} price alerts."},
    "prem_why_tech": {"tr": "Teknik alarmlar Premium'a dahil.", "en": "Technical alerts are part of Premium."},
    "prem_why_pf": {"tr": "Portföy takibi Premium'a dahil.", "en": "Portfolio tracking is part of Premium."},
    "prem_price": {"tr": "Fiyat: <b>{s} ⭐ Stars / {d} gün</b>", "en": "Price: <b>{s} ⭐ Stars / {d} days</b>"},
    "prem_perks": {"tr": "<b>Premium'da:</b> sınırsız fiyat alarmı · teknik alarmlar · portföy takibi\n"
                         "<b>Ücretsiz:</b> fiyatlar, grafikler, günlük özet ve {n} fiyat alarmı",
                   "en": "<b>Premium:</b> unlimited price alerts · technical alerts · portfolio tracking\n"
                         "<b>Free:</b> prices, charts, daily summary and {n} price alerts"},
    "btn_buy": {"tr": "⭐ Premium al — {s} Stars", "en": "⭐ Get Premium — {s} Stars"},
    "prem_status_on": {"tr": "⭐ <b>Premium aktif</b> — {date} tarihine kadar ({d} gün kaldı).",
                       "en": "⭐ <b>Premium is active</b> until {date} ({d} days left)."},
    "prem_status_trial": {"tr": "🎁 <b>Deneme süresindesin:</b> Premium özellikleri {d} gün daha açık.",
                          "en": "🎁 <b>You're on a free trial:</b> Premium features stay open for {d} more days."},
    "prem_status_free": {"tr": "♾ Tüm özellikler sana açık.", "en": "♾ Everything is unlocked for you."},
    "prem_status_off": {"tr": "Şu an ücretsiz plandasın (en fazla {n} fiyat alarmı).",
                        "en": "You're on the free plan (up to {n} price alerts)."},
    "prem_off_mode": {"tr": "Bu botta tüm özellikler ücretsiz. 🎉", "en": "Everything in this bot is free. 🎉"},
    "inv_title": {"tr": "Premium · {d} gün", "en": "Premium · {d} days"},
    "inv_desc": {"tr": "Sınırsız fiyat alarmı, teknik alarmlar ve portföy takibi — {d} gün. Otomatik yenilenmez.",
                 "en": "Unlimited price alerts, technical alerts and portfolio tracking for {d} days. Does not auto-renew."},
    "pay_err": {"tr": "Bu ödeme artık geçerli değil, lütfen /premium ile yeniden dene.",
                "en": "This payment is no longer valid, please try again with /premium."},
    "prem_thanks": {"tr": "🎉 <b>Teşekkürler! Premium aktif.</b>\n{date} tarihine kadar tüm özellikler açık.",
                    "en": "🎉 <b>Thank you! Premium is active.</b>\nEverything is unlocked until {date}."},
    "prem_owner": {"tr": "⭐ {name} (<code>{cid}</code>) {s} Stars ödedi. Premium: {date}",
                   "en": "⭐ {name} (<code>{cid}</code>) paid {s} Stars. Premium until {date}"},
    "prem_warn": {"tr": "⭐ Premium'un {d} gün sonra bitiyor. Kesintisiz devam etmek için yenileyebilirsin.",
                  "en": "⭐ Your Premium ends in {d} days. Renew to keep everything running."},
    "prem_ended": {"tr": "⭐ Premium süren doldu. Bot ücretsiz planla çalışmaya devam ediyor "
                         "(en fazla {n} fiyat alarmı; teknik alarmlar durdu, silinmedi).",
                   "en": "⭐ Your Premium has ended. The bot keeps working on the free plan "
                         "(up to {n} price alerts; technical alerts are paused, not deleted)."},
    "trial_end_free": {"tr": "⏳ <b>Deneme süren doldu.</b>\nBot ücretsiz planla çalışmaya devam ediyor: en fazla {n} "
                             "fiyat alarmı. Teknik alarmlar ve portföy Premium'da; alarmların silinmedi.",
                       "en": "⏳ <b>Your trial has ended.</b>\nThe bot keeps working on the free plan: up to {n} price "
                             "alerts. Technical alerts and the portfolio are Premium; nothing was deleted."},
    "trial_warn_prem": {"tr": "⏳ Deneme süren {d} gün sonra bitiyor. Sonrasında ücretsiz plan devam eder; "
                              "tüm özellikler için Premium alabilirsin.",
                        "en": "⏳ Your trial ends in {d} days. After that the free plan continues; "
                              "get Premium to keep everything."},
    "paused_hint": {"tr": "⏸ = ücretsiz planda duraklatıldı, Premium ile çalışır.",
                    "en": "⏸ = paused on the free plan, works with Premium."},
    "paysupport": {"tr": "💬 <b>Ödeme desteği</b>\nSorununu şöyle yaz, doğrudan bot sahibine iletilir:\n"
                         "<code>/paysupport mesajın</code>{c}",
                   "en": "💬 <b>Payment support</b>\nWrite your issue like this and it goes straight to the bot owner:\n"
                         "<code>/paysupport your message</code>{c}"},
    "ps_sent": {"tr": "✅ Mesajın iletildi, en kısa sürede dönüş yapılacak.", "en": "✅ Sent. You'll get a reply soon."},
    "ps_owner": {"tr": "💬 <b>Ödeme desteği</b> — {name} (<code>{cid}</code>):\n{msg}",
                 "en": "💬 <b>Payment support</b> — {name} (<code>{cid}</code>):\n{msg}"},
    "terms": {"tr": "📄 <b>Kullanım koşulları</b>\n"
                    "• Bot fiyat bildirimleri gönderir; yatırım tavsiyesi vermez.\n"
                    "• Veriler ücretsiz kaynaklardan gelir, gecikmeli olabilir; bildirimlerin zamanında ulaşması "
                    "garanti edilmez.\n"
                    "• Premium, satın alındığı sohbet için {d} gün geçerlidir ve otomatik yenilenmez.\n"
                    "• Ödeme sorunları ve iade talepleri için: /paysupport",
              "en": "📄 <b>Terms</b>\n"
                    "• The bot sends price notifications; it does not give investment advice.\n"
                    "• Data comes from free sources and may be delayed; timely delivery is not guaranteed.\n"
                    "• Premium is valid for {d} days in the chat where it was bought and does not auto-renew.\n"
                    "• For payment issues and refund requests: /paysupport"},
    "grant_usage": {"tr": "Kullanım: <code>/premiumver 12345678 30</code> (gün)", "en": "Usage: <code>/grant 12345678 30</code> (days)"},
    "granted_prem": {"tr": "⭐ {cid} için {d} gün Premium tanımlandı.", "en": "⭐ Gave {cid} {d} days of Premium."},
    "prem_gift": {"tr": "🎁 Sana {d} gün Premium tanımlandı!", "en": "🎁 You've been given {d} days of Premium!"},
    "refund_usage": {"tr": "Kullanım: <code>/iade 12345678</code> — o kişinin son ödemesini iade eder",
                     "en": "Usage: <code>/refund 12345678</code> — refunds that person's last payment"},
    "refund_done": {"tr": "↩️ {cid} kişisinin {s} Stars ödemesi iade edildi, Premium kapatıldı.",
                    "en": "↩️ Refunded {s} Stars to {cid} and ended their Premium."},
    "refund_fail": {"tr": "İade yapılamadı (ödeme bulunamadı ya da Telegram reddetti).",
                    "en": "Refund failed (no payment found, or Telegram refused it)."},
    "refunded": {"tr": "↩️ Ödemen iade edildi ve Premium kapatıldı.", "en": "↩️ Your payment was refunded and Premium ended."},
    "adm_prem": {"tr": "\n⭐ Premium: {n} aktif · toplam {s} Stars ({p} ödeme) · fiyat {price} Stars",
                 "en": "\n⭐ Premium: {n} active · {s} Stars total ({p} payments) · price {price} Stars"},
    "st_premium": {"tr": "⭐ premium {d} gün", "en": "⭐ premium {d}d"},
}


def T(key, lg, /, **kw):
    """Translated text. Positional-only so templates can use {lang} themselves."""
    entry = S[key]
    text = entry.get(lg) or entry.get(DEFAULT_LANG) or entry["tr"]
    return text.format(**kw) if kw else text


# ---------------------------------------------------------------- small helpers
def e(x):
    return html.escape(str(x), quote=False)


def tz_for(region):
    return pytz.timezone(REGION_TZ.get(region) or REGION_TZ[DEFAULT_REGION])


def now_local(tz=None):
    return datetime.now(tz or tz_for(DEFAULT_REGION))


def read_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        s = {}
    for k, v in (("offset", 0), ("next_id", 1), ("alerts", []), ("users", {}), ("pending", {}),
                 ("summaries", {}), ("allowed", []), ("private_mode", None), ("requests", {}),
                 ("stats", {"fired_total": 0, "day": "", "fired_today": 0}), ("cmds_v", ""),
                 ("portfolios", {}), ("payments", [])):
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


def prefs(state, chat_id):
    """(lang, region) for a chat."""
    u = state["users"].get(str(chat_id)) or {}
    lang = u.get("lang") if u.get("lang") in LANGS else DEFAULT_LANG
    region = u.get("region") if u.get("region") in REGIONS else DEFAULT_REGION
    return lang, region


def owner_lang(state):
    return prefs(state, OWNER_CHAT_ID)[0] if OWNER_CHAT_ID else DEFAULT_LANG


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


def fmt_pct(c, lang, signed=True):
    """tr: %+1.2 / %−1.2   en: +1.2% / −1.2%"""
    body = f"{abs(c):.1f}"
    sign = ("+" if c >= 0 else "−") if signed else ""
    return f"%{sign}{body}" if lang == "tr" else f"{sign}{body}%"


def fmt_chg(c, lang=None):
    if c is None:
        return ""
    arrow = "🟢" if c > 0.05 else ("🔴" if c < -0.05 else "⚪")
    return f"{arrow} {fmt_pct(c, lang or DEFAULT_LANG)}"


def nice_round(x):
    """Round to 4 significant digits: 66,321 -> 66,320 ; 4.3517 -> 4.352"""
    if x <= 0:
        return x
    m = 10 ** (math.floor(math.log10(x)) - 3)
    return round(round(x / m) * m, 10)


def parse_number(text):
    """'70000', '70.000', '70,000', '1.234,5', '0.1234', '70k', '$70,5' -> float (None if invalid)."""
    s = str(text).strip().lower().replace("$", "").replace("₺", "").replace("€", "").replace("tl", "").replace(" ", "")
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


def normalize_symbol(sym, region=None):
    region = region or DEFAULT_REGION
    s = str(sym).translate(TR_MAP).strip().upper().replace(" ", "").lstrip("$#")
    ra = REGION_ALIASES["tr"] if region == "tr" else REGION_ALIASES["*"]

    def alias(x):
        if x in SPECIAL:
            return x
        return ra.get(x) or ALIASES.get(x) or (x if x in ("GRAMALTIN", "GRAMGUMUS") else None)

    if alias(s):
        return alias(s)
    s = s.replace("-TRY", "TRY").replace("/TRY", "TRY")
    for suffix in ("-USDT", "-USD", "/USDT", "/USD", "USDT", "USD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    if alias(s):
        return alias(s)
    if not re.fullmatch(r"[A-Z0-9.\-^=]{1,15}", s) or not re.search(r"[A-Z]", s):
        return None
    return s


def name_of(key, lang):
    if key in SPECIAL:
        return SPECIAL[key]["name"].get(lang) or SPECIAL[key]["name"]["tr"]
    if key.endswith(".IS"):
        return key[:-3]
    if key.endswith("TRY") and len(key) > 3 and "." not in key:
        return f"{name_of(key[:-3], lang)}/{'TL' if lang == 'tr' else 'TRY'}"
    return key


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


def get_quote(sym, region=None):
    """dict(key, name, price, cur, chg) or None. Accepts user input or a stored key."""
    key = normalize_symbol(sym, region) if sym else None
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
                    q = dict(key=key, price=r[0] * fx[0] / GRAMS_PER_OZ, cur="₺", chg=_combine(_chg(r), _chg(fx)))
            else:
                q = dict(key=key, price=r[0], cur=sp["cur"], chg=_chg(r))
    elif key.endswith("TRY") and len(key) > 3 and "." not in key:
        base = get_quote(key[:-3], region)
        fx = yahoo_raw("USDTRY=X")
        if base and base["cur"] == "$" and fx:
            q = dict(key=key, price=base["price"] * fx[0], cur="₺", chg=_combine(base["chg"], _chg(fx)))
    else:
        if not re.search(r"[.=^]", key):
            r = crypto_raw(key)
            if r:
                q = dict(key=key, price=r[0], cur="$", chg=_chg(r))
        if q is None:
            r = yahoo_raw(key)
            if r:
                q = dict(key=key, price=r[0], cur="₺" if key.endswith(".IS") else "$", chg=_chg(r))
        if q is None and "." not in key:
            r = yahoo_raw(key + ".IS")
            if r:
                q = dict(key=key + ".IS", price=r[0], cur="₺", chg=_chg(r))
    if q:
        q["name"] = name_of(q["key"], "tr")
    _cache[ck] = q
    return q


def local_equiv(q, region):
    """≈ value in the region's own currency, for dollar prices."""
    if q["cur"] != "$":
        return ""
    if region == "tr":
        fx = yahoo_raw("USDTRY=X")
        return f"\n≈ {fmt_price(q['price'] * fx[0], '₺')}" if fx else ""
    if region == "eu":
        fx = yahoo_raw("EURUSD=X")
        return f"\n≈ {fmt_price(q['price'] / fx[0], '€')}" if fx else ""
    return ""


def is_delayed(key):
    """Yahoo data (stocks, indices, gold, FX) is ~15 min delayed; Coinbase crypto is live."""
    return bool(re.search(r"[.=^]", key)) or key in SPECIAL or key.endswith("TRY")


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


CMD_MENU = {
    "tr": [("alarm", "Alarm kur"), ("fiyat", "Anlık fiyat"), ("liste", "Alarmlarım"), ("portfoy", "Portföyüm"),
           ("ozet", "Günlük piyasa özeti"), ("ayarlar", "Dil ve bölge"), ("yardim", "Nasıl kullanılır")],
    "en": [("alert", "Set a price alert"), ("price", "Live price"), ("list", "My alerts"), ("portfolio", "My portfolio"),
           ("summary", "Daily market summary"), ("settings", "Language and region"), ("help", "How it works")],
}


def set_commands(state):
    ver = f"{VERSION}-{1 if PREMIUM_STARS else 0}"
    if state.get("cmds_v") == ver:
        return
    extra = {"tr": [("premium", "Premium üyelik"), ("paysupport", "Ödeme desteği"), ("terms", "Koşullar")],
             "en": [("premium", "Premium"), ("paysupport", "Payment support"), ("terms", "Terms")]}

    def menu(lg):
        return [{"command": c, "description": d} for c, d in CMD_MENU[lg] + (extra[lg] if PREMIUM_STARS else [])]
    ok = tg("setMyCommands", commands=menu("en"))
    tg("setMyCommands", commands=menu("tr"), language_code="tr")
    if ok:
        state["cmds_v"] = ver


# ---------------------------------------------------------------- views
def main_kb(lang):
    last = [T("b_help", lang)] + ([T("b_prem", lang)] if PREMIUM_STARS else [])
    return {"keyboard": [[T("b_alarm", lang), T("b_price", lang)], [T("b_list", lang), T("b_port", lang)],
                         [T("b_sum", lang), T("b_settings", lang)], last],
            "resize_keyboard": True, "is_persistent": True}


MAIN_KB = main_kb(DEFAULT_LANG)                                 # backwards compatibility


def help_text(private=True, lang=None, region=None):
    lang, region = lang or DEFAULT_LANG, region or DEFAULT_REGION
    title = BOT_TITLE or T("title", lang)
    t = f"🔔 <b>{html.escape(title)}</b>\n{T('intro', lang)}\n\n"
    t += (T("howto", lang, ex=EX_HELP[(lang, region)]) if private else T("howto_group", lang)) + "\n\n"
    return t + T("cmds", lang) + "\n\n" + T("disclaimer", lang)


def group_menu(lang):
    return ikb([[(T("b_alarm", lang), "m|alarm"), (T("b_price", lang), "m|price")],
                [(T("b_list", lang), "m|list"), (T("b_sum", lang), "m|sum")],
                [(T("b_settings", lang), "m|settings")]])


def popular_for(region):
    return [s.strip() for s in (ENV_POPULAR or REGION_POPULAR[region]).split(",") if s.strip()]


def asset_picker(prefix, lang=None, region=None):
    lang, region = lang or DEFAULT_LANG, region or DEFAULT_REGION
    rows, row = [], []
    for s in popular_for(region):
        key = normalize_symbol(s, region)
        if not key:
            continue
        row.append((name_of(key, lang), f"{prefix}|{key}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    rows.append(row)
    rows.append([(T("btn_other", lang), f"{prefix}|*")])
    return ikb(rows)


def price_view(q, lang=None, region=None):
    lang, region = lang or DEFAULT_LANG, region or DEFAULT_REGION
    text = f"💱 <b>{e(name_of(q['key'], lang))}</b>: {fmt_price(q['price'], q['cur'])}"
    if q["chg"] is not None:
        text += f"  {fmt_chg(q['chg'], lang)} <i>{T('today_tag', lang)}</i>"
    text += local_equiv(q, region)
    if is_delayed(q["key"]):
        text += "\n" + T("delayed", lang)
    kb = ikb([[(T("btn_set_alert", lang), f"aa|{q['key']}"), (T("btn_chart", lang), f"ch|{q['key']}|1d")],
              [(T("btn_refresh", lang), f"pq|{q['key']}"), (T("btn_to_pf", lang), f"pp|{q['key']}")]])
    return text, kb


def level_picker(q, lang=None):
    lang = lang or DEFAULT_LANG
    p, cur, k = q["price"], q["cur"], q["key"]
    text = (T("lp_now", lang, name=e(name_of(k, lang)), price=fmt_price(p, cur))
            + (T("lp_today", lang, chg=fmt_chg(q["chg"], lang)) if q["chg"] is not None else "")
            + "\n" + T("lp_ask", lang))

    def lab(sign, n, value):
        pct = f"%{n}" if lang == "tr" else f"{n}%"
        return f"{'📈' if sign == '+' else '📉'} {sign}{pct} → {fmt_price(value, cur)}"

    def btn(sign, n):                       # the level shown on the button travels with it
        v = nice_round(p * (1 + n / 100 if sign == "+" else 1 - n / 100))
        return lab(sign, n, v), f"al|{k}|{'u' if sign == '+' else 'd'}|{n}|{v:.10g}"
    up = [btn("+", n) for n in (2, 5, 10)]
    dn = [btn("−", n) for n in (2, 5, 10)]
    kb = ikb([up[:2], [up[2], dn[0]], dn[1:],
              [(T("btn_move", lang, n=3), f"am|{k}|3"), (T("btn_move", lang, n=5), f"am|{k}|5")],
              [(T("btn_write", lang), f"aw|{k}"), (T("btn_tech", lang), f"tm|{k}")]])
    return text, kb


def describe(a, lang=None):
    lang = lang or DEFAULT_LANG
    cur, name = a.get("currency", "$"), e(name_of(a["symbol"], lang))
    rep = "🔁 " if a.get("repeat") else ""
    if a["kind"] == "tech":
        return T("tech_desc", lang, name=name, sig=T("short_" + a["sig"], lang))
    if a["kind"] == "above":
        return f"{rep}{name} ≥ {fmt_price(a['level'], cur)}"
    if a["kind"] == "below":
        return f"{rep}{name} ≤ {fmt_price(a['level'], cur)}"
    return T("move_desc", lang, rep=rep, name=name, pct=f"{a['pct']:g}", ref=fmt_price(a["ref"], cur))


def alert_kb(a, lang=None):
    lang = lang or DEFAULT_LANG
    return ikb([[(T("btn_once", lang) if a.get("repeat") else T("btn_repeat", lang), f"rp|{a['id']}"),
                 (T("btn_cancel", lang), f"dl|{a['id']}")]])


def user_alerts(state, chat_id):
    return [a for a in state["alerts"] if a["chat_id"] == chat_id]


def list_view(state, chat_id):
    lang, _ = prefs(state, chat_id)
    mine = user_alerts(state, chat_id)
    if not mine:
        return T("no_alerts", lang), ikb([[(T("btn_add", lang), "m|alarm")]])
    paused = silent_ids(state, chat_id)
    lines = [T("list_title", lang, n=len(mine))] + [f"{i}. {'⏸ ' if a['id'] in paused else ''}{describe(a, lang)}"
                                                    for i, a in enumerate(mine, 1)]
    lines.append(T("list_hint", lang))
    if paused:
        lines.append(T("paused_hint", lang))
    btns = [(f"🗑 {i}", f"dl|{a['id']}|L") for i, a in enumerate(mine, 1)]
    rows = [btns[i:i + 5] for i in range(0, len(btns), 5)]
    rows.append([(T("btn_del_all", lang), "dla"), (T("btn_new", lang), "m|alarm")])
    return "\n".join(lines), ikb(rows)


def summary_kb(state, chat_id):
    lang, _ = prefs(state, chat_id)
    sub = state["summaries"].get(str(chat_id))
    if sub:
        return ikb([[(T("btn_sum_off", lang, t=sub["time"]), "ss|off")]])
    return ikb([[(T("btn_sum_on", lang, t=SUMMARY_TIME), "ss|on")]])


def build_summary(lang=None, region=None):
    lang, region = lang or DEFAULT_LANG, region or DEFAULT_REGION
    now = now_local(tz_for(region))
    dt = now.strftime("%d.%m.%Y %H:%M") if lang == "tr" else now.strftime("%d %b %Y, %H:%M")
    lines = [T("sum_title", lang, dt=dt), ""]
    for s in (ENV_SUMMARY or REGION_SUMMARY[region]).split(","):
        q = get_quote(s.strip(), region)
        if q:
            lines.append(f"{e(name_of(q['key'], lang))}: <b>{fmt_price(q['price'], q['cur'])}</b>  {fmt_chg(q['chg'], lang)}")
    movers = []
    for t in REGION_MOVERS.get(region, []):
        c = _chg(yahoo_raw(t))
        if c is not None:
            movers.append((c, t.replace(".IS", "")))
    if len(movers) >= 5:
        movers.sort(reverse=True)
        up = " · ".join(f"{t} {fmt_pct(c, lang)}" for c, t in movers[:3] if c > 0)
        dn = " · ".join(f"{t} {fmt_pct(c, lang)}" for c, t in movers[::-1][:3] if c < 0)
        lines.append("")
        if up:
            lines.append(T("movers_up", lang, x=up))
        if dn:
            lines.append(T("movers_dn", lang, x=dn))
    lines.append(T("sum_footer", lang))
    return "\n".join(lines)


def admin_view(state):
    lang = owner_lang(state)
    users = state["users"]
    groups = sum(1 for u in users.values() if u.get("type") != "private")
    st = state["stats"]
    counts = {}
    for u in users.values():
        if u.get("lang"):
            counts[u["lang"]] = counts.get(u["lang"], 0) + 1
    langs = " · ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "—"
    trial = ""
    if TRIAL_DAYS:
        trial += T("adm_trial", lang, d=TRIAL_DAYS, u=sum(1 for u in users.values() if u.get("no_trial")))
    if TRIAL_UNTIL:
        trial += T("adm_until", lang, d=TRIAL_UNTIL)
    if PREMIUM_STARS:
        now = time.time()
        trial += T("adm_prem", lang, n=sum(1 for u in users.values() if u.get("premium_until", 0) > now),
                   s=st.get("stars_total", 0), p=len(state.get("payments", [])), price=PREMIUM_STARS)
    text = T("admin", lang, v=VERSION, p=len(users) - groups, g=groups, langs=langs, n=len(state["alerts"]),
             r=sum(1 for a in state["alerts"] if a.get("repeat")), subs=len(state["summaries"]),
             fd=st.get("fired_today", 0), ft=st.get("fired_total", 0), trial=trial,
             pm=T("on", lang) if state["private_mode"] else T("off", lang),
             al=len(set(state["allowed"]) | ENV_ALLOWED))
    kb = ikb([[(T("btn_pm_off", lang) if state["private_mode"] else T("btn_pm_on", lang), "ad|pm"),
               (T("btn_refresh", lang), "ad|st")]])
    return text, kb


def lang_picker(first="tr"):
    order = ["tr", "en"] if first == "tr" else ["en", "tr"]
    flags = {"tr": "🇹🇷 Türkçe", "en": "🇬🇧 English"}
    return ikb([[(flags[x], f"lg|{x}") for x in order]])


def region_picker(lang):
    n = REGION_NAME[lang]
    return ikb([[(n["tr"], "rg|tr"), (n["us"], "rg|us")], [(n["eu"], "rg|eu"), (n["global"], "rg|global")]])


def settings_view(state, chat_id):
    lang, region = prefs(state, chat_id)
    text = T("settings", lang, lang=LANG_NAME[lang], region=REGION_NAME[lang][region], tz=REGION_TZ[region])
    return text, ikb([[(T("btn_lang", lang), "st|lang"), (T("btn_region", lang), "st|region")]])


# ---------------------------------------------------------------- history (charts + technical alerts)
_hist = {}
SPANS = ("1d", "1w", "1m", "1y")
SPAN_LABEL = {"tr": {"1d": "1G", "1w": "1H", "1m": "1A", "1y": "1Y"},
              "en": {"1d": "1D", "1w": "1W", "1m": "1M", "1y": "1Y"}}
HIST_TTL = {"1d": 120, "1w": 600, "1m": 1800, "1y": 1800}
CB_GRAN = {"1d": (300, 86400), "1w": (3600, 7 * 86400), "1m": (21600, 30 * 86400), "1y": (86400, 365 * 86400)}
YF_SPAN = {"1d": ("1d", "5m"), "1w": ("5d", "30m"), "1m": ("1mo", "60m"), "1y": ("1y", "1d")}


def _iso(ts):
    return datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def coinbase_hist(sym, span):
    """(times, closes, volumes) from Coinbase candles, oldest first, or None."""
    gran, total = CB_GRAN[span]
    end = int(time.time())
    s, rows = end - total, {}
    while s < end:
        chunk_end = min(end, s + gran * 300)                  # Coinbase returns at most 300 candles
        r = requests.get(f"{CB_API}/products/{sym}-USD/candles", headers=HTTP_HEADERS, timeout=10,
                         params={"granularity": gran, "start": _iso(s), "end": _iso(chunk_end)})
        if not r.ok:
            break
        for row in r.json() or []:
            rows[int(row[0])] = row                           # [time, low, high, open, close, volume]
        s = chunk_end
    if len(rows) < 2:
        return None
    ks = sorted(rows)
    return ([datetime.fromtimestamp(k, pytz.utc) for k in ks], [float(rows[k][4]) for k in ks],
            [float(rows[k][5]) for k in ks])


def yahoo_hist(ticker, span):
    import yfinance as yf
    period, interval = YF_SPAN[span]
    t = yf.Ticker(ticker)
    h = t.history(period=period, interval=interval)
    if span == "1d" and (h is None or len(h) < 2):            # market closed today: show the last session
        h = t.history(period="5d", interval=interval)
        if h is not None and len(h):
            last_day = h.index[-1].date()
            h = h[[ix.date() == last_day for ix in h.index]]
    if h is None or not len(h):
        return None
    h = h.dropna(subset=["Close"])
    if len(h) < 2:
        return None
    times = []
    for ix in h.index:
        d = ix.to_pydatetime() if hasattr(ix, "to_pydatetime") else ix
        times.append(d if d.tzinfo else pytz.utc.localize(d))
    vols = [float(x) for x in h["Volume"]] if "Volume" in h else None
    return times, [float(x) for x in h["Close"]], vols


def _series_mul(a, b, div=1.0):
    """a × b (b aligned to a by last known value) / div — e.g. gold($/oz) × USDTRY / 31.1."""
    if not a or not b:
        return None
    import bisect
    tb = [t.timestamp() for t in b[0]]
    out_t, out_c = [], []
    for t, c in zip(a[0], a[1]):
        i = bisect.bisect_right(tb, t.timestamp()) - 1
        if i < 0:
            i = 0
        out_t.append(t)
        out_c.append(c * b[1][i] / div)
    return (out_t, out_c, None) if len(out_c) >= 2 else None


def _history(key, span):
    if key in SPECIAL:
        sp = SPECIAL[key]
        base = yahoo_hist(sp["yahoo"], span)
        if sp.get("gram"):
            return _series_mul(base, yahoo_hist("USDTRY=X", span), GRAMS_PER_OZ)
        return base
    if key.endswith("TRY") and len(key) > 3 and "." not in key:
        return _series_mul(history(key[:-3], span), yahoo_hist("USDTRY=X", span))
    if not re.search(r"[.=^]", key) and crypto_raw(key):
        h = coinbase_hist(key, span)
        if h:
            return h
    return yahoo_hist(key, span)


def history(key, span):
    """(times, closes, volumes|None), cached for a few minutes so loops don't hammer the APIs."""
    ck, now = (key, span), time.time()
    hit = _hist.get(ck)
    if hit and now - hit[0] < HIST_TTL[span]:
        return hit[1]
    try:
        res = _history(key, span)
    except Exception as ex:
        log.warning("History %s %s: %s", key, span, ex)
        res = None
    _hist[ck] = (now, res)
    return res


def cur_of(key):
    if key in SPECIAL:
        return "₺" if SPECIAL[key].get("gram") else SPECIAL[key]["cur"]
    if key.endswith(".IS") or (key.endswith("TRY") and len(key) > 3):
        return "₺"
    return "$"


# ---------------------------------------------------------------- charts
def make_chart(key, span, lang, region):
    """-> (png_bytes, last_price, change_%) or None"""
    h = history(key, span)
    if not h or len(h[1]) < 2:
        return None
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    t, c = h[0], h[1]
    cur = cur_of(key)
    chg = (c[-1] / c[0] - 1) * 100 if c[0] else 0.0
    col, bg = ("#22c55e" if chg >= 0 else "#ef4444"), "#0f1a2b"
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    lo, hi = min(c), max(c)
    pad = (hi - lo) * 0.08 or hi * 0.01
    ax.plot(t, c, color=col, lw=2)
    ax.fill_between(t, c, lo - pad, color=col, alpha=0.12)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(t[0], t[-1])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors="#8aa0b8", labelsize=9, length=0)
    ax.grid(axis="y", color="#1e2d44", lw=0.8)
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "" if v <= 0 else f"{v:,.0f}" if v >= 1000 else fmt_num(v)))
    tz = tz_for(region)
    loc = mdates.AutoDateLocator(tz=tz, minticks=3, maxticks=7)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(
        {"1d": "%H:%M", "1w": "%d.%m", "1m": "%d.%m", "1y": "%m.%Y"}[span], tz=tz))
    ax.set_title(f"{name_of(key, lang)}  ·  {SPAN_LABEL[lang][span]}", loc="left", color="#e8eef6",
                 fontsize=13, fontweight="bold")
    sign = "+" if chg >= 0 else "−"
    ax.set_title(f"{fmt_price(c[-1], cur)}   {sign}{abs(chg):.2f}%", loc="right", color=col, fontsize=12)
    fig.text(0.01, 0.01, BOT_TITLE or T("title", lang), color="#4b5d75", fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue(), c[-1], chg


def tg_file(method, files, **params):
    """Multipart call (sendPhoto / editMessageMedia)."""
    if not TELEGRAM_TOKEN:
        return None
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in params.items()}
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", data=data, files=files,
                          timeout=30)
        d = r.json()
        if not d.get("ok"):
            log.error("Telegram %s failed: %s", method, str(d.get("description", d))[:200])
            return None
        return d.get("result")
    except Exception as ex:
        log.error("Telegram %s error: %s", method, ex)
        return None


def chart_kb(key, span, lang):
    lab = SPAN_LABEL[lang]
    return ikb([[(("• " if s == span else "") + lab[s], f"ch|{key}|{s}") for s in SPANS],
                [(T("btn_set_alert", lang), f"aa|{key}"), (T("btn_tech", lang), f"tm|{key}")]])


def send_chart(state, chat_id, key, span="1d", mid=None):
    """Sends (or, with mid, replaces) a chart photo. -> True/False"""
    lang, region = prefs(state, chat_id)
    res = make_chart(key, span, lang, region)
    if not res:
        return False
    png, last, chg = res
    cap = T("chart_cap", lang, name=e(name_of(key, lang)), span=SPAN_LABEL[lang][span],
            price=fmt_price(last, cur_of(key)), chg=fmt_chg(chg, lang))
    if is_delayed(key):
        cap += "\n" + T("delayed", lang)
    kb = chart_kb(key, span, lang)
    if mid and tg_file("editMessageMedia", {"p": ("chart.png", png, "image/png")}, chat_id=chat_id,
                       message_id=mid, reply_markup=kb,
                       media={"type": "photo", "media": "attach://p", "caption": cap, "parse_mode": "HTML"}):
        return True
    return tg_file("sendPhoto", {"photo": ("chart.png", png, "image/png")}, chat_id=chat_id, caption=cap,
                   parse_mode="HTML", reply_markup=kb) is not None


# ---------------------------------------------------------------- technical alerts
TECH_SIGS = ("rsi_lo", "rsi_hi", "ma", "hi52", "lo52", "vol")
TECH_NEED = {"rsi_lo": 30, "rsi_hi": 30, "ma": 201, "hi52": 60, "lo52": 60, "vol": 21}


def rsi(c, n=14):
    """Wilder's RSI of the last close."""
    if len(c) < n + 1:
        return None
    gains = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _mean(x):
    return sum(x) / len(x)


def tech_values(sig, h):
    """Numbers a signal looks at, or None when the data is too short."""
    c, v = h[1], h[2]
    if len(c) < TECH_NEED[sig]:
        return None
    if sig in ("rsi_lo", "rsi_hi"):
        return {"rsi": rsi(c)}
    if sig == "ma":
        return {"s50": _mean(c[-50:]), "s200": _mean(c[-200:])}
    if sig in ("hi52", "lo52"):
        past = c[-253:-1]
        return {"hi": max(past), "lo": min(past), "price": c[-1]}
    if not v or len(v) < 21:
        return None
    avg = _mean(v[-21:-1])
    return {"x": v[-1] / avg} if avg > 0 else None


def tech_condition(sig, val):
    if sig == "rsi_lo":
        return val["rsi"] < 30
    if sig == "rsi_hi":
        return val["rsi"] > 70
    if sig == "hi52":
        return val["price"] > val["hi"]
    if sig == "lo52":
        return val["price"] < val["lo"]
    if sig == "vol":
        return val["x"] >= 2
    return val["s50"] > val["s200"]                                  # ma: True = 50-day above 200-day


def tech_rearm(sig, val):
    """Hysteresis, so a signal hovering at the threshold doesn't fire again and again."""
    if sig == "rsi_lo":
        return val["rsi"] > 35
    if sig == "rsi_hi":
        return val["rsi"] < 65
    if sig == "hi52":
        return val["price"] < val["hi"] * 0.97
    if sig == "lo52":
        return val["price"] > val["lo"] * 1.03
    return False


def tech_status(sig, val, cur, lang):
    if sig in ("rsi_lo", "rsi_hi"):
        return T("ts_rsi", lang, v=f"{val['rsi']:.1f}")
    if sig == "ma":
        return T("ts_ma", lang, a=fmt_price(val["s50"], cur), b=fmt_price(val["s200"], cur),
                 pos=T("ts_above" if val["s50"] > val["s200"] else "ts_below", lang))
    if sig == "hi52":
        return T("ts_hi", lang, v=fmt_price(val["hi"], cur))
    if sig == "lo52":
        return T("ts_lo", lang, v=fmt_price(val["lo"], cur))
    return T("ts_vol", lang, x=f"{val['x']:.1f}")


def tech_picker(key, lang):
    rows = [[(T("sig_" + s, lang), f"ta|{key}|{s}")] for s in TECH_SIGS]
    return T("tech_pick", lang, name=e(name_of(key, lang))), ikb(rows)


def add_tech(state, chat_id, key, sig):
    """-> (text, kb)"""
    lang, region = prefs(state, chat_id)
    if sig not in TECH_SIGS:
        return T("tech_nodata", lang), None
    if not is_premium(state, chat_id):
        return premium_needed(state, chat_id, "prem_why_tech")
    mine = user_alerts(state, chat_id)
    if len(mine) >= MAX_ALERTS_PER_CHAT:
        return T("max_alerts", lang, n=MAX_ALERTS_PER_CHAT), ikb([[(T("btn_my_alerts", lang), "m|list")]])
    q = get_quote(key, region)
    if not q:
        return T("not_found", lang, sym=e(key), ex=EX_SHORT[(lang, region)]), None
    key = q["key"]
    if any(a.get("kind") == "tech" and a["symbol"] == key and a.get("sig") == sig for a in mine):
        return T("tech_dup", lang), ikb([[(T("btn_my_alerts", lang), "m|list")]])
    h = history(key, "1y")
    val = tech_values(sig, h) if h else None
    if not val:
        return T("tech_nodata", lang), None
    a = {"id": state["next_id"], "chat_id": chat_id, "symbol": key, "name": q["name"], "currency": q["cur"],
         "created": time.time(), "kind": "tech", "sig": sig, "checked": time.time(), "fired": 0}
    cond = tech_condition(sig, val)
    if sig == "ma":
        a["above"] = cond
    elif sig == "vol":
        a["last_day"] = now_local().strftime("%Y-%m-%d") if cond else ""
    else:
        a["armed"] = not cond                                       # already true now: wait for the next time
    state["alerts"].append(a)
    state["next_id"] += 1
    return (T("tech_set", lang, desc=describe(a, lang), now=tech_status(sig, val, q["cur"], lang)),
            ikb([[(T("btn_cancel", lang), f"dl|{a['id']}"), (T("btn_chart", lang), f"ch|{key}|1y")]]))


def tech_check(a):
    """Evaluates one technical alert. -> (text_key, kw) when it fires, else None. Updates a's state."""
    h = history(a["symbol"], "1y")
    val = tech_values(a["sig"], h) if h else None
    if not val:
        return None
    sig, cond = a["sig"], tech_condition(a["sig"], val)
    if sig == "ma":
        prev, a["above"] = a.get("above"), cond
        if prev is not None and prev != cond:
            return ("tf_gc" if cond else "tf_dc"), {}
        return None
    if sig == "vol":
        today = now_local().strftime("%Y-%m-%d")
        if cond and a.get("last_day") != today:
            a["last_day"] = today
            return "tf_vol", {"x": f"{val['x']:.1f}"}
        return None
    if cond and a.get("armed", True):
        a["armed"] = False
        return "tf_" + sig, {"v": f"{val.get('rsi', 0):.1f}"}
    if not cond and tech_rearm(sig, val):
        a["armed"] = True
    return None


# ---------------------------------------------------------------- portfolio
def positions(state, chat_id):
    return state["portfolios"].get(str(chat_id)) or []


def fmt_qty(x):
    return f"{x:,.8f}".rstrip("0").rstrip(".")


def fmt_signed(x, cur):
    return ("+" if x >= 0 else "−") + fmt_price(abs(x), cur)


def parse_position(text):
    """'BTC 0.5 60000' / 'gram altın 10' / 'THYAO 100 @ 280 TL' -> (sym, qty, cost|None) or None"""
    m = re.fullmatch(r"(.+?)\s+([0-9][0-9.,]*)(?:\s+@?\s*([$€₺]?\s*[0-9][0-9.,]*\s*[kK]?)\s*(?:tl|TL|₺|\$|€)?)?",
                     (text or "").strip())
    if not m:
        return None
    qty = parse_number(m.group(2))
    cost = parse_number(m.group(3)) if m.group(3) else None
    if not qty or (m.group(3) and not cost):
        return None
    return m.group(1).strip(), qty, cost


def to_usd(amount, cur):
    if cur == "$":
        return amount
    if cur == "₺":
        fx = yahoo_raw("USDTRY=X")
        return amount / fx[0] if fx else None
    if cur == "€":
        fx = yahoo_raw("EURUSD=X")
        return amount * fx[0] if fx else None
    return None


def from_usd(amount, region):
    """-> (value, currency) in the region's own money."""
    if region == "tr":
        fx = yahoo_raw("USDTRY=X")
        return (amount * fx[0], "₺") if fx else (None, None)
    if region == "eu":
        fx = yahoo_raw("EURUSD=X")
        return (amount / fx[0], "€") if fx else (None, None)
    return amount, "$"


def portfolio_totals(state, chat_id, region):
    """-> (rows, totals_by_currency, grand) ; rows = [(pos, quote|None)]"""
    rows, tot = [], {}
    for p in positions(state, chat_id):
        q = get_quote(p["symbol"], region)
        rows.append((p, q))
        if q:
            t = tot.setdefault(p["cur"], [0.0, 0.0])
            t[0] += p["qty"] * q["price"]
            t[1] += p["qty"] * p["cost"]
    grand = None
    if tot:
        usd = [to_usd(v[0], c) for c, v in tot.items()]
        if None not in usd:
            gv, gc = from_usd(sum(usd), region)
            if gv is not None and (len(tot) > 1 or gc not in tot):
                grand = (gv, gc)
    return rows, tot, grand


def portfolio_view(state, chat_id):
    lang, region = prefs(state, chat_id)
    if not is_premium(state, chat_id):
        return premium_needed(state, chat_id, "prem_why_pf")
    if not positions(state, chat_id):
        return T("pf_empty", lang), ikb([[(T("btn_pf_add", lang), "pf|add")]])
    rows, tot, grand = portfolio_totals(state, chat_id, region)
    now = now_local(tz_for(region)).strftime("%d.%m %H:%M")
    lines = [T("pf_title", lang, t=now), ""]
    for i, (p, q) in enumerate(rows, 1):
        name, cur = e(name_of(p["symbol"], lang)), p["cur"]
        if not q:
            lines.append(T("pf_nopx", lang, i=i, name=name, qty=fmt_qty(p["qty"]), cost=fmt_price(p["cost"], cur)))
            continue
        value, pl = p["qty"] * q["price"], p["qty"] * (q["price"] - p["cost"])
        lines.append(T("pf_row", lang, i=i, name=name, qty=fmt_qty(p["qty"]), cost=fmt_price(p["cost"], cur),
                       price=fmt_price(q["price"], cur), value=fmt_price(value, cur), pl=fmt_signed(pl, cur),
                       plp=fmt_pct((q["price"] / p["cost"] - 1) * 100, lang)))
    lines.append("")
    for cur, (v, c) in tot.items():
        lines.append(T("pf_total", lang, cur=cur, value=fmt_price(v, cur), pl=fmt_signed(v - c, cur),
                       plp=fmt_pct((v / c - 1) * 100 if c else 0, lang)))
    if grand:
        lines.append(T("pf_grand", lang, v=fmt_price(*grand)))
    lines.append(T("pf_hint", lang))
    btns = [(f"🗑 {i}", f"pd|{p['id']}") for i, (p, _) in enumerate(rows, 1)]
    kb = [btns[i:i + 5] for i in range(0, len(btns), 5)]
    kb.append([(T("btn_pf_add", lang), "pf|add"), (T("btn_refresh", lang), "pf|v")])
    return "\n".join(lines), ikb(kb)


def add_position(state, chat_id, sym, qty, cost=None):
    """-> (text, kb)"""
    lang, region = prefs(state, chat_id)
    if not is_premium(state, chat_id):
        return premium_needed(state, chat_id, "prem_why_pf")
    q = get_quote(sym, region)
    if not q:
        return T("not_found", lang, sym=e(sym), ex=EX_SHORT[(lang, region)]), None
    cost = cost or q["price"]
    mine = state["portfolios"].setdefault(str(chat_id), [])
    same = next((p for p in mine if p["symbol"] == q["key"]), None)
    if same:                                                       # buying more: weighted average cost
        total = same["qty"] + qty
        same["cost"] = (same["qty"] * same["cost"] + qty * cost) / total
        same["qty"] = total
    else:
        if len(mine) >= MAX_POSITIONS:
            return T("pf_max", lang, n=MAX_POSITIONS), None
        mine.append({"id": state["next_id"], "symbol": q["key"], "qty": qty, "cost": cost, "cur": q["cur"],
                     "ts": int(time.time())})
        state["next_id"] += 1
    added = T("pf_added", lang, name=e(name_of(q["key"], lang)), qty=fmt_qty(qty), cost=fmt_price(cost, q["cur"]))
    text, kb = portfolio_view(state, chat_id)
    return added + "\n\n" + text, kb


def portfolio_line(state, chat_id, lang, region):
    """One-line portfolio snapshot for the daily summary ('' when there is nothing to show)."""
    if not positions(state, chat_id) or not is_premium(state, chat_id):
        return ""
    _, tot, grand = portfolio_totals(state, chat_id, region)
    parts = [f"{fmt_price(v, cur)} ({fmt_pct((v / c - 1) * 100 if c else 0, lang)})" for cur, (v, c) in tot.items()]
    if not parts:
        return ""
    if grand:
        parts.append("≈ " + fmt_price(*grand))
    return "\n\n" + T("pf_sum", lang, x=" · ".join(parts))


# ---------------------------------------------------------------- premium (Telegram Stars)
def is_premium(state, chat_id):
    """Everything is open when PREMIUM_STARS is not set."""
    if not PREMIUM_STARS:
        return True
    cid = str(chat_id)
    if OWNER_CHAT_ID and cid == OWNER_CHAT_ID:
        return True
    u = state["users"].get(cid) or {}
    if u.get("blocked"):
        return False
    if u.get("no_trial") or u.get("premium_until", 0) > time.time():
        return True
    left = trial_left(state, chat_id)
    return left is not None and left > 0


def premium_days_left(state, chat_id):
    u = state["users"].get(str(chat_id)) or {}
    return (u.get("premium_until", 0) - time.time()) / 86400


def buy_kb(lang):
    return ikb([[(T("btn_buy", lang, s=PREMIUM_STARS), "pr|buy")]])


def premium_needed(state, chat_id, why_key):
    lang = prefs(state, chat_id)[0]
    why = T(why_key, lang, n=FREE_ALERTS)
    return (T("prem_need", lang, what=why, price=T("prem_price", lang, s=PREMIUM_STARS, d=PREMIUM_DAYS)),
            buy_kb(lang))


def premium_view(state, chat_id):
    lang = prefs(state, chat_id)[0]
    if not PREMIUM_STARS:
        return T("prem_off_mode", lang), None
    u = state["users"].get(str(chat_id)) or {}
    left = premium_days_left(state, chat_id)
    tz = tz_for(prefs(state, chat_id)[1])
    if left > 0:
        date = datetime.fromtimestamp(u["premium_until"], tz).strftime("%d.%m.%Y")
        status = T("prem_status_on", lang, date=date, d=max(1, int(math.ceil(left))))
    elif is_premium(state, chat_id):
        tl = trial_left(state, chat_id)
        status = T("prem_status_trial", lang, d=max(1, int(math.ceil(tl)))) if tl else T("prem_status_free", lang)
    else:
        status = T("prem_status_off", lang, n=FREE_ALERTS)
    text = (status + "\n\n" + T("prem_perks", lang, n=FREE_ALERTS) + "\n"
            + T("prem_price", lang, s=PREMIUM_STARS, d=PREMIUM_DAYS))
    return text, buy_kb(lang)


def send_invoice(state, chat_id):
    lang = prefs(state, chat_id)[0]
    return tg("sendInvoice", chat_id=chat_id, title=T("inv_title", lang, d=PREMIUM_DAYS),
              description=T("inv_desc", lang, d=PREMIUM_DAYS), payload=f"prem:{chat_id}:{PREMIUM_DAYS}",
              provider_token="", currency="XTR",
              prices=[{"label": T("inv_title", lang, d=PREMIUM_DAYS), "amount": PREMIUM_STARS}])


def answer_pre_checkout(state, pq):
    """Telegram cancels the payment if this isn't answered within 10 seconds."""
    payload = str(pq.get("invoice_payload", ""))
    ok = (bool(PREMIUM_STARS) and pq.get("currency") == "XTR" and payload.startswith("prem:")
          and int(pq.get("total_amount", 0)) == PREMIUM_STARS)
    extra = {} if ok else {"error_message": T("pay_err", tg_lang(pq.get("from") or {}))}
    tg("answerPreCheckoutQuery", pre_checkout_query_id=pq.get("id"), ok=ok, **extra)


def on_payment(state, chat, user, sp):
    """successful_payment: only now is the purchase real."""
    cid = str(chat["id"])
    try:
        days = int(str(sp.get("invoice_payload", "")).split(":")[2])
    except (IndexError, ValueError):
        days = PREMIUM_DAYS
    u = state["users"].setdefault(cid, {"name": who(user, chat), "type": chat.get("type", "private"),
                                        "since": int(time.time())})
    base = max(time.time(), u.get("premium_until", 0))
    u["premium_until"] = int(base + days * 86400)
    for k in ("prem_warn_for", "prem_end_for", "blocked"):
        u.pop(k, None)
    stars = int(sp.get("total_amount", 0))
    state["payments"].append({"cid": cid, "user_id": user.get("id"), "stars": stars, "days": days,
                              "charge_id": sp.get("telegram_payment_charge_id"), "ts": int(time.time())})
    st = state["stats"]
    st["stars_total"] = st.get("stars_total", 0) + stars
    lang, region = prefs(state, cid)
    date = datetime.fromtimestamp(u["premium_until"], tz_for(region)).strftime("%d.%m.%Y")
    send(chat["id"], T("prem_thanks", lang, date=date), main_kb(lang) if chat.get("type") == "private" else None)
    if OWNER_CHAT_ID and cid != OWNER_CHAT_ID:
        send(OWNER_CHAT_ID, T("prem_owner", owner_lang(state), name=e(who(user, chat)), cid=cid, s=stars, date=date))


def premium_notices(state):
    """Reminder shortly before Premium runs out, and one message when it does."""
    if not PREMIUM_STARS:
        return
    now = time.time()
    for cid, u in list(state["users"].items()):
        until = u.get("premium_until")
        if not until:
            continue
        lang = prefs(state, cid)[0]
        if until <= now and u.get("prem_end_for") != until:
            u["prem_end_for"] = until
            if not is_premium(state, cid):
                send(int(cid), T("prem_ended", lang, n=FREE_ALERTS), buy_kb(lang))
        elif 0 < until - now <= WARN_BEFORE_DAYS * 86400 and u.get("prem_warn_for") != until:
            u["prem_warn_for"] = until
            send(int(cid), T("prem_warn", lang, d=max(1, int(math.ceil((until - now) / 86400)))), buy_kb(lang))


def silent_ids(state, chat_id):
    """Alerts kept but paused on the free plan: all technical ones and price alerts past FREE_ALERTS."""
    if is_premium(state, chat_id):
        return set()
    out, n = set(), 0
    for a in user_alerts(state, chat_id):
        if a.get("kind") == "tech":
            out.add(a["id"])
            continue
        n += 1
        if n > FREE_ALERTS:
            out.add(a["id"])
    return out


# ---------------------------------------------------------------- actions
def parse_alarm_args(args):
    """-> (symbol_text, kind, value, repeat) or None. kind: above | below | auto | move"""
    s = (args or "").strip()
    repeat = False
    s2 = re.sub(r"\s*\b(tekrar\w*|repeat\w*|her\s*seferinde|every\s*time)\b\s*", " ", s, flags=re.I).strip()
    if s2 != s:
        repeat, s = True, s2
    s = re.sub(r"^(.+?)\s+([0-9.,]+)\s*%\s*$", r"\1 %\2", s)            # "ETH 5%" -> "ETH %5"
    # a space or an operator must separate name and number, so "SP500" / "BIST100" stay one symbol
    m = re.fullmatch(r"(.+?)(?:\s*(>=|<=|>|<|%|üstü|ustu|üstüne|ustune|altı|alti|altına|altina|above|below)\s*|\s+)"
                     r"([$€]?[0-9][0-9.,]*\s*[kK]?)\s*(?:tl|TL|₺|\$|€)?", s)
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
    lang, region = prefs(state, chat_id)
    if len(user_alerts(state, chat_id)) >= MAX_ALERTS_PER_CHAT:
        return T("max_alerts", lang, n=MAX_ALERTS_PER_CHAT), ikb([[(T("btn_my_alerts", lang), "m|list")]])
    if not is_premium(state, chat_id) and \
            sum(1 for a in user_alerts(state, chat_id) if a.get("kind") != "tech") >= FREE_ALERTS:
        return premium_needed(state, chat_id, "prem_why_alerts")
    q = get_quote(sym, region)
    if q is None:
        return T("not_found", lang, sym=e(sym), ex=EX_SHORT[(lang, region)]), None
    price, cur = q["price"], q["cur"]
    name = e(name_of(q["key"], lang))
    a = {"id": state["next_id"], "chat_id": chat_id, "symbol": q["key"], "name": q["name"], "currency": cur,
         "created": time.time(), "repeat": bool(repeat), "armed": True, "fired": 0}
    if kind == "move":
        if not 0.1 <= value <= 100:
            return T("pct_range", lang), None
        a.update(kind="move", pct=value, ref=price)
    else:
        if kind == "auto":
            if abs(value / price - 1) < 0.0005:
                return T("already_at", lang, name=name, price=fmt_price(price, cur)), None
            kind = "above" if value > price else "below"
        if (kind == "above" and price >= value) or (kind == "below" and price <= value):
            return T("would_fire", lang, name=name, price=fmt_price(price, cur)), None
        a.update(kind=kind, level=value)
    state["alerts"].append(a)
    state["next_id"] += 1
    note = ""
    if a["kind"] != "move" and (value > price * 3 or value < price / 3):
        note = T("far_warn", lang)
    return T("alert_set", lang, desc=describe(a, lang), price=fmt_price(price, cur), note=note), alert_kb(a, lang)


def set_pending(state, chat_id, action, symbol=None):
    state["pending"][str(chat_id)] = {"action": action, "symbol": symbol, "ts": time.time()}


def pop_pending(state, chat_id):
    p = state["pending"].pop(str(chat_id), None)
    return p if p and time.time() - p.get("ts", 0) < PENDING_TTL else None


def reply_price(state, chat_id, sym):
    lang, region = prefs(state, chat_id)
    q = get_quote(sym, region)
    if q is None:
        send(chat_id, T("not_found", lang, sym=e(sym), ex=EX_SHORT[(lang, region)]))
        return
    send(chat_id, *price_view(q, lang, region))


def reply_help(state, chat_id, private):
    lang, region = prefs(state, chat_id)
    if private:
        send(chat_id, help_text(True, lang, region), main_kb(lang))
    else:
        send(chat_id, help_text(False, lang, region), group_menu(lang))


def menu_action(state, chat_id, what, private=True):
    lang, region = prefs(state, chat_id)
    if what == "alarm":
        send(chat_id, T("pick_alarm", lang), asset_picker("aa", lang, region))
    elif what == "price":
        send(chat_id, T("pick_price", lang), asset_picker("pa", lang, region))
    elif what == "list":
        send(chat_id, *list_view(state, chat_id))
    elif what == "sum":
        send(chat_id, build_summary(lang, region), summary_kb(state, chat_id))
    elif what == "settings":
        send(chat_id, *settings_view(state, chat_id))
    elif what == "portfolio":
        send(chat_id, *portfolio_view(state, chat_id))
    elif what == "premium":
        send(chat_id, *premium_view(state, chat_id))
    else:
        reply_help(state, chat_id, private)


def subscribe_summary(state, chat_id, on, hhmm=None):
    lang, region = prefs(state, chat_id)
    cid = str(chat_id)
    if not on:
        state["summaries"].pop(cid, None)
        return T("sum_off", lang)
    hhmm = hhmm or SUMMARY_TIME
    now = now_local(tz_for(region))
    state["summaries"][cid] = {"time": hhmm,
                               "last": now.strftime("%Y-%m-%d") if now.strftime("%H:%M") >= hhmm else ""}
    return T("sum_on", lang, t=hhmm)


BUTTON_TEXTS = {}
for _lg in LANGS:
    for _k, _v in (("b_alarm", "alarm"), ("b_price", "price"), ("b_list", "list"), ("b_sum", "sum"),
                   ("b_settings", "settings"), ("b_help", "help"), ("b_port", "portfolio"), ("b_prem", "premium")):
        BUTTON_TEXTS[T(_k, _lg)] = _v

COMMANDS = {
    "alarm": "alarm", "alert": "alarm", "fiyat": "price", "price": "price", "liste": "list", "list": "list",
    "alarmlar": "list", "alerts": "list", "sil": "delete", "delete": "delete", "ozet": "sum", "özet": "sum",
    "summary": "sum", "yardim": "help", "yardım": "help", "help": "help", "start": "start", "menu": "help",
    "menü": "help", "ayarlar": "settings", "settings": "settings", "dil": "language", "language": "language",
    "bolge": "region", "bölge": "region", "region": "region", "id": "id",
    "uzat": "extend", "extend": "extend", "bitir": "endtrial", "end": "endtrial",
    "kullanicilar": "users", "kullanıcılar": "users", "users": "users", "admin": "admin",
    "duyuru": "broadcast", "broadcast": "broadcast", "izinver": "allow", "allow": "allow",
    "izinkaldir": "disallow", "disallow": "disallow", "ozelmod": "pmode", "private": "pmode",
    "portfoy": "portfolio", "portföy": "portfolio", "portfolio": "portfolio", "ekle": "pfadd", "add": "pfadd",
    "grafik": "chart", "chart": "chart", "teknik": "tech", "tech": "tech",
    "premium": "premium", "paysupport": "paysupport", "destek": "paysupport", "terms": "terms",
    "kosullar": "terms", "koşullar": "terms", "premiumver": "grant", "grant": "grant",
    "iade": "refund", "refund": "refund",
}
SHORTCUT = re.compile(r"^(.+?)\s+(grafik|chart|grafiği|teknik|tech|rsi)$", re.I)


def handle_text(state, ctx, text):
    chat_id, private = ctx["chat_id"], ctx["type"] == "private"
    lang, region = prefs(state, chat_id)
    if not text.startswith("/"):
        if not private:
            return
        if text in BUTTON_TEXTS:
            pop_pending(state, chat_id)
            return menu_action(state, chat_id, BUTTON_TEXTS[text])
        p = pop_pending(state, chat_id)
        if p and p["action"] == "alarm_level":
            if "%" in text:
                v, kind = parse_number(text.replace("%", "")), "move"
            else:
                v, kind = parse_number(text), "auto"
                if v is None:
                    parsed = parse_alarm_args(f"{p['symbol']} {text}")
                    if parsed:
                        _, kind, v, _ = parsed
            if v is None:
                set_pending(state, chat_id, "alarm_level", p["symbol"])
                return send(chat_id, T("only_price", lang))
            return send(chat_id, *add_alert(state, chat_id, p["symbol"], kind, v,
                                            repeat=bool(re.search(r"tekrar|repeat", text, re.I))))
        if p and p["action"] == "alarm_sym":
            parsed = parse_alarm_args(text)
            if parsed:
                s, kind, v, rep = parsed
                return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
            q = get_quote(text, region)
            if not q:
                return send(chat_id, T("not_found", lang, sym=e(text), ex=EX_SHORT[(lang, region)]))
            return send(chat_id, *level_picker(q, lang))
        if p and p["action"] == "price_sym":
            return reply_price(state, chat_id, text)
        if p and p["action"] == "pf_add":
            parsed = parse_position(text)
            if not parsed:
                set_pending(state, chat_id, "pf_add")
                return send(chat_id, T("pf_bad", lang))
            return send(chat_id, *add_position(state, chat_id, *parsed))
        if p and p["action"] == "pf_qty":
            parsed = parse_position(f"{p['symbol']} {text}")
            if not parsed:
                set_pending(state, chat_id, "pf_qty", p["symbol"])
                return send(chat_id, T("pf_bad", lang))
            return send(chat_id, *add_position(state, chat_id, *parsed))
        sc = SHORTCUT.match(text)
        if sc and normalize_symbol(sc.group(1), region):
            q = get_quote(sc.group(1), region)
            if not q:
                return send(chat_id, T("not_found", lang, sym=e(sc.group(1)), ex=EX_SHORT[(lang, region)]))
            if sc.group(2).lower() in ("grafik", "chart", "grafiği"):
                return send_chart(state, chat_id, q["key"]) or send(chat_id, T("chart_fail", lang))
            return send(chat_id, *tech_picker(q["key"], lang))
        parsed = parse_alarm_args(text) if re.search(r"\d", text) else None
        if parsed:
            s, kind, v, rep = parsed
            return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
        if " " not in text and normalize_symbol(text, region) and len(text) <= 20:
            return reply_price(state, chat_id, text)
        return send(chat_id, T("what", lang, ex=EX_HELP[(lang, region)]), main_kb(lang))

    m = re.match(r"^/([A-Za-zçğıöşüÇĞİÖŞÜ]+)(?:@\w+)?\s*(.*)$", text, re.S)
    cmd = COMMANDS.get(m.group(1).lower()) if m else None
    args = (m.group(2) if m else "").strip()
    is_owner = bool(OWNER_CHAT_ID) and str(ctx["user_id"]) == OWNER_CHAT_ID
    if cmd == "start":
        return reply_help(state, chat_id, private)
    if cmd == "alarm":
        if not args:
            return menu_action(state, chat_id, "alarm")
        parsed = parse_alarm_args(args)
        if not parsed:
            return send(chat_id, T("bad_alarm", lang, gold="altın"))
        s, kind, v, rep = parsed
        return send(chat_id, *add_alert(state, chat_id, s, kind, v, rep))
    if cmd == "price":
        return reply_price(state, chat_id, args) if args else menu_action(state, chat_id, "price")
    if cmd == "list":
        return menu_action(state, chat_id, "list")
    if cmd == "delete":
        mine = user_alerts(state, chat_id)
        a = args.lower()
        if a in ("hepsi", "tümü", "tumu", "all"):
            state["alerts"] = [x for x in state["alerts"] if x["chat_id"] != chat_id]
            return send(chat_id, T("n_deleted", lang, n=len(mine)))
        if not a.isdigit() or not 1 <= int(a) <= len(mine):
            return send(chat_id, *list_view(state, chat_id))
        target = mine[int(a) - 1]
        state["alerts"] = [x for x in state["alerts"] if x["id"] != target["id"]]
        return send(chat_id, T("deleted_desc", lang, desc=describe(target, lang)))
    if cmd == "sum":
        parts = args.lower().split()
        if parts and parts[0] in ("ac", "aç", "on"):
            if not private and not is_group_admin(chat_id, ctx["user_id"]):
                return send(chat_id, T("sum_admin", lang))
            hhmm = parts[1] if len(parts) > 1 and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", parts[1]) else None
            return send(chat_id, subscribe_summary(state, chat_id, True, hhmm))
        if parts and parts[0] in ("kapat", "off"):
            if not private and not is_group_admin(chat_id, ctx["user_id"]):
                return send(chat_id, T("sum_admin", lang))
            return send(chat_id, subscribe_summary(state, chat_id, False))
        return menu_action(state, chat_id, "sum")
    if cmd in ("settings", "language", "region"):
        if not private and not is_group_admin(chat_id, ctx["user_id"]):
            return send(chat_id, T("group_admin_only", lang))
        if cmd == "language":
            return send(chat_id, T("choose_lang", lang), lang_picker(lang))
        if cmd == "region":
            return send(chat_id, T("choose_region", lang), region_picker(lang))
        return send(chat_id, *settings_view(state, chat_id))
    if cmd == "id":
        return send(chat_id, T("id", lang, cid=chat_id) + (T("id_user", lang, uid=ctx["user_id"]) if not private else ""))
    if cmd == "portfolio":
        return menu_action(state, chat_id, "portfolio")
    if cmd == "pfadd":
        parsed = parse_position(args)
        if not parsed:
            return send(chat_id, *portfolio_view(state, chat_id)) if not args else send(chat_id, T("pf_bad", lang))
        return send(chat_id, *add_position(state, chat_id, *parsed))
    if cmd in ("chart", "tech"):
        if not args:
            return send(chat_id, T("type_symbol", lang, ex=EX_TYPE.get((lang, region)) or EX_TYPE[(lang, "*")]))
        q = get_quote(args, region)
        if not q:
            return send(chat_id, T("not_found", lang, sym=e(args), ex=EX_SHORT[(lang, region)]))
        if cmd == "chart":
            return send_chart(state, chat_id, q["key"]) or send(chat_id, T("chart_fail", lang))
        return send(chat_id, *tech_picker(q["key"], lang))
    if cmd == "premium":
        return send(chat_id, *premium_view(state, chat_id))
    if cmd == "terms":
        return send(chat_id, T("terms", lang, d=PREMIUM_DAYS))
    if cmd == "paysupport":
        if not args:
            return send(chat_id, T("paysupport", lang, c=_contact(lang)))
        if OWNER_CHAT_ID:
            u = state["users"].get(str(chat_id)) or {}
            send(OWNER_CHAT_ID, T("ps_owner", owner_lang(state), name=e(u.get("name", chat_id)), cid=chat_id,
                                  msg=e(args[:1500])))
        return send(chat_id, T("ps_sent", lang))
    if cmd in ("admin", "broadcast", "allow", "disallow", "pmode", "extend", "endtrial", "users", "grant", "refund"):
        if not is_owner:
            return reply_help(state, chat_id, private)
        return owner_command(state, chat_id, cmd, args)
    return reply_help(state, chat_id, private)


def owner_command(state, chat_id, cmd, args):
    ol = owner_lang(state)
    if cmd == "admin":
        return send(chat_id, *admin_view(state))
    if cmd == "broadcast":
        if not args:
            return send(chat_id, T("bc_usage", ol))
        ok = sum(send(int(cid), f"📢 {e(args)}") for cid in list(state["users"]))
        return send(chat_id, T("bc_done", ol, ok=ok, n=len(state["users"])))
    if cmd in ("allow", "disallow"):
        if not re.fullmatch(r"-?\d+", args):
            return send(chat_id, T("allow_usage", ol))
        allowed_ = set(state["allowed"])
        (allowed_.add if cmd == "allow" else allowed_.discard)(args)
        state["allowed"] = sorted(allowed_)
        if cmd == "allow":
            state["requests"].pop(args, None)
            send(int(args), T("granted", prefs(state, args)[0]))
            return send(chat_id, T("approved", ol, cid=args))
        return send(chat_id, T("removed", ol, cid=args))
    if cmd == "extend":
        parts = args.split()
        if not parts or not re.fullmatch(r"-?\d+", parts[0]):
            return send(chat_id, T("ext_usage", ol))
        cid = parts[0]
        u = state["users"].setdefault(cid, {"name": cid, "type": "private", "since": int(time.time())})
        for k in ("trial_warn_sent", "trial_end_sent", "blocked"):
            u.pop(k, None)
        ul = prefs(state, cid)[0]
        if len(parts) > 1 and parts[1].lower() in ("sinirsiz", "sınırsız", "limitsiz", "unlimited"):
            u["no_trial"] = True
            send(int(cid), T("unlimited", ul))
            return send(chat_id, T("ext_unlimited", ol, cid=cid))
        u.pop("no_trial", None)
        u["since"] = int(time.time())
        send(int(cid), T("extended", ul, d=TRIAL_DAYS))
        return send(chat_id, T("ext_done", ol, cid=cid, d=TRIAL_DAYS))
    if cmd == "endtrial":
        if not re.fullmatch(r"-?\d+", args.strip()):
            return send(chat_id, T("end_usage", ol))
        cid = args.strip()
        u = state["users"].setdefault(cid, {"name": cid, "type": "private", "since": int(time.time())})
        u["blocked"] = True
        u.pop("no_trial", None)
        ul = prefs(state, cid)[0]
        send(int(cid), T("closed", ul, contact=_contact(ul)))
        return send(chat_id, T("end_done", ol, cid=cid))
    if cmd == "users":
        rows = []
        tz = tz_for(DEFAULT_REGION)
        for cid, u in sorted(state["users"].items(), key=lambda kv: kv[1].get("since", 0), reverse=True)[:30]:
            start = datetime.fromtimestamp(u.get("since", 0), tz).strftime("%d.%m %H:%M")
            left = trial_left(state, int(cid))
            if u.get("blocked"):
                status = T("st_closed", ol)
            elif u.get("premium_until", 0) > time.time():
                status = T("st_premium", ol, d=max(1, int(math.ceil(premium_days_left(state, int(cid))))))
            elif u.get("no_trial") or left is None:
                status = T("st_unlimited", ol)
            elif left <= 0:
                status = T("st_expired", ol)
            else:
                status = T("st_left", ol, d=left)
            n = sum(1 for a in state["alerts"] if str(a["chat_id"]) == cid)
            lr = f"{u.get('lang', '?')}/{u.get('region', '?')}"
            rows.append(T("users_row", ol, name=e(u.get("name", cid)), cid=cid, start=start, status=status, n=n, lr=lr))
        if not rows:
            return send(chat_id, T("no_users", ol))
        return send(chat_id, T("users_title", ol) + "\n\n" + "\n".join(rows) + T("users_foot", ol))
    if cmd == "pmode":
        state["private_mode"] = args.lower() in ("ac", "aç", "on")
        return send(chat_id, *admin_view(state))
    if cmd == "grant":
        parts = args.split()
        if not parts or not re.fullmatch(r"-?\d+", parts[0]) or (len(parts) > 1 and not parts[1].isdigit()):
            return send(chat_id, T("grant_usage", ol))
        cid, days = parts[0], int(parts[1]) if len(parts) > 1 else PREMIUM_DAYS
        u = state["users"].setdefault(cid, {"name": cid, "type": "private", "since": int(time.time())})
        u["premium_until"] = int(max(time.time(), u.get("premium_until", 0)) + days * 86400)
        u.pop("blocked", None)
        send(int(cid), T("prem_gift", prefs(state, cid)[0], d=days))
        return send(chat_id, T("granted_prem", ol, cid=cid, d=days))
    if cmd == "refund":
        cid = args.strip()
        pay = next((p for p in reversed(state["payments"]) if p["cid"] == cid and not p.get("refunded")), None)
        if not re.fullmatch(r"-?\d+", cid):
            return send(chat_id, T("refund_usage", ol))
        if not pay or not tg("refundStarPayment", user_id=pay["user_id"],
                             telegram_payment_charge_id=pay["charge_id"]):
            return send(chat_id, T("refund_fail", ol))
        pay["refunded"] = True
        u = state["users"].get(cid) or {}
        u["premium_until"] = int(time.time())
        u["prem_end_for"] = u["premium_until"]
        send(int(cid), T("refunded", prefs(state, cid)[0]))
        return send(chat_id, T("refund_done", ol, cid=cid, s=pay["stars"]))


def handle_callback(state, cb):
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id, mid = chat.get("id"), msg.get("message_id")
    user_id = (cb.get("from") or {}).get("id")
    private = chat.get("type", "private") == "private"
    is_owner = bool(OWNER_CHAT_ID) and str(user_id) == OWNER_CHAT_ID
    lang, region = prefs(state, chat_id)
    parts = data.split("|")
    op = parts[0]
    toast = None

    if op in ("lg", "rg", "st"):
        if not private and not is_group_admin(chat_id, user_id):
            toast = T("toast_admin", lang)
        else:
            u = state["users"].setdefault(str(chat_id), {"name": str(chat_id), "since": int(time.time()),
                                                         "type": chat.get("type", "private")})
            if op == "st":
                if parts[1] == "lang":
                    edit(chat_id, mid, T("choose_lang", lang), lang_picker(lang))
                else:
                    edit(chat_id, mid, T("choose_region", lang), region_picker(lang))
            elif op == "lg" and parts[1] in LANGS:
                u["lang"] = parts[1]
                if not u.get("region"):
                    edit(chat_id, mid, T("choose_region", parts[1]), region_picker(parts[1]))
                else:
                    finish_setup(state, chat_id, mid, private)
            elif op == "rg" and parts[1] in REGIONS:
                u["region"] = parts[1]
                u.setdefault("lang", lang)
                finish_setup(state, chat_id, mid, private)
    elif op == "m":
        menu_action(state, chat_id, parts[1], private)
    elif op in ("aa", "pa"):
        if parts[1] == "*" and not private:
            send(chat_id, T("group_type_hint", lang))
        elif parts[1] == "*":
            set_pending(state, chat_id, "alarm_sym" if op == "aa" else "price_sym")
            send(chat_id, T("type_symbol", lang, ex=EX_TYPE.get((lang, region)) or EX_TYPE[(lang, "*")]))
        else:
            q = get_quote(parts[1], region)
            if not q:
                toast = T("no_price", lang)
            elif op == "aa":
                send(chat_id, *level_picker(q, lang))
            else:
                send(chat_id, *price_view(q, lang, region))
    elif op == "pq":
        q = get_quote(parts[1], region)
        if q:
            edit(chat_id, mid, *price_view(q, lang, region))
            toast = T("updated", lang)
        else:
            toast = T("no_price", lang)
    elif op == "al":
        q = None if len(parts) > 4 else get_quote(parts[1], region)
        if q or len(parts) > 4:
            n = float(parts[3])
            level = float(parts[4]) if len(parts) > 4 else \
                nice_round(q["price"] * (1 + n / 100 if parts[2] == "u" else 1 - n / 100))
            send(chat_id, *add_alert(state, chat_id, parts[1], "above" if parts[2] == "u" else "below", level))
        else:
            toast = T("no_price", lang)
    elif op == "am":
        send(chat_id, *add_alert(state, chat_id, parts[1], "move", float(parts[2])))
    elif op == "aw" and not private:
        send(chat_id, T("group_level_hint", lang, sym=e(name_of(parts[1], lang))))
    elif op == "aw":
        q = get_quote(parts[1], region)
        set_pending(state, chat_id, "alarm_level", parts[1])
        now_s = T("now_paren", lang, p=fmt_price(q["price"], q["cur"])) if q else ""
        send(chat_id, T("write_level", lang, name=e(name_of(parts[1], lang)), now=now_s))
    elif op == "re":
        kind = {"a": "above", "b": "below", "m": "move"}[parts[2]]
        send(chat_id, *add_alert(state, chat_id, parts[1], kind, float(parts[3])))
    elif op == "rp":
        a = next((x for x in state["alerts"] if x["id"] == int(parts[1]) and x["chat_id"] == chat_id), None)
        if a:
            a["repeat"], a["armed"] = not a.get("repeat"), True
            edit(chat_id, mid, T("alert_label", lang, desc=describe(a, lang)) + "\n"
                 + (T("repeat_on", lang) if a["repeat"] else T("repeat_off", lang)), alert_kb(a, lang))
        else:
            toast = T("alert_gone", lang)
    elif op == "dl":
        before = len(state["alerts"])
        state["alerts"] = [x for x in state["alerts"] if not (x["id"] == int(parts[1]) and x["chat_id"] == chat_id)]
        toast = T("deleted", lang) if len(state["alerts"]) < before else T("alert_gone", lang)
        if len(parts) > 2:
            edit(chat_id, mid, *list_view(state, chat_id))
        else:
            edit(chat_id, mid, T("cancelled", lang))
    elif op == "dla":
        n = len(user_alerts(state, chat_id))
        state["alerts"] = [x for x in state["alerts"] if x["chat_id"] != chat_id]
        edit(chat_id, mid, T("n_deleted", lang, n=n), ikb([[(T("btn_new", lang), "m|alarm")]]))
    elif op == "ss":
        if not private and not is_group_admin(chat_id, user_id):
            toast = T("toast_admin", lang)
        else:
            send(chat_id, subscribe_summary(state, chat_id, parts[1] == "on"))
    elif op in ("ok", "no") and is_owner:
        cid, ol = parts[1], owner_lang(state)
        ul = (state["requests"].get(cid + ":lang") or DEFAULT_LANG)
        if op == "ok":
            state["allowed"] = sorted(set(state["allowed"]) | {cid})
            state["requests"].pop(cid, None)
            send(int(cid), T("granted", ul))
            edit(chat_id, mid, T("approved", ol, cid=cid))
        else:
            state["requests"][cid] = "denied"
            send(int(cid), T("refused", ul))
            edit(chat_id, mid, T("denied", ol, cid=cid))
    elif op == "ad" and is_owner:
        if parts[1] == "pm":
            state["private_mode"] = not state["private_mode"]
        edit(chat_id, mid, *admin_view(state))
    elif op == "ch" and len(parts) > 2 and parts[2] in SPANS:
        if not send_chart(state, chat_id, parts[1], parts[2], mid if msg.get("photo") else None):
            toast = T("chart_fail", lang)
    elif op == "tm":
        send(chat_id, *tech_picker(parts[1], lang))
    elif op == "ta" and len(parts) > 2:
        send(chat_id, *add_tech(state, chat_id, parts[1], parts[2]))
    elif op == "pf":
        if parts[1] == "add" and not private:
            send(chat_id, T("pf_bad", lang))
        elif parts[1] == "add":
            if is_premium(state, chat_id):
                set_pending(state, chat_id, "pf_add")
                send(chat_id, T("pf_ask", lang))
            else:
                send(chat_id, *premium_needed(state, chat_id, "prem_why_pf"))
        else:
            edit(chat_id, mid, *portfolio_view(state, chat_id))
            toast = T("updated", lang)
    elif op == "pp":
        q = get_quote(parts[1], region)
        if not is_premium(state, chat_id):
            send(chat_id, *premium_needed(state, chat_id, "prem_why_pf"))
        elif not private:
            send(chat_id, T("pf_bad", lang))
        elif q:
            set_pending(state, chat_id, "pf_qty", q["key"])
            send(chat_id, T("pf_ask_qty", lang, name=e(name_of(q["key"], lang)), p=f"{nice_round(q['price']):g}"))
        else:
            toast = T("no_price", lang)
    elif op == "pd":
        mine = state["portfolios"].get(str(chat_id)) or []
        keep = [p for p in mine if p["id"] != int(parts[1])]
        toast = T("deleted", lang) if len(keep) < len(mine) else T("pf_gone", lang)
        state["portfolios"][str(chat_id)] = keep
        edit(chat_id, mid, *portfolio_view(state, chat_id))
    elif op == "pr":
        if PREMIUM_STARS and not send_invoice(state, chat_id):
            toast = T("error", lang)
    tg("answerCallbackQuery", callback_query_id=cb.get("id"), **({"text": toast} if toast else {}))


def finish_setup(state, chat_id, mid, private):
    lang, region = prefs(state, chat_id)
    edit(chat_id, mid, T("saved", lang, lang=LANG_NAME[lang], region=REGION_NAME[lang][region]))
    reply_help(state, chat_id, private)


# ---------------------------------------------------------------- trial
def _contact(lang=None):
    return T("contact", lang or DEFAULT_LANG, c=e(TRIAL_CONTACT)) if TRIAL_CONTACT else ""


def bot_expired():
    """Whole-bot deadline (TRIAL_UNTIL), used for a customer's own installation."""
    if not TRIAL_UNTIL:
        return False
    try:
        return now_local().strftime("%Y-%m-%d") > TRIAL_UNTIL
    except Exception:
        return False


def trial_left(state, chat_id):
    """Days left in this chat's own trial, or None when no per-user trial applies."""
    if not TRIAL_DAYS:
        return None
    u = state["users"].get(str(chat_id))
    if u and u.get("no_trial"):
        return None
    if not u or not u.get("since"):
        return TRIAL_DAYS
    return TRIAL_DAYS - (time.time() - u["since"]) / 86400


def trial_over(state, chat_id):
    u = state["users"].get(str(chat_id)) or {}
    if u.get("blocked"):
        return True
    if PREMIUM_STARS:
        return bot_expired()
    left = trial_left(state, chat_id)
    return bot_expired() or (left is not None and left <= 0)


def trial_notices(state):
    """Warn shortly before a trial ends, and say goodbye once when it does."""
    if not TRIAL_DAYS:
        return
    for cid, u in list(state["users"].items()):
        if OWNER_CHAT_ID and cid == OWNER_CHAT_ID:
            continue
        left = trial_left(state, int(cid))
        if left is None:
            continue
        lang = prefs(state, cid)[0]
        paid = u.get("premium_until", 0) > time.time()
        if left <= 0 and not u.get("trial_end_sent"):
            u["trial_end_sent"] = True
            if PREMIUM_STARS and not paid:
                send(int(cid), T("trial_end_free", lang, n=FREE_ALERTS), buy_kb(lang))
            elif not PREMIUM_STARS:
                send(int(cid), T("trial_end", lang, contact=_contact(lang)))
        elif 0 < left <= WARN_BEFORE_DAYS and not u.get("trial_warn_sent"):
            u["trial_warn_sent"] = True
            if PREMIUM_STARS and not paid:
                send(int(cid), T("trial_warn_prem", lang, d=max(1, int(round(left)))), buy_kb(lang))
            elif not PREMIUM_STARS:
                send(int(cid), T("trial_warn", lang, d=max(1, int(round(left))), contact=_contact(lang)))


# ---------------------------------------------------------------- access + updates
_hits = {}


def rate_limited(chat_id):
    """True when a chat sends more than RATE_LIMIT messages in a minute."""
    now, q = time.time(), _hits.setdefault(chat_id, [])
    q[:] = [t for t in q if now - t < 60]
    q.append(now)
    if len(q) == RATE_LIMIT + 1:
        log.warning("Rate limit hit by %s", chat_id)
    return len(q) > RATE_LIMIT


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
        name += f" · {chat.get('title', '')}"
    return name


def tg_lang(user):
    code = (user.get("language_code") or "").lower()
    return "tr" if code.startswith("tr") else ("en" if code else DEFAULT_LANG)


def register(state, chat, user):
    cid = str(chat["id"])
    if cid in state["users"]:
        return False
    state["users"][cid] = {"name": who(user, chat), "type": chat.get("type", "private"), "since": int(time.time()),
                           "tg_lang": tg_lang(user)}
    if NOTIFY_NEW_USERS and OWNER_CHAT_ID and cid != OWNER_CHAT_ID:
        send(OWNER_CHAT_ID, T("new_user", owner_lang(state), name=e(state["users"][cid]["name"]), cid=cid))
    return True


def deny(state, chat, user):
    cid = str(chat["id"])
    if state["requests"].get(cid) == "denied":
        return
    first = cid not in state["requests"]
    state["requests"][cid] = "pending"
    state["requests"][cid + ":lang"] = tg_lang(user)
    if first:
        send(chat["id"], T("private_bot", tg_lang(user)))
        if OWNER_CHAT_ID:
            ol = owner_lang(state)
            send(OWNER_CHAT_ID, T("access_req", ol, name=e(who(user, chat)), cid=cid),
                 ikb([[(T("btn_approve", ol), f"ok|{cid}"), (T("btn_deny", ol), f"no|{cid}")]]))


def needs_onboarding(state, chat, user):
    if not ONBOARDING or chat.get("type", "private") != "private":
        return False
    return not (state["users"].get(str(chat["id"])) or {}).get("lang")


def process_updates(state, timeout=0):
    updates = tg("getUpdates", offset=state["offset"] + 1, timeout=timeout,
                 allowed_updates=["message", "callback_query", "pre_checkout_query"]) or []
    for u in updates:
        state["offset"] = max(state["offset"], int(u.get("update_id", 0)))
        try:
            if "pre_checkout_query" in u:
                answer_pre_checkout(state, u["pre_checkout_query"])
                continue
            if "callback_query" in u:
                cb = u["callback_query"]
                chat = (cb.get("message") or {}).get("chat") or {}
                user = cb.get("from") or {}
                if chat.get("id") is None:
                    continue
                lang = prefs(state, chat["id"])[0]
                if not allowed(state, chat["id"], user.get("id")):
                    tg("answerCallbackQuery", callback_query_id=cb.get("id"), text=T("no_access", lang))
                    continue
                if rate_limited(chat["id"]):
                    tg("answerCallbackQuery", callback_query_id=cb.get("id"), text=T("slow", lang))
                    continue
                if trial_over(state, chat["id"]) and str(chat["id"]) != OWNER_CHAT_ID:
                    tg("answerCallbackQuery", callback_query_id=cb.get("id"), text=T("trial_toast", lang))
                    continue
                handle_callback(state, cb)
                continue
            msg = u.get("message") or {}
            chat, user = msg.get("chat") or {}, msg.get("from") or {}
            if msg.get("successful_payment") and chat.get("id") is not None:
                on_payment(state, chat, user, msg["successful_payment"])
                continue
            text = (msg.get("text") or "").strip()
            if chat.get("id") is None or not text:
                continue
            ctx = {"chat_id": chat["id"], "user_id": user.get("id"), "type": chat.get("type", "private")}
            if ctx["type"] != "private" and not text.startswith("/"):
                continue                                   # in groups, only react to commands
            if not allowed(state, chat["id"], user.get("id")):
                deny(state, chat, user)
                continue
            if rate_limited(chat["id"]):
                continue
            if trial_over(state, chat["id"]) and str(chat["id"]) != OWNER_CHAT_ID:
                ul = prefs(state, chat["id"])[0]
                send(chat["id"], T("trial_over", ul, contact=_contact(ul)))
                continue
            register(state, chat, user)
            if needs_onboarding(state, chat, user):
                first = (state["users"].get(str(chat["id"])) or {}).get("tg_lang") or DEFAULT_LANG
                send(chat["id"], T("choose_lang", first), lang_picker(first))
                continue
            handle_text(state, ctx, text)
        except Exception as ex:
            log.exception("Update failed: %s", ex)
            try:
                cid = ((u.get("message") or {}).get("chat") or {}).get("id") or \
                      (((u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")
                if cid:
                    send(cid, T("error", prefs(state, cid)[0]))
            except Exception:
                pass
    return len(updates)


# ---------------------------------------------------------------- checking
def check_alerts(state):
    _cache.clear()
    fired, keep = 0, []
    today = now_local().strftime("%Y-%m-%d")
    st = state["stats"]
    if st.get("day") != today:
        st["day"], st["fired_today"] = today, 0
    paused = {}
    for a in state["alerts"]:
        if trial_over(state, a["chat_id"]) and str(a["chat_id"]) != OWNER_CHAT_ID:
            keep.append(a)                      # kept, but silent until the trial is extended
            continue
        if a["chat_id"] not in paused:
            paused[a["chat_id"]] = silent_ids(state, a["chat_id"])
        if a["id"] in paused[a["chat_id"]]:
            keep.append(a)                      # free plan: kept, but silent until Premium
            continue
        if a.get("kind") == "tech":
            keep.append(a)
            if time.time() - a.get("checked", 0) < TECH_CHECK_SECONDS:
                continue
            a["checked"] = time.time()
            hit = tech_check(a)
            if not hit:
                continue
            lang, region = prefs(state, a["chat_id"])
            q = get_quote(a["symbol"])
            cur = a.get("currency", "$")
            price = fmt_price(q["price"], cur) if q else "—"
            text = (T(hit[0], lang, name=e(name_of(a["symbol"], lang)), price=price, **hit[1]) + "\n"
                    + T("fired_now", lang, price=price, time=now_local(tz_for(region)).strftime("%H:%M")) + "\n"
                    + T("tech_footer", lang))
            kb = ikb([[(T("btn_chart", lang), f"ch|{a['symbol']}|1y"), (T("btn_del_alert", lang), f"dl|{a['id']}")]])
            if send(a["chat_id"], text, kb):
                fired += 1
                a["fired"] = a.get("fired", 0) + 1
                st["fired_today"] = st.get("fired_today", 0) + 1
                st["fired_total"] = st.get("fired_total", 0) + 1
            continue
        q = get_quote(a["symbol"])
        if q is None:
            keep.append(a)
            continue
        lang, region = prefs(state, a["chat_id"])
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
        name = e(name_of(a["symbol"], lang))
        if a["kind"] == "above" and price >= a["level"]:
            head = T("fired_above", lang, name=name, level=fmt_price(a["level"], cur))
        elif a["kind"] == "below" and price <= a["level"]:
            head = T("fired_below", lang, name=name, level=fmt_price(a["level"], cur))
        elif a["kind"] == "move":
            chg = (price / a["ref"] - 1) * 100
            if abs(chg) >= a["pct"]:
                head = T("fired_up" if chg > 0 else "fired_down", lang, name=name, chg=fmt_pct(chg, lang),
                         ref=fmt_price(a["ref"], cur), price=fmt_price(price, cur))
        if not head:
            keep.append(a)
            continue
        now = now_local(tz_for(region))
        text = head + "\n" + T("fired_now", lang, price=fmt_price(price, cur), time=now.strftime("%H:%M")) + "\n"
        if a.get("repeat"):
            text += T("fired_repeat", lang)
            kb = ikb([[(T("btn_del_alert", lang), f"dl|{a['id']}"), (T("btn_price", lang), f"pq|{a['symbol']}")]])
        else:
            text += T("fired_once", lang)
            k = {"above": "a", "below": "b", "move": "m"}[a["kind"]]
            v = a["pct"] if a["kind"] == "move" else a["level"]
            kb = ikb([[(T("btn_again", lang), f"re|{a['symbol']}|{k}|{v:g}"),
                       (T("btn_price", lang), f"pq|{a['symbol']}")]])
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
    built, sent = {}, 0
    for cid, sub in list(state["summaries"].items()):
        if trial_over(state, int(cid)) and cid != OWNER_CHAT_ID:
            continue
        lang, region = prefs(state, cid)
        now = now_local(tz_for(region))
        today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        if sub.get("last") == today or hhmm < sub.get("time", "99"):
            continue
        if (lang, region) not in built:
            built[(lang, region)] = build_summary(lang, region)
        send(int(cid), built[(lang, region)] + portfolio_line(state, int(cid), lang, region), summary_kb(state, int(cid)))
        sub["last"] = today
        sent += 1
    return sent


# ---------------------------------------------------------------- main
def run_once():
    state = read_state()
    try:
        set_commands(state)
        process_updates(state)
        fired = check_alerts(state)
        maybe_send_summaries(state)
        trial_notices(state)
        premium_notices(state)
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
                    trial_notices(state)
                    premium_notices(state)
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
