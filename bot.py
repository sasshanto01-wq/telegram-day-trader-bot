import os
import time
import base64
import logging
from typing import Optional

import httpx

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("day-trader-bot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
BINANCE_URL = "https://api.binance.com/api/v3/klines"

TIMEFRAMES = {
    "1m": "1min", "5m": "5min", "15m": "15min",
    "1min": "1min", "5min": "5min", "15min": "15min",
}


def gemini_generate(prompt: str, image_bytes: Optional[bytes] = None, mime: str = "image/jpeg") -> str:
    if not GEMINI_API_KEY:
        return "Gemini is not configured. Add GEMINI_API_KEY to your .env file and restart the bot."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    parts = [{"text": prompt}]
    if image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": mime,
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }
        })
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1100},
    }
    # Gemini can temporarily return 503 during capacity spikes. Retry only
    # transient server/rate-limit errors; do not loop on invalid requests or keys.
    data = None
    last_error = None
    for attempt in range(5):
        try:
            with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
                response = client.post(url, params={"key": GEMINI_API_KEY}, json=payload)
            if response.status_code in (408, 429, 500, 502, 503, 504):
                last_error = f"Gemini temporarily unavailable (HTTP {response.status_code}): {response.text[:500]}"
                if attempt < 4:
                    delay = min(2 ** attempt * 2, 30)
                    log.warning("%s; retrying in %s seconds", last_error, delay)
                    time.sleep(delay)
                    continue
                raise RuntimeError(last_error)
            response.raise_for_status()
            data = response.json()
            break
        except httpx.TransportError as exc:
            last_error = str(exc)
            if attempt < 4:
                delay = min(2 ** attempt * 2, 30)
                log.warning("Gemini network error: %s; retrying in %s seconds", exc, delay)
                time.sleep(delay)
                continue
            raise RuntimeError(f"Gemini network request failed after retries: {last_error}") from exc
    if data is None:
        raise RuntimeError(last_error or "Gemini request failed after retries")
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected Gemini response: {data}")


def get_market_data(symbol: str, timeframe: str) -> str:
    tf = TIMEFRAMES.get(timeframe.lower())
    if not tf:
        return "Unsupported timeframe. Use 1m, 5m, or 15m."

    # Binance public spot candles: crypto pairs such as BTCUSDT, ETHUSDT.
    normalized = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
    if normalized.endswith("USDT") or normalized.endswith("BUSD") or normalized.endswith("BTC"):
        interval = timeframe.lower().replace("m", "m")
        try:
            with httpx.Client(timeout=20) as client:
                r = client.get(BINANCE_URL, params={"symbol": normalized, "interval": interval, "limit": 30})
                r.raise_for_status()
                rows = r.json()
            candles = [
                {"time": x[0], "open": float(x[1]), "high": float(x[2]),
                 "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])}
                for x in rows
            ]
            return f"Source: Binance Spot API. Symbol: {normalized}. Timeframe: {timeframe}. Recent OHLCV candles (oldest to newest): {candles}"
        except Exception as exc:
            log.warning("Binance data request failed: %s", exc)

    if TWELVEDATA_API_KEY:
        try:
            with httpx.Client(timeout=25) as client:
                r = client.get(TWELVEDATA_URL, params={
                    "symbol": symbol.upper(), "interval": tf, "outputsize": 30,
                    "apikey": TWELVEDATA_API_KEY, "format": "JSON",
                })
                r.raise_for_status()
                data = r.json()
            if "values" in data:
                values = list(reversed(data["values"]))
                candles = [{
                    "time": x.get("datetime"),
                    "open": float(x["open"]), "high": float(x["high"]),
                    "low": float(x["low"]), "close": float(x["close"]),
                    "volume": x.get("volume"),
                } for x in values]
                return f"Source: Twelve Data API. Symbol: {symbol.upper()}. Timeframe: {timeframe}. Recent OHLCV candles (oldest to newest): {candles}"
            return f"Twelve Data did not return candles: {data.get('message', data.get('code', 'unknown response'))}"
        except Exception as exc:
            log.warning("Twelve Data request failed: %s", exc)

    if not TWELVEDATA_API_KEY:
        return ("No live feed is configured for this symbol. Crypto USDT pairs use Binance automatically. "
                "For forex, stocks, indices, and many commodities, add a Twelve Data API key as TWELVEDATA_API_KEY.")
    return "Live market data could not be retrieved. Check the symbol, API plan, and provider status."


ANALYSIS_RULES = """You are a disciplined intraday market-chart analyst. Analyze only evidence visible in the supplied chart or supplied OHLCV data.
Do not invent prices, indicators, news, order flow, or certainty. Distinguish observed facts from inference.
Give conditional next-candle scenarios: (A) if the current candle closes bullish/green, and (B) if it closes bearish/red. State what would invalidate each scenario.
Cover trend/structure, momentum, nearby support/resistance, candle context, and uncertainty when evidence permits.
Use WAIT/NO TRADE when evidence is weak or conflicting. Never promise a winning trade and never claim a calibrated probability.
This bot is analysis/signals only. Never instruct automatic execution.
Format the answer with: Market & timeframe; What is visible; Bullish-close scenario; Bearish-close scenario; Bias (bullish/bearish/neutral); Key invalidation; Risk note.
If the screenshot does not clearly show the symbol or timeframe, say so."""


def send_message(chat_id: int, text: str) -> None:
    # Telegram message limit is 4096 characters.
    text = text or "No analysis was returned."
    with httpx.Client(timeout=25) as client:
        for start in range(0, len(text), 3900):
            client.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id, "text": text[start:start + 3900],
                "disable_web_page_preview": True,
            }).raise_for_status()


