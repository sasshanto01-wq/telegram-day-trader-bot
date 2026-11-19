# Telegram Day-Trader Bot

Telegram bot for AI-assisted chart screenshot analysis and short-timeframe market scenarios. **Analysis/signals only; no order execution.**

## Features

- Send a chart screenshot to receive visual analysis from Gemini.
- Ask for conditional scenarios if the current candle closes bullish/green or bearish/red.
- `/market BTCUSDT 5m` retrieves public Binance Spot candles for supported crypto pairs.
- `/market EUR/USD 15m` uses Twelve Data when `TWELVEDATA_API_KEY` is configured.
- Supported intervals: 1m, 5m, 15m.

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
- `GEMINI_API_KEY`: create a Gemini API key in Google AI Studio.
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

## Important limitations

- Binance support here is public **spot** candles, not futures/perpetual contract data.
- Forex, stocks, indices, and many commodities require a Twelve Data API key and a plan/symbol supported by that provider. Provider availability and symbol format vary.
- Screenshot analysis depends on chart readability. Include the symbol and timeframe in the caption.
- The newest candle may still be forming. The bot must not treat it as closed without confirmation.
- AI output is not a calibrated forecast or financial advice. Validate independently; never rely on a single candle prediction.
- The included analysis prompt is a first implementation, not a verified port of any external `/day-trader` skill. Strategy-specific modules and historical validation remain future work.
