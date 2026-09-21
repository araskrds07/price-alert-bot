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

VERSION = "3.0"
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
                    "• sonuna <code>tekrar</code> yazarsan alarm her geçişte çalışır",
              "en": "<b>Easiest:</b> use the buttons below or just type:\n"
                    "• <code>BTC</code> → live price\n"
                    "• <code>BTC 90000</code> → ping me at $90,000\n"
                    "• <code>{ex}</code>\n"
                    "• <code>ETH 5%</code> → ping me on a ±5% move\n"
                    "• add <code>repeat</code> to get pinged on every cross"},
    "howto_group": {"tr": "<b>Grupta:</b> aşağıdaki butonlar ya da komutlar\n"
                          "• <code>/fiyat BTC</code> · <code>/alarm BTC 90000</code>",
                    "en": "<b>In groups:</b> use the buttons below or commands\n"
                          "• <code>/price BTC</code> · <code>/alert BTC 90000</code>"},
    "cmds": {"tr": "<b>Komutlar:</b> /alarm · /fiyat · /liste · /ozet · /ayarlar · /yardim",
             "en": "<b>Commands:</b> /alert · /price · /list · /summary · /settings · /help"},
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
    "tr": [("alarm", "Alarm kur"), ("fiyat", "Anlık fiyat"), ("liste", "Alarmlarım"),
           ("ozet", "Günlük piyasa özeti"), ("ayarlar", "Dil ve bölge"), ("yardim", "Nasıl kullanılır")],
    "en": [("alert", "Set a price alert"), ("price", "Live price"), ("list", "My alerts"),
           ("summary", "Daily market summary"), ("settings", "Language and region"), ("help", "How it works")],
}


def set_commands(state):
    if state.get("cmds_v") == VERSION:
        return
    ok = tg("setMyCommands", commands=[{"command": c, "description": d} for c, d in CMD_MENU["en"]])
    tg("setMyCommands", commands=[{"command": c, "description": d} for c, d in CMD_MENU["tr"]],
       language_code="tr")
    if ok:
        state["cmds_v"] = VERSION


# ---------------------------------------------------------------- views
def main_kb(lang):
    return {"keyboard": [[T("b_alarm", lang), T("b_price", lang)], [T("b_list", lang), T("b_sum", lang)],
                         [T("b_settings", lang), T("b_help", lang)]],
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
    kb = ikb([[(T("btn_set_alert", lang), f"aa|{q['key']}"), (T("btn_refresh", lang), f"pq|{q['key']}")]])
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
              [(T("btn_write", lang), f"aw|{k}")]])
    return text, kb


def describe(a, lang=None):
    lang = lang or DEFAULT_LANG
    cur, name = a.get("currency", "$"), e(name_of(a["symbol"], lang))
    rep = "🔁 " if a.get("repeat") else ""
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
    lines = [T("list_title", lang, n=len(mine))] + [f"{i}. {describe(a, lang)}" for i, a in enumerate(mine, 1)]
    lines.append(T("list_hint", lang))
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
                   ("b_settings", "settings"), ("b_help", "help")):
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
}


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
    if cmd in ("admin", "broadcast", "allow", "disallow", "pmode", "extend", "endtrial", "users"):
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
        if left <= 0 and not u.get("trial_end_sent"):
            u["trial_end_sent"] = True
            send(int(cid), T("trial_end", lang, contact=_contact(lang)))
        elif 0 < left <= WARN_BEFORE_DAYS and not u.get("trial_warn_sent"):
            u["trial_warn_sent"] = True
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
    for a in state["alerts"]:
        if trial_over(state, a["chat_id"]) and str(a["chat_id"]) != OWNER_CHAT_ID:
            keep.append(a)                      # kept, but silent until the trial is extended
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
        send(int(cid), built[(lang, region)], summary_kb(state, int(cid)))
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
