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
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5").strip()
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
BINANCE_URL = "https://api.binance.com/api/v3/klines"

TIMEFRAMES = {
    "1m": "1min", "5m": "5min", "15m": "15min",
    "1min": "1min", "5min": "5min", "15min": "15min",
}


def claude_generate(
    prompt: str,
    image_bytes: Optional[bytes] = None,
    mime: str = "image/jpeg",
) -> str:
    """Send text and optional chart image to the Anthropic Messages API."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("Claude is not configured. Add ANTHROPIC_API_KEY to .env.")

    content = []
    if image_bytes:
        if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            raise ValueError("Unsupported image type. Send a JPEG, PNG, GIF, or WebP chart.")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": base64.b64encode(image_bytes).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 900,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    last_error = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
                response = client.post(ANTHROPIC_URL, headers=headers, json=payload)

            if response.status_code in (408, 429, 500, 502, 503, 504):
                last_error = f"Claude temporarily unavailable (HTTP {response.status_code})."
                if attempt < 3:
                    delay = min(2 ** attempt * 2, 20)
                    log.warning("%s Retrying in %s seconds.", last_error, delay)
                    time.sleep(delay)
                    continue
                raise RuntimeError(last_error)

            if response.status_code in (401, 403):
                raise RuntimeError("Claude API key is invalid or does not have access. Check ANTHROPIC_API_KEY.")
            if response.status_code == 400:
                raise RuntimeError("Claude rejected the request. Check CLAUDE_MODEL and image format.")
            response.raise_for_status()
            data = response.json()
            answer = "\n".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            ).strip()
            if not answer:
                raise RuntimeError("Claude returned an empty response. Please try again.")
            return answer

        except httpx.TransportError as exc:
            last_error = str(exc)
            if attempt < 3:
                delay = min(2 ** attempt * 2, 20)
                log.warning("Claude network error: %s. Retrying in %s seconds.", exc, delay)
                time.sleep(delay)
                continue
            raise RuntimeError("Could not connect to Claude after several attempts.") from exc

    raise RuntimeError(last_error or "Claude request failed.")


def get_market_data(symbol: str, timeframe: str) -> str:
    tf = TIMEFRAMES.get(timeframe.lower())
    if not tf:
        return "Unsupported timeframe. Use 1m, 5m, or 15m."

    normalized = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
    if normalized.endswith(("USDT", "BUSD", "BTC")):
        interval = timeframe.lower()
        try:
            with httpx.Client(timeout=20) as client:
                r = client.get(
                    BINANCE_URL,
                    params={"symbol": normalized, "interval": interval, "limit": 30},
                )
                r.raise_for_status()
                rows = r.json()
            candles = [
                {"time": x[0], "open": float(x[1]), "high": float(x[2]),
                 "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])}
                for x in rows
            ]
            return (
                f"Source: Binance Spot API. Symbol: {normalized}. "
                f"Timeframe: {timeframe}. Recent OHLCV candles (oldest to newest): {candles}"
            )
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
                return (
                    f"Source: Twelve Data API. Symbol: {symbol.upper()}. "
                    f"Timeframe: {timeframe}. Recent OHLCV candles (oldest to newest): {candles}"
                )
            return f"Twelve Data did not return candles: {data.get('message', data.get('code', 'unknown response'))}"
        except Exception as exc:
            log.warning("Twelve Data request failed: %s", exc)

    if not TWELVEDATA_API_KEY:
        return (
            "No live feed is configured for this symbol. Crypto USDT pairs use Binance automatically. "
            "For forex, stocks, indices, and many commodities, add a Twelve Data API key as TWELVEDATA_API_KEY."
        )
    return "Live market data could not be retrieved. Check the symbol, API plan, and provider status."


ANALYSIS_RULES = """You are a disciplined intraday market-chart analyst. Analyze only evidence visible in the supplied chart or supplied OHLCV data.
Do not invent prices, indicators, news, order flow, or certainty. Distinguish observed facts from inference.
Give conditional next-candle scenarios: (A) if the current candle closes bullish/green, and (B) if it closes bearish/red. State what would invalidate each scenario.
Cover trend/structure, momentum, nearby support/resistance, candle context, and uncertainty when evidence permits.
Use WAIT/NO TRADE when evidence is weak or conflicting. Never promise a winning trade and never claim a calibrated probability.
This bot is analysis/signals only. Never instruct automatic execution.
Keep the reply SHORT, simple, and easy to understand. Use plain language. Maximum 6 short bullet points and about 100 words.
Format:
• Market/timeframe:
• Current trend: Bullish / Bearish / Sideways
• If this candle closes GREEN: one short next-candle scenario.
• If this candle closes RED: one short next-candle scenario.
• Overall view: BUY BIAS / SELL BIAS / WAIT
• Key level or reason: one short sentence.
Do not give a trade entry, target, or stop unless the chart clearly supports it. If symbol or timeframe is unclear, say so briefly."""


def send_message(chat_id: int, text: str) -> None:
    text = text or "No analysis was returned."
    with httpx.Client(timeout=25) as client:
        for start in range(0, len(text), 3900):
            response = client.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id, "text": text[start:start + 3900],
                "disable_web_page_preview": True,
            })
            response.raise_for_status()


def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/start"):
        send_message(chat_id,
            "📊 Day-Trader AI is running with Claude.\n\n"
            "Send a chart screenshot for visual analysis. Include 1m, 5m, or 15m in the caption.\n"
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
            "Claude gives short scenarios, not guaranteed predictions or trade execution.")
        return

    if text.startswith("/market"):
        bits = text.split()
        if len(bits) < 3:
            send_message(chat_id, "Usage: /market SYMBOL TIMEFRAME\nExample: /market BTCUSDT 5m")
            return
        symbol, timeframe = bits[1], bits[2]
        market = get_market_data(symbol, timeframe)
        if market.startswith(("No live feed", "Live market data", "Unsupported")):
            send_message(chat_id, market)
            return
        prompt = (
            f"{ANALYSIS_RULES}\n\n"
            "Analyze this provider data. The latest candle may still be open; "
            "do not treat it as closed unless provider data confirms closure.\n"
            f"{market}"
        )
        try:
            send_message(chat_id, claude_generate(prompt))
        except Exception:
            log.exception("Market analysis failed")
            send_message(chat_id, "Analysis failed. Check the API key/model, then try again.")
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
            if len(image_bytes) > 5 * 1024 * 1024:
                send_message(chat_id, "Image is too large. Please send a screenshot under 5 MB.")
                return
            ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
            caption = text or "No symbol/timeframe caption supplied."
            prompt = (
                f"{ANALYSIS_RULES}\n\n"
                f"User caption: {caption}\n"
                "Inspect the chart screenshot. Identify visible timeframe/symbol only if legible. "
                "Do not assume the current candle has closed. Explain both outcomes depending on its close."
            )
            send_message(chat_id, claude_generate(prompt, image_bytes, mime))
        except Exception:
            log.exception("Screenshot analysis failed")
            send_message(chat_id, "Screenshot analysis failed. Check the image and Claude API settings, then retry.")
        return

    if text:
        send_message(chat_id, "Send a chart screenshot or use /market SYMBOL TIMEFRAME. Type /help for instructions.")


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN. Copy .env.example to .env and add your bot token.")
    if not ANTHROPIC_API_KEY:
        raise SystemExit("Missing ANTHROPIC_API_KEY. Add your Claude API key to .env before starting.")
    offset = None
    log.info("Telegram Day-Trader bot starting with Claude (analysis-only mode)")
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
