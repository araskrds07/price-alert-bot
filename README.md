# Telegram Price Alert Bot

**Turkish & English · region-aware (Türkiye / USA / Europe / Global)**

A Telegram bot for price alerts on **crypto, US stocks, Borsa Istanbul, gold and FX**.
Everything works with buttons, so there are no commands to memorise. It also does
**charts, technical alerts (RSI, moving-average cross, 52-week high/low, volume), portfolio
tracking** and a **daily market summary**, and it can **sell Premium in Telegram Stars**.
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
| `BTC grafik` / `BTC chart` | Chart image with 1D / 1W / 1M / 1Y buttons |
| `BTC teknik` / `BTC tech` | Technical alerts for that asset |
| `/ekle BTC 0.5 60000` / `/add BTC 0.5 60000` | Adds 0.5 BTC bought at $60,000 to your portfolio |

Bottom buttons: **🔔 Alarm kur · 💱 Fiyat · 📋 Alarmlarım · 💼 Portföy · 📊 Özet · ⚙️ Ayarlar** (+ **⭐ Premium** when it's on)

- **Alarm in 2 taps:** pick an asset, then tap a level such as "📈 +5% → $68,250".
- **Manage alerts with buttons:** delete (🗑), repeat (🔁), set again (after an alert fires), refresh a price (🔄).
- **📈 Charts:** every price has a *Chart* button. You get a clean dark chart image; 1D / 1W / 1M / 1Y switch in place.
- **📐 Technical alerts** (daily chart, checked every 10 minutes, stay on until deleted):
  RSI below 30 / above 70 · 50/200-day moving-average cross (golden / death cross) · new 52-week high / low · volume spike (2× the 20-day average).
  Each one fires when the event happens, then re-arms, so you are not spammed while it lasts.
- **💼 Portfolio:** add what you hold (`BTC 0.5 60000`, or just `THYAO 100` to use today's price). You see value and profit/loss per asset, totals per currency and one combined total in your own currency (₺ / €). Buying more of the same asset averages the cost. The daily summary includes your portfolio.
- **Daily summary:** BIST 100, USD/TL, EUR/TL, gram gold, BTC and ETH, plus today's biggest BIST risers and fallers. Sent every day at a chosen time.
- **Groups:** add the bot to a group. It answers commands and buttons, and ignores normal chat. Only group admins can switch the daily summary on or off.

## Language and region

On first contact the bot asks two questions with buttons: **language** (Türkçe / English) and **region**.
The region sets the quick-pick buttons, the local-currency line, the time zone, the daily summary and what "gold" means:

| Region | Quick picks | Local currency | Summary | "gold" / "altın" |
|---|---|---|---|---|
| 🇹🇷 Türkiye | BTC, gram gold, USD/TRY, BIST 100, THYAO… | ≈ ₺ | BIST 100, USD/TRY, gram gold + BIST movers | gram gold in ₺ |
| 🇺🇸 USA | BTC, S&P 500, Nasdaq, gold, AAPL, NVDA… | — | S&P 500, Nasdaq, Dow + US movers | gold per ounce in $ |
| 🇪🇺 Europe | BTC, EUR/USD, gold, DAX, Euro Stoxx… | ≈ € | Euro Stoxx 50, DAX, EUR/USD | gold per ounce in $ |
| 🌍 Other | BTC, S&P 500, EUR/USD, gold, AAPL… | — | S&P 500, EUR/USD, gold | gold per ounce in $ |

Users change both any time with **⚙️ Settings** (`/settings`, `/ayarlar`). In groups only admins can.
The command menu shows Turkish commands on Turkish phones and English ones everywhere else.

## Premium with Telegram Stars (optional)

Set `PREMIUM_STARS` (e.g. `250`) and the bot gets a **free plan** and a paid **Premium**:

| | Free | ⭐ Premium |
|---|---|---|
| Prices, charts, daily summary | ✅ | ✅ |
| Price alerts | up to `FREE_ALERTS` (3) | unlimited (20) |
| Technical alerts | — | ✅ |
| Portfolio | — | ✅ |

- Users tap **⭐ Get Premium** and pay inside Telegram with Stars. No payment provider or BotFather setup is needed.
- Premium lasts `PREMIUM_DAYS` (30) for the chat where it was bought (a group purchase unlocks the whole group). It does not auto-renew; the bot reminds the user 2 days before it ends.
- When Premium (or a trial) ends, nothing is deleted. Extra alerts are paused (⏸) and come back with Premium.
- With `TRIAL_DAYS` also set, new users get Premium features during the trial and then fall back to the free plan instead of being locked out.
- `/terms` and `/paysupport` are built in, as Telegram requires. `/paysupport message` is forwarded to the owner.
- The Stars go to the bot's balance; the owner withdraws them through Telegram (Fragment).

> **Payments need a server.** Telegram cancels a Stars payment if the bot doesn't confirm it within 10 seconds. On the free GitHub Actions setup there is about a minute between runs, so a payment made in that gap fails (the user is not charged and can just try again). For a bot that sells Premium, run it 24/7 on a small server.

## For the owner

Set `OWNER_CHAT_ID`. You can get this number by sending `/id` to the bot. Then:

- `/admin`: number of users and groups, active alerts, alerts fired, and a switch for private mode
- **New-user notifications**, so you can see who is trying your demo
- **Private mode:** strangers can request access, and you get a message with **✅ Approve / ❌ Deny** buttons
- `/duyuru text`: sends a message to every user
- `/izinver id` · `/izinkaldir id` · `/ozelmod ac|kapat`
- `/kullanicilar`: who is using the bot, when they started, days left, alerts each
- `/uzat id` restarts someone's trial · `/uzat id sinirsiz` removes their time limit · `/bitir id` cuts one person off
- `/premiumver id 30` gives someone 30 days of Premium · `/iade id` refunds their last Stars payment and ends their Premium
- `/admin` also shows active Premium users and total Stars earned; `/kullanicilar` shows who is Premium

**Trials:** with `TRIAL_DAYS` set, each user gets their own countdown from their first message. Two days before the end they get a reminder, and when it runs out the bot stops answering them — their alerts are kept, not deleted, so one `/uzat` brings everything back.

## White-label settings (GitHub → Settings → Secrets and variables → Actions → Variables)

| Variable | Example | What it does |
|---|---|---|
| `OWNER_CHAT_ID` | `123456789` | Admin panel and notifications |
| `DEFAULT_LANG` | `tr` or `en` | Language for groups and before a user chooses |
| `DEFAULT_REGION` | `tr`, `us`, `eu`, `global` | Region for groups and before a user chooses |
| `ONBOARDING` | `0` | Skip the language/region questions and use the defaults |
| `BOT_TITLE` | `Kripto Kulübü Botu` | Name shown in the help message |
| `POPULAR` | `BTC,ETH,GRAMALTIN,USDTRY,ASELS.IS` | Quick-pick buttons |
| `SUMMARY_ASSETS` | `BIST100,USDTRY,GRAMALTIN,BTC` | What the daily summary shows |
| `SUMMARY_TIME` | `18:15` | Default time for the daily summary |
| `LOCAL_TZ` | `Europe/Istanbul` | Time zone |
| `ALLOWED_CHAT_IDS` | `111,222` | Starts in private mode with these chats allowed |
| `TRIAL_DAYS` | `7` | Free days per user, counted from that person's own first message |
| `TRIAL_UNTIL` | `2026-10-31` | Hard stop date for the whole bot |
| `TRIAL_CONTACT` | `@yourname` | Shown when a trial ends |
| `PREMIUM_STARS` | `250` | Turns on the free plan + Premium at this many Stars |
| `PREMIUM_DAYS` | `30` | How long one Premium purchase lasts |
| `FREE_ALERTS` | `3` | Price alerts allowed on the free plan |

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

Coinbase public API (crypto prices and candles) and Yahoo Finance (stocks, BIST, gold, FX).
Technical alerts use daily candles; volume alerts are not available for gold and FX, which have no volume.
Both are free, and prices may be delayed. Gram gold is calculated as gold price (USD/oz) × USD/TRY ÷ 31.1035.

## Disclaimer

For information only. This is not investment advice.
