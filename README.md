# Telegram Day-Trader Bot

Telegram bot for AI-assisted chart screenshot analysis and short-timeframe market scenarios. **Claude powers chart analysis. Analysis/signals only; no order execution.**

## Features

- Send a chart screenshot for visual analysis by Claude (Anthropic).
- Get short, conditional scenarios if the current candle closes bullish/green or bearish/red.
- `/market BTCUSDT 5m` retrieves public Binance Spot candles for supported crypto pairs.
- `/market EUR/USD 15m` uses Twelve Data when `TWELVEDATA_API_KEY` is configured.
- Supported intervals: 1m, 5m, 15m.
- Claude model is configurable with `CLAUDE_MODEL` (default: `claude-sonnet-5-5`).

## Android Termux setup

Run these commands inside the cloned repository:

```bash
pkg update && pkg upgrade -y
pkg install python git -y
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env
```

In `.env`, add:
- `TELEGRAM_BOT_TOKEN`: create a bot with Telegram's official @BotFather.
- `ANTHROPIC_API_KEY`: create an API key in the Anthropic Console. Claude API usage is billed separately from a Claude chat subscription.
- `CLAUDE_MODEL`: optional; defaults to `claude-sonnet-5-5`.
- `TWELVEDATA_API_KEY`: optional; needed for live non-crypto symbols supported by your Twelve Data plan.

Save nano with **Ctrl+O**, Enter, then **Ctrl+X**. Keep all keys private. Never commit `.env` or paste keys into chat.

## Start

```bash
python bot.py
```

Open your Telegram bot and send `/start`. Send a chart screenshot or try `/market BTCUSDT 5m`.

Stop the bot with **Ctrl+C**. To update later:

```bash
git pull
pip install -r requirements.txt
python bot.py
```

## Market data and limitations

- Binance support uses public **spot** candles, not futures/perpetual contract data.
- Forex, stocks, indices, and many commodities require a Twelve Data API key and a plan/symbol supported by that provider. Provider availability and symbol format vary.
- Screenshot analysis depends on chart readability. Include the symbol and timeframe in the caption.
- The newest candle may still be forming. The bot must not treat it as closed without confirmation.
- Claude image input supports JPEG, PNG, GIF, and WebP. The bot applies a conservative 5 MB upload limit.
- AI output is not a calibrated forecast or financial advice. Validate independently; never rely on a single candle prediction.
- This is analysis/signals only. It does not place broker orders.

## Troubleshooting

- **Missing ANTHROPIC_API_KEY:** check that `.env` exists and contains your Anthropic API key.
- **401/403:** the Anthropic key is invalid, disabled, or lacks API access.
- **429/5xx:** API rate limit or temporary service issue; the bot retries temporary errors.
- **No live feed:** Binance supports eligible crypto spot pairs; configure Twelve Data for supported non-crypto symbols.
