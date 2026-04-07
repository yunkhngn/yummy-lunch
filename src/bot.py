from __future__ import annotations

import logging
import re
import asyncio
from datetime import datetime

import httpx
from telegram import LinkPreviewOptions, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TimedOut
from telegram.request import HTTPXRequest

from src.config import DATA_DIR, Config, load_config
from src.history import clear_history, get_past_suggestions, save_entry
from src.suggest import get_suggestion
from src.weather import fetch_weather

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_HISTORY_FILE = DATA_DIR / "history.json"
_URL_RE = re.compile(r"https?://\S+")
_DISTANCE_RE = re.compile(r"Cách khoảng[:\s]*([0-9]+(?:[.,][0-9]+)?)\s*km", re.IGNORECASE)
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _get_meal_period() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 10:
        return "bữa sáng"
    elif 10 <= hour < 14:
        return "bữa trưa"
    elif 14 <= hour < 17:
        return "bữa xế / ăn vặt"
    elif 17 <= hour < 21:
        return "bữa tối"
    else:
        return "ăn khuya"


def _extract_place_query(first_line: str) -> str | None:
    parts = [p.strip() for p in first_line.split("|")]
    if len(parts) < 2:
        return None
    # Expect: [Món] | [Quán + địa chỉ] | ...
    return parts[1]


def _extract_distance_km(first_line: str) -> float | None:
    m = _DISTANCE_RE.search(first_line)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _choose_travel_mode(distance_km: float | None) -> str:
    if distance_km is None:
        return "walking"
    return "walking" if distance_km <= 1.0 else "two-wheeler"


async def _geocode_place(query: str) -> tuple[float, float] | None:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "accept-language": "vi",
        "countrycodes": "vn",
    }
    headers = {
        "User-Agent": "hom-nay-an-gi-bot/1.0 (telegram bot)",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_NOMINATIM_URL, params=params, headers=headers)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data:
        return None
    try:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    return lat, lon


def _build_maps_url(
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    travel_mode: str,
) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin_lat},{origin_lon}"
        f"&destination={dest_lat},{dest_lon}"
        f"&travelmode={travel_mode}"
    )


async def _safe_reply(
    update: Update,
    text: str,
    *,
    link_preview_options: LinkPreviewOptions | None = None,
    retries: int = 2,
) -> None:
    if not update.message:
        return
    for attempt in range(retries + 1):
        try:
            await update.message.reply_text(
                text,
                link_preview_options=link_preview_options,
            )
            return
        except TimedOut:
            if attempt >= retries:
                logger.exception("Telegram reply timeout after retries")
                return
            await asyncio.sleep(1 + attempt)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe_reply(
        update,
        "Hôm nay ăn gì?\n\n"
        "/eat — Gợi ý món ăn theo thời tiết\n"
        "/history — Xem đã gợi ý gì trong tuần\n"
        "/reset — Xóa lịch sử tuần",
    )


async def cmd_eat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["config"]
    meal = _get_meal_period()

    await _safe_reply(update, "Đang tìm món ngon cho bữa trưa...")

    try:
        weather = await fetch_weather(
            lat=cfg.latitude,
            lon=cfg.longitude,
        )

        past = get_past_suggestions(_HISTORY_FILE)

        suggestion = await get_suggestion(
            api_key=cfg.gemini_api_key,
            weather=weather,
            address=cfg.address,
            latitude=cfg.latitude,
            longitude=cfg.longitude,
            radius_km=cfg.search_radius_km,
            meal_period=meal,
            past_suggestions=past,
        )

        # Normalize to 2-line output and replace destination with
        # coordinates from OSM geocoding for higher route accuracy.
        lines = [line.strip() for line in suggestion.splitlines() if line.strip()]
        first_line = lines[0] if lines else suggestion.strip()
        resolved_url = None
        place_query = _extract_place_query(first_line)
        if place_query:
            distance_km = _extract_distance_km(first_line)
            mode = _choose_travel_mode(distance_km)
            dest = await _geocode_place(place_query)
            if dest:
                resolved_url = _build_maps_url(
                    origin_lat=cfg.latitude,
                    origin_lon=cfg.longitude,
                    dest_lat=dest[0],
                    dest_lon=dest[1],
                    travel_mode=mode,
                )

        # Try to force Telegram to render preview by sending URL
        # as a dedicated line with preview explicitly enabled.
        url_match = _URL_RE.search(suggestion)
        if url_match:
            url = resolved_url or url_match.group(0)
            text_without_url = first_line
            if text_without_url:
                await _safe_reply(update, text_without_url)
            await _safe_reply(
                update,
                url,
                link_preview_options=LinkPreviewOptions(
                    is_disabled=False,
                    url=url,
                ),
            )
        else:
            fallback = suggestion.strip()
            if resolved_url and first_line:
                fallback = f"{first_line}\n{resolved_url}"
            await _safe_reply(
                update,
                fallback,
                link_preview_options=LinkPreviewOptions(
                    is_disabled=False
                ),
            )

        save_entry(
            filepath=_HISTORY_FILE,
            meal=meal,
            suggestion=f"{first_line}\n{resolved_url or (url_match.group(0) if url_match else '')}".strip(),
        )

    except Exception:
        logger.exception("Error in /eat command")
        await _safe_reply(update, "Có lỗi xảy ra. Vui lòng thử lại sau.")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    past = get_past_suggestions(_HISTORY_FILE)
    if past:
        await _safe_reply(update, f"Đã gợi ý trong tuần:\n\n{past}")
    else:
        await _safe_reply(
            update,
            "Chưa có gợi ý nào trong tuần này. Dùng /eat để bắt đầu.",
        )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_history(_HISTORY_FILE)
    await _safe_reply(
        update,
        "Đã xóa lịch sử tuần. Dùng /eat để nhận gợi ý mới.",
    )


def main() -> None:
    cfg = load_config()

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = Application.builder().token(cfg.telegram_token).request(request).build()
    app.bot_data["config"] = cfg

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("eat", cmd_eat))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("reset", cmd_reset))

    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
