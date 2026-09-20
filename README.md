# Telegram Price Alert Bot

A Telegram bot for price alerts on **crypto, US stocks, Borsa Istanbul, gold and FX**.
Everything works with buttons, so there are no commands to memorise. It also
sends a **daily market summary** to private chats and groups.
Runs free on GitHub Actions, or 24/7 on any small server.

> The bot only sends notifications. It does not give buy/sell advice.

## For users

Tap a button, or just type:

| Type | Result |
|---|---|
| `BTC` | Live price, daily % change, and the value in TL |
| `BTC 70000` | Alerts you at 70,000. Above or below is picked automatically |
| `altın 4500` · `dolar 42` · `THYAO 350` | Gold (gram, TL), USD/TRY, Borsa Istanbul |
| `ETH %5` | Alerts you on a ±5% move |
| `SOL 150 tekrar` | Repeating alert: fires on every cross, not just once |
| `BTCTRY 3000000` | Crypto priced in TL |

Bottom buttons: **🔔 Alarm kur · 💱 Fiyat · 📋 Alarmlarım · 📊 Özet**

- **Alarm in 2 taps:** pick an asset, then tap a level such as "📈 +5% → $68,250".
- **Manage alerts with buttons:** delete (🗑), repeat (🔁), set again (after an alert fires), refresh a price (🔄).
- **Daily summary:** BIST 100, USD/TL, EUR/TL, gram gold, BTC and ETH, plus today's biggest BIST risers and fallers. Sent every day at a chosen time.
- **Groups:** add the bot to a group. It answers commands and buttons, and ignores normal chat. Only group admins can switch the daily summary on or off.

## For the owner

Set `OWNER_CHAT_ID`. You can get this number by sending `/id` to the bot. Then:

- `/admin`: number of users and groups, active alerts, alerts fired, and a switch for private mode
- **New-user notifications**, so you can see who is trying your demo
- **Private mode:** strangers can request access, and you get a message with **✅ Approve / ❌ Deny** buttons
- `/duyuru text`: sends a message to every user
- `/izinver id` · `/izinkaldir id` · `/ozelmod ac|kapat`
- `/kullanicilar`: who is using the bot, when they started, days left, alerts each
- `/uzat id` restarts someone's trial · `/uzat id sinirsiz` removes their time limit · `/bitir id` cuts one person off

**Trials:** with `TRIAL_DAYS` set, each user gets their own countdown from their first message. Two days before the end they get a reminder, and when it runs out the bot stops answering them — their alerts are kept, not deleted, so one `/uzat` brings everything back.

## White-label settings (GitHub → Settings → Secrets and variables → Actions → Variables)

| Variable | Example | What it does |
|---|---|---|
| `OWNER_CHAT_ID` | `123456789` | Admin panel and notifications |
| `BOT_TITLE` | `Kripto Kulübü Botu` | Name shown in the help message |
| `POPULAR` | `BTC,ETH,GRAMALTIN,USDTRY,ASELS.IS` | Quick-pick buttons |
| `SUMMARY_ASSETS` | `BIST100,USDTRY,GRAMALTIN,BTC` | What the daily summary shows |
| `SUMMARY_TIME` | `18:15` | Default time for the daily summary |
| `LOCAL_TZ` | `Europe/Istanbul` | Time zone |
| `ALLOWED_CHAT_IDS` | `111,222` | Starts in private mode with these chats allowed |
| `TRIAL_DAYS` | `7` | Free days per user, counted from that person's own first message |
| `TRIAL_UNTIL` | `2026-10-31` | Hard stop date for the whole bot |
| `TRIAL_CONTACT` | `@yourname` | Shown when a trial ends |

The only secret is `TELEGRAM_TOKEN`, which you get from @BotFather.

## Setup (free, about 10 minutes)

1. In Telegram, message `@BotFather` → `/newbot` → copy the token.
2. Create a **public** GitHub repo and upload `price_alert_bot.py`, `requirements.txt` and `README.md`.
3. Create the file `.github/workflows/price-alert.yml` with the content from this repo.
4. Go to *Settings → Secrets and variables → Actions* and add the secret `TELEGRAM_TOKEN`.
5. Go to *Actions* → enable workflows → *Price Alert Bot* → *Run workflow*.
6. Send `/start` to the bot. Then send `/id` and save the number as the `OWNER_CHAT_ID` variable.

The command menu is registered with Telegram automatically, so you don't need `/setcommands`.

## Hosting

| Option | Response time | Cost |
|---|---|---|
| GitHub Actions (included workflow) | Near-instant replies. Each run listens for 9 minutes and a new one is always queued, with ~1 minute gaps between runs | Free on public repos |
| Any VPS / Raspberry Pi: `RUN_MODE=loop python price_alert_bot.py` | Instant, 24/7 | ~$4–6/month |

GitHub Actions is meant for CI. Running a bot there is fine for a demo or personal use. For paying customers, use a small server.

## Data sources

Coinbase public API (crypto) and Yahoo Finance (stocks, BIST, gold, FX).
Both are free, and prices may be delayed. Gram gold is calculated as gold price (USD/oz) × USD/TRY ÷ 31.1035.

## Disclaimer

For information only. This is not investment advice.