def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/start"):
        send_message(chat_id,
            "📊 Day-Trader AI is running.\n\n"
            "Send a chart screenshot for visual analysis. Include 1m, 5m, or 15m in the caption if possible.\n"
            "Use /market BTCUSDT 5m for live crypto candles.\n"
            "Use /market EUR/USD 15m for supported non-crypto symbols (requires Twelve Data key).\n"
            "Commands: /help")
        return
    if text.startswith("/help"):
        send_message(chat_id,
            "How to use:\n"
            "• Send a chart screenshot; optional caption: BTCUSDT 5m\n"
            "• /market BTCUSDT 1m\n"
            "• /market EUR/USD 5m (requires TWELVEDATA_API_KEY)\n"
            "Supported timeframes: 1m, 5m, 15m.\n"
            "The bot provides scenarios, not guaranteed predictions or trade execution.")
        return

    if text.startswith("/market"):
        bits = text.split()
        if len(bits) < 3:
            send_message(chat_id, "Usage: /market SYMBOL TIMEFRAME\nExample: /market BTCUSDT 5m")
            return
        symbol, timeframe = bits[1], bits[2]
        market = get_market_data(symbol, timeframe)
        if market.startswith("No live feed") or market.startswith("Live market data") or market.startswith("Unsupported"):
            send_message(chat_id, market)
            return
        prompt = f"{ANALYSIS_RULES}\n\nAnalyze this verified provider data. The latest candle may still be open; do not treat it as closed unless provider data confirms closure.\n{market}"
        try:
            send_message(chat_id, gemini_generate(prompt))
        except Exception as exc:
            log.exception("Market analysis failed")
            send_message(chat_id, f"Analysis failed: {exc}")
        return

    photos = message.get("photo")
    if photos:
        try:
            photo = photos[-1]
            with httpx.Client(timeout=30) as client:
                f = client.get(f"{TELEGRAM_API}/getFile", params={"file_id": photo["file_id"]})
                f.raise_for_status()
                file_path = f.json()["result"]["file_path"]
                img = client.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
                img.raise_for_status()
                image_bytes = img.content
            caption = text or "No symbol/timeframe caption supplied."
            prompt = (
                f"{ANALYSIS_RULES}\n\n"
                f"User caption: {caption}\n"
                "Inspect the chart screenshot. Identify visible timeframe/symbol only if legible. "
                "Do not assume the current candle has closed. Explain both possible outcomes depending on its close."
            )
            mime = "image/png" if file_path.lower().endswith(".png") else "image/jpeg"
            send_message(chat_id, gemini_generate(prompt, image_bytes, mime))
        except Exception as exc:
            log.exception("Screenshot analysis failed")
            send_message(chat_id, f"Screenshot analysis failed: {exc}")
        return

    if text:
        send_message(chat_id, "Send a chart screenshot or use /market SYMBOL TIMEFRAME. Type /help for instructions.")


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN. Copy .env.example to .env and add your bot token.")
    if not GEMINI_API_KEY:
        raise SystemExit("Missing GEMINI_API_KEY. Add it to .env before starting.")
    offset = None
    log.info("Telegram Day-Trader bot starting (analysis-only mode)")
    while True:
        try:
            with httpx.Client(timeout=40) as client:
                params = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                response = client.get(f"{TELEGRAM_API}/getUpdates", params=params)
                response.raise_for_status()
                updates = response.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception:
                    log.exception("Update handler failed")
        except KeyboardInterrupt:
            log.info("Bot stopped by user")
            break
        except Exception:
            log.exception("Polling error; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
