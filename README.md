# Telegram Price Alert Bot

A lightweight Telegram bot that lets anyone set their own price alerts for
**crypto, US stocks and Borsa Istanbul** — and pings them when a level is hit.
Runs for free on GitHub Actions, or 24/7 on any small server.

> The bot only sends notifications. It does not give buy/sell advice.

## Features

- **Level alerts** – `/alarm BTC > 70000`, `/alarm AAPL < 180`
- **Percent-move alerts** – `/alarm ETH %5` (fires on a ±5% move from the current price)
- **Live price** – `/fiyat BTC` or `/price TSLA`
- **Manage alerts** – `/liste` (`/list`), `/sil 2` (`/delete 2`), `/sil hepsi` (`/delete all`)
- **Multi-user** – every chat has its own alerts (max 20 each)
- **Group support** – add it to a Telegram group; it only answers commands
- **Private mode** – restrict usage to chosen chat ids
- **Smart input** – understands `70000`, `70.000`, `70,000`, `70k`, `BTC-USD`, `ETHUSDT`
- **Safety checks** – rejects alerts that would fire instantly, warns about typos (level far from price)
- Turkish interface with English command aliases

| Market | Source | Example |
|---|---|---|
| Crypto | Coinbase public API | `BTC`, `ETH`, `SOL` |
| US stocks & ETFs | Yahoo Finance | `AAPL`, `NVDA`, `SPY` |
| Borsa Istanbul | Yahoo Finance | `THYAO.IS`, `ASELS.IS` |

## Demo

```
You:  /alarm BTC > 70000
Bot:  ✅ Alarm kuruldu: BTC > $70,000
      Şu an: $65,000

...later...

Bot:  🔔 BTC $70,000 seviyesini geçti!
      Şu an: $70,412 (14:35)
```

## Setup (free, ~10 minutes)

1. **Create a bot** – in Telegram, talk to `@BotFather` → `/newbot` → copy the token.
2. **Fork / upload this repo** to GitHub (public repos get free Actions minutes).
3. **Add the token** – *Settings → Secrets and variables → Actions → New repository secret*
   Name: `TELEGRAM_TOKEN`
4. *(Optional)* **Private mode** – *Variables* tab → `ALLOWED_CHAT_IDS` = `12345678,87654321`
5. **Enable** – *Actions* tab → enable workflows → *Price Alert Bot* → *Run workflow*.
6. Send `/start` to your bot.

Optional: in BotFather use `/setcommands` and paste:

```
alarm - Alarm kur: /alarm BTC > 70000
fiyat - Anlık fiyat: /fiyat BTC
liste - Alarmlarım
sil - Alarm sil: /sil 1
yardim - Yardım
```

## Run modes

| Mode | Where | Reply / check speed |
|---|---|---|
| `RUN_MODE=once` | GitHub Actions (every 5 min) | up to ~5–15 min |
| `RUN_MODE=loop` | Any server / PC / Raspberry Pi | instant replies, prices every 30 s |

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN=xxxx
RUN_MODE=loop python price_alert_bot.py
```

On GitHub Actions, alerts are stored in the Actions cache (not committed), so
user chat ids never appear in the public repository.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | – | Bot token (required) |
| `ALLOWED_CHAT_IDS` | empty (public) | Comma-separated chat ids allowed to use the bot |
| `RUN_MODE` | `loop` | `once` or `loop` |
| `STATE_FILE` | `alerts.json` | Where alerts are stored |
| `LOCAL_TZ` | `Europe/Podgorica` | Time zone for timestamps in alerts |

## Customisation ideas

Daily price summary to a channel · volume / RSI alerts · news alerts ·
English-only interface · web dashboard · database storage for many users.

## Disclaimer

Prices come from free public sources and may be delayed. This tool is for
information only and is not investment advice.
