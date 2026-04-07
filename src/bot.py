from __future__ import annotations

import logging
import re
import asyncio
import math
from datetime import datetime
from urllib.parse import quote_plus

import httpx
from telegram import LinkPreviewOptions, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import RetryAfter, TimedOut
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
_GEOAPIFY_URL = "https://api.geoapify.com/v1/geocode/search"


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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


async def _geocode_place(
    query: str,
    *,
    origin_lat: float,
    origin_lon: float,
    radius_km: int,
    geoapify_api_key: str | None,
) -> tuple[float, float] | None:
    if geoapify_api_key:
        async with httpx.AsyncClient(timeout=10) as client:
            # Pass 1: strict search inside user radius
            params1 = {
                "text": query,
                "filter": f"circle:{origin_lon},{origin_lat},{radius_km * 1000}",
                "bias": f"proximity:{origin_lon},{origin_lat}",
                "lang": "vi",
                "limit": 5,
                "apiKey": geoapify_api_key,
            }
            resp = await client.get(_GEOAPIFY_URL, params=params1)
            if resp.status_code == 200:
                data = resp.json().get("features", [])
                best: tuple[float, float] | None = None
                best_dist = float("inf")
                for item in data:
                    try:
                        lon, lat = item["geometry"]["coordinates"]
                        lat = float(lat)
                        lon = float(lon)
                    except (KeyError, ValueError, TypeError):
                        continue
                    dist = _haversine_km(origin_lat, origin_lon, lat, lon)
                    if dist < best_dist:
                        best_dist = dist
                        best = (lat, lon)
                if best:
                    return best

            # Pass 2: broaden query and remove hard circle filter
            params2 = {
                "text": query,
                "bias": f"proximity:{origin_lon},{origin_lat}",
                "lang": "vi",
                "limit": 10,
                "apiKey": geoapify_api_key,
            }
            resp2 = await client.get(_GEOAPIFY_URL, params=params2)
            if resp2.status_code == 200:
                data2 = resp2.json().get("features", [])
                best2: tuple[float, float] | None = None
                best_dist2 = float("inf")
                for item in data2:
                    try:
                        lon, lat = item["geometry"]["coordinates"]
                        lat = float(lat)
                        lon = float(lon)
                    except (KeyError, ValueError, TypeError):
                        continue
                    dist = _haversine_km(origin_lat, origin_lon, lat, lon)
                    if dist < best_dist2:
                        best_dist2 = dist
                        best2 = (lat, lon)
                if best2:
                    return best2

    # Fallback: Nominatim
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 5,
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

    best: tuple[float, float] | None = None
    best_dist = float("inf")
    for item in data:
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        dist = _haversine_km(origin_lat, origin_lon, lat, lon)
        if dist < best_dist:
            best_dist = dist
            best = (lat, lon)
    return best


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


def _build_maps_url_text_destination(
    *,
    origin_lat: float,
    origin_lon: float,
    destination_text: str,
    travel_mode: str,
) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin_lat},{origin_lon}"
        f"&destination={quote_plus(destination_text)}"
        f"&travelmode={travel_mode}"
    )


def _build_geoapify_static_map_url(
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    geoapify_api_key: str,
) -> str:
    return (
        "https://maps.geoapify.com/v1/staticmap"
        "?style=osm-bright"
        "&width=900&height=450"
        f"&marker=lonlat:{origin_lon},{origin_lat};color:%23007aff;size:small"
        f"&marker=lonlat:{dest_lon},{dest_lat};color:%23ff3b30;size:large"
        f"&apiKey={geoapify_api_key}"
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
        except RetryAfter as e:
            wait_seconds = int(getattr(e, "retry_after", 3))
            if attempt >= retries:
                logger.exception("Telegram flood control after retries")
                return
            await asyncio.sleep(wait_seconds + 1)
        except Exception:
            logger.exception("Telegram reply failed")
            return


async def _safe_photo(
    update: Update,
    photo_url: str,
    *,
    caption: str | None = None,
    retries: int = 2,
) -> None:
    if not update.message:
        return
    for attempt in range(retries + 1):
        try:
            await update.message.reply_photo(photo=photo_url, caption=caption)
            return
        except TimedOut:
            if attempt >= retries:
                logger.exception("Telegram photo timeout after retries")
                return
            await asyncio.sleep(1 + attempt)
        except RetryAfter as e:
            wait_seconds = int(getattr(e, "retry_after", 3))
            if attempt >= retries:
                logger.exception("Telegram flood control on photo after retries")
                return
            await asyncio.sleep(wait_seconds + 1)
        except Exception:
            logger.exception("Telegram photo send failed")
            return


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
        dest_coords: tuple[float, float] | None = None
        place_query = _extract_place_query(first_line)
        distance_km = _extract_distance_km(first_line)
        mode = _choose_travel_mode(distance_km)

        # Safe fallback URL (always ASCII/URL-encoded) if geocoding fails.
        if place_query:
            resolved_url = _build_maps_url_text_destination(
                origin_lat=cfg.latitude,
                origin_lon=cfg.longitude,
                destination_text=place_query,
                travel_mode=mode,
            )

        if place_query:
            try:
                dest = await _geocode_place(
                    place_query,
                    origin_lat=cfg.latitude,
                    origin_lon=cfg.longitude,
                    radius_km=cfg.search_radius_km,
                    geoapify_api_key=cfg.geoapify_api_key,
                )
                if dest:
                    dest_coords = dest
                    resolved_url = _build_maps_url(
                        origin_lat=cfg.latitude,
                        origin_lon=cfg.longitude,
                        dest_lat=dest[0],
                        dest_lon=dest[1],
                        travel_mode=mode,
                    )
            except Exception:
                logger.exception("Geocoding failed, falling back to text destination URL")

        # Send one single message to avoid Telegram flood control (429).
        url_match = _URL_RE.search(suggestion)
        url = resolved_url or (url_match.group(0) if url_match else "")
        reply_text = first_line if first_line else suggestion.strip()
        if url:
            reply_text = f"{reply_text}\n{url}"
        static_map_url = None
        if cfg.geoapify_api_key and dest_coords:
            static_map_url = _build_geoapify_static_map_url(
                origin_lat=cfg.latitude,
                origin_lon=cfg.longitude,
                dest_lat=dest_coords[0],
                dest_lon=dest_coords[1],
                geoapify_api_key=cfg.geoapify_api_key,
            )

        # Prefer sending static map image (stable visual preview).
        if static_map_url:
            await _safe_photo(update, static_map_url, caption=reply_text)
        else:
            await _safe_reply(
                update,
                reply_text,
                link_preview_options=LinkPreviewOptions(
                    is_disabled=False
                ),
            )

        save_entry(
            filepath=_HISTORY_FILE,
            meal=meal,
            suggestion=reply_text,
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
