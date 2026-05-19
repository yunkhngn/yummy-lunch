from __future__ import annotations

import logging
import re
import asyncio
import math
from datetime import datetime, time as dt_time
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx
from telegram import LinkPreviewOptions, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from telegram.error import RetryAfter, TimedOut
from telegram.request import HTTPXRequest

from src.config import DATA_DIR, Config, load_config
from src.history import clear_history, get_past_suggestions, save_entry
from src.places import fetch_nearby_places
from src.settings import get_chat_settings, load_settings, update_chat_settings
from src.suggest import get_suggestion, get_thank_you_message
from src.weather import fetch_weather
from src.pointing_handlers import (
    ROOM_STORE_KEY,
    _cleanup_job_callback,
    cmd_cancel_room,
    cmd_create_room,
    cmd_join_room,
    cmd_reveal,
    cmd_start_point,
    handle_vote_callback,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_HISTORY_FILE = DATA_DIR / "history.json"
_SETTINGS_FILE = DATA_DIR / "settings.json"
_URL_RE = re.compile(r"https?://\S+")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
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
        "/eat_shopeefood — Gợi ý + link ShopeeFood\n"
        "/eat_grabfood — Gợi ý + link GrabFood\n"
        "/history — Xem đã gợi ý gì trong tuần\n"
        "/reset — Xóa lịch sử tuần\n"
        "/set_daily HH:MM — Hẹn giờ thông báo Daily meeting (VN)\n"
        "/turn_on — Bật lại hẹn giờ\n"
        "/turn_off — Tắt hẹn giờ\n\n"
        "Sprint Pointing:\n"
        "/create_room — Tạo room đánh điểm\n"
        "/join_room <id> — Join room\n"
        "/start_point — Bắt đầu đánh điểm\n"
        "/reveal — Reveal kết quả\n"
        "/cancel_room — Huỷ room\n\n"
        "Cảm ơn:\n"
        "/thank_you <tên> — Cảm ơn sếp đã đặt đồ ăn",
    )


import unicodedata

_DELIVERY_PLATFORMS = {
    "shopeefood": {"label": "ShopeeFood", "domain": "shopeefood.vn"},
    "grabfood": {"label": "GrabFood", "domain": "food.grab.com"},
}

def _slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def _build_delivery_url(place_name: str, platform: str) -> str:
    """Build a direct delivery URL or platform-specific search URL."""
    if platform == "shopeefood":
        slug = _slugify(place_name)
        # Tạm thời default là ha-noi vì ShopeeFood bắt buộc có region.
        return f"https://shopeefood.vn/ha-noi/{slug}"
    # GrabFood có ID đặc thù phía sau URL quán nên dùng link search là chuẩn nhất.
    return f"https://food.grab.com/vn/vi/restaurants?searchWord={quote_plus(place_name)}"


async def _handle_suggestion_for_chat(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    update: Update | None = None,
    platform: str = "dine_in",
) -> None:
    """Core logic shared by /eat and the daily scheduled job.

    When *update* is provided the reply goes to the user who invoked /eat.
    When *update* is ``None`` (scheduled job) a message is sent directly
    to *chat_id*.
    """
    cfg: Config = context.bot_data["config"]
    meal = _get_meal_period()
    is_delivery = platform in _DELIVERY_PLATFORMS
    platform_label = _DELIVERY_PLATFORMS.get(platform, {}).get("label", "")

    # -- helpers to abstract away "reply vs send" ----------------------------
    async def _reply_text(
        text: str,
        link_preview_options: LinkPreviewOptions | None = None,
    ) -> None:
        if update:
            await _safe_reply(update, text, link_preview_options=link_preview_options)
        else:
            for attempt in range(3):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        link_preview_options=link_preview_options,
                    )
                    return
                except (TimedOut, RetryAfter):
                    await asyncio.sleep(2 + attempt)
                except Exception:
                    logger.exception("send_message failed for chat %s", chat_id)
                    return

    async def _reply_photo(photo_url: str, caption: str | None = None) -> None:
        if update:
            await _safe_photo(update, photo_url, caption=caption)
        else:
            for attempt in range(3):
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=photo_url, caption=caption
                    )
                    return
                except (TimedOut, RetryAfter):
                    await asyncio.sleep(2 + attempt)
                except Exception:
                    logger.exception("send_photo failed for chat %s", chat_id)
                    return

    # -----------------------------------------------------------------------

    if is_delivery:
        await _reply_text(f"Đang tìm món ngon trên {platform_label} cho {meal}...")
    else:
        await _reply_text(f"Đang tìm món ngon cho {meal}...")

    try:
        weather = await fetch_weather(
            lat=cfg.latitude,
            lon=cfg.longitude,
        )

        past = get_past_suggestions(_HISTORY_FILE)

        # Dine-in usually prefers walking distance, delivery can be further.
        radius_km = 3 if is_delivery else cfg.search_radius_km

        # Fetch real nearby places to ground the AI suggestion
        nearby_places = []
        if cfg.geoapify_api_key:
            try:
                nearby_places = await fetch_nearby_places(
                    api_key=cfg.geoapify_api_key,
                    lat=cfg.latitude,
                    lon=cfg.longitude,
                    radius_km=radius_km,
                )
                logger.info(
                    "Fetched %d real nearby places (radius=%dkm) for grounding",
                    len(nearby_places),
                    radius_km,
                )
            except Exception:
                logger.exception("Failed to fetch nearby places, continuing without")

        result = await get_suggestion(
            api_key=cfg.gemini_api_key,
            weather=weather,
            address=cfg.address,
            latitude=cfg.latitude,
            longitude=cfg.longitude,
            radius_km=radius_km,
            meal_period=meal,
            past_suggestions=past,
            nearby_places=nearby_places,
            platform=platform,
        )

        suggestion = result.text
        lines = [line.strip() for line in suggestion.splitlines() if line.strip()]
        first_line = lines[0] if lines else suggestion.strip()

        if is_delivery:
            # --------------- Delivery platform mode -------------------------
            if result.matched_place and result.matched_place.name:
                search_target = result.matched_place.name
            else:
                place_query = _extract_place_query(first_line) or ""
                # Tách lấy phần tên quán nếu chuỗi có chứa địa chỉ (thường phân cách bởi " - " hoặc " — ")
                search_target = place_query.split(" - ")[0].split(" — ")[0].split("-")[0].strip()

            reply_text = first_line
            if search_target:
                # Trực tiếp sinh URL ứng dụng giao hàng hoặc trang tìm kiếm nội bộ của họ
                delivery_url = _build_delivery_url(
                    search_target, platform
                )
                reply_text = (
                    f"{first_line}\n\n"
                    f"Đặt trên {platform_label}:\n"
                    f"{delivery_url}"
                )

            await _reply_text(
                reply_text,
                link_preview_options=LinkPreviewOptions(is_disabled=False),
            )

            save_entry(
                filepath=_HISTORY_FILE,
                meal=meal,
                suggestion=reply_text,
            )
        else:
            # --------------- Dine-in mode (Google Maps) ---------------------
            resolved_url = None
            dest_coords: tuple[float, float] | None = None
            distance_km = _extract_distance_km(first_line)
            mode = _choose_travel_mode(distance_km)

            # Priority 1: Use matched real-place coordinates (most accurate)
            if result.matched_place:
                mp = result.matched_place
                dest_coords = (mp.lat, mp.lon)
                actual_dist = _haversine_km(
                    cfg.latitude, cfg.longitude, mp.lat, mp.lon
                )
                mode = _choose_travel_mode(actual_dist)
                resolved_url = _build_maps_url(
                    origin_lat=cfg.latitude,
                    origin_lon=cfg.longitude,
                    dest_lat=mp.lat,
                    dest_lon=mp.lon,
                    travel_mode=mode,
                )
                logger.info(
                    "Matched real place: %s (%.6f, %.6f)",
                    mp.name,
                    mp.lat,
                    mp.lon,
                )
            else:
                # Priority 2: Geocode the place name from the AI response
                place_query = _extract_place_query(first_line)
                if place_query:
                    resolved_url = _build_maps_url_text_destination(
                        origin_lat=cfg.latitude,
                        origin_lon=cfg.longitude,
                        destination_text=place_query,
                        travel_mode=mode,
                    )
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
                        logger.exception(
                            "Geocoding failed, falling back to text destination URL"
                        )

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

            if static_map_url:
                await _reply_photo(static_map_url, caption=reply_text)
            else:
                await _reply_text(
                    reply_text,
                    link_preview_options=LinkPreviewOptions(is_disabled=False),
                )

            save_entry(
                filepath=_HISTORY_FILE,
                meal=meal,
                suggestion=reply_text,
            )

    except Exception:
        logger.exception("Error generating suggestion for chat %s", chat_id)
        await _reply_text("Có lỗi xảy ra. Vui lòng thử lại sau.")


async def cmd_eat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_suggestion_for_chat(
        chat_id=update.effective_chat.id,
        context=context,
        update=update,
    )


async def cmd_eat_shopeefood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_suggestion_for_chat(
        chat_id=update.effective_chat.id,
        context=context,
        update=update,
        platform="shopeefood",
    )


async def cmd_eat_grabfood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_suggestion_for_chat(
        chat_id=update.effective_chat.id,
        context=context,
        update=update,
        platform="grabfood",
    )


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


# ---------------------------------------------------------------------------
# Daily Scheduling: helpers
# ---------------------------------------------------------------------------

def _parse_time_str(raw: str) -> dt_time | None:
    """Parse 'HH:MM' or 'HH' into a `datetime.time` (naive)."""
    raw = raw.strip()
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return dt_time(hour, minute)
    except (ValueError, IndexError):
        pass
    return None


def _job_name(chat_id: int | str) -> str:
    return f"daily_{chat_id}"


def _remove_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int | str) -> None:
    """Remove existing daily job for *chat_id* (if any)."""
    if context.job_queue is None:
        return
    current_jobs = context.job_queue.get_jobs_by_name(_job_name(chat_id))
    for job in current_jobs:
        job.schedule_removal()


def _schedule_daily_job(
    context_or_app: ContextTypes.DEFAULT_TYPE | Application,
    chat_id: int | str,
    target_time: dt_time,
) -> None:
    """Register a daily job that fires at *target_time* (in VN_TZ)."""
    jq = context_or_app.job_queue
    if jq is None:
        logger.warning("JobQueue unavailable; cannot schedule daily job for chat %s.", chat_id)
        return
    # Remove any existing job first
    current_jobs = jq.get_jobs_by_name(_job_name(chat_id))
    for job in current_jobs:
        job.schedule_removal()

    jq.run_daily(
        _daily_job_callback,
        time=target_time.replace(tzinfo=VN_TZ),
        name=_job_name(chat_id),
        chat_id=int(chat_id),
        data={"chat_id": int(chat_id)},
    )
    logger.info(
        "Scheduled daily job for chat %s at %s (VN)",
        chat_id,
        target_time.strftime("%H:%M"),
    )


async def _daily_job_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback — sends a meeting announcement to the scheduled chat."""
    chat_id = context.job.data["chat_id"]
    logger.info("Running daily meeting announcement for chat %s", chat_id)
    
    chat_cfg = get_chat_settings(_SETTINGS_FILE, chat_id)
    time_str = chat_cfg.get("time", "")
    
    parsed = _parse_time_str(time_str)
    if parsed:
        am_pm_time = parsed.strftime("%I:%M %p")
    else:
        am_pm_time = time_str

    text = f"Daily meeting start at {am_pm_time}, please join the meeting"
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("send_message failed for chat %s", chat_id)


def _restore_daily_jobs(app: Application) -> None:
    """On startup, re-register daily jobs for every enabled chat."""
    settings = load_settings(_SETTINGS_FILE)
    for chat_id_str, cfg_entry in settings.items():
        if not cfg_entry.get("enabled"):
            continue
        time_str = cfg_entry.get("time")
        if not time_str:
            continue
        parsed = _parse_time_str(time_str)
        if parsed is None:
            logger.warning("Invalid time '%s' for chat %s, skipping.", time_str, chat_id_str)
            continue
        _schedule_daily_job(app, int(chat_id_str), parsed)


# ---------------------------------------------------------------------------
# Commands: /set_daily, /turn_on, /turn_off
# ---------------------------------------------------------------------------

async def cmd_set_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _safe_reply(
            update,
            "Vui lòng nhập giờ hẹn. Ví dụ: /set_daily 11:30",
        )
        return

    parsed = _parse_time_str(context.args[0])
    if parsed is None:
        await _safe_reply(
            update,
            "Định dạng giờ không hợp lệ. Dùng HH:MM hoặc HH.\nVí dụ: /set_daily 11:30",
        )
        return

    chat_id = update.effective_chat.id
    time_str = parsed.strftime("%H:%M")
    update_chat_settings(_SETTINGS_FILE, chat_id, time_str=time_str, enabled=True)
    _remove_job(context, chat_id)
    _schedule_daily_job(context, chat_id, parsed)

    await _safe_reply(
        update,
        f"✅ Đã hẹn giờ thông báo Daily meeting mỗi ngày lúc {time_str} (giờ Việt Nam).\n"
        "Dùng /turn_off để tắt.",
    )


async def cmd_turn_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    chat_cfg = get_chat_settings(_SETTINGS_FILE, chat_id)
    time_str = chat_cfg.get("time")

    if not time_str:
        await _safe_reply(
            update,
            "Bạn chưa hẹn giờ nào. Dùng /set_daily HH:MM để bắt đầu.",
        )
        return

    parsed = _parse_time_str(time_str)
    if parsed is None:
        await _safe_reply(update, "Giờ hẹn lưu không hợp lệ. Vui lòng /set_daily lại.")
        return

    update_chat_settings(_SETTINGS_FILE, chat_id, enabled=True)
    _remove_job(context, chat_id)
    _schedule_daily_job(context, chat_id, parsed)

    await _safe_reply(
        update,
        f"✅ Đã bật lại hẹn giờ lúc {time_str} (giờ Việt Nam).",
    )


async def cmd_turn_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    update_chat_settings(_SETTINGS_FILE, chat_id, enabled=False)
    _remove_job(context, chat_id)

    await _safe_reply(
        update,
        "⏸ Đã tắt hẹn giờ. Dùng /turn_on để bật lại.",
    )


async def cmd_thank_you(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _safe_reply(
            update,
            "Vui lòng nhập tên sếp. Ví dụ: /thank_you Anh Nam",
        )
        return

    boss_name = " ".join(context.args)
    cfg: Config = context.bot_data["config"]

    await _safe_reply(update, f"Đang soạn lời cảm ơn gửi {boss_name}...")

    try:
        message = await get_thank_you_message(
            api_key=cfg.gemini_api_key,
            boss_name=boss_name,
        )
        await _safe_reply(update, message or "Có lỗi xảy ra. Vui lòng thử lại sau.")
    except Exception:
        logger.exception("Error generating thank-you message")
        await _safe_reply(update, "Có lỗi xảy ra. Vui lòng thử lại sau.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

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
    app.add_handler(CommandHandler("eat_shopeefood", cmd_eat_shopeefood))
    app.add_handler(CommandHandler("eat_grabfood", cmd_eat_grabfood))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("set_daily", cmd_set_daily))
    app.add_handler(CommandHandler("turn_on", cmd_turn_on))
    app.add_handler(CommandHandler("turn_off", cmd_turn_off))
    app.add_handler(CommandHandler("create_room", cmd_create_room))
    app.add_handler(CommandHandler("join_room", cmd_join_room))
    app.add_handler(CommandHandler("start_point", cmd_start_point))
    app.add_handler(CommandHandler("reveal", cmd_reveal))
    app.add_handler(CommandHandler("cancel_room", cmd_cancel_room))
    app.add_handler(CommandHandler("thank_you", cmd_thank_you))
    app.add_handler(CallbackQueryHandler(handle_vote_callback, pattern=r"^vote:"))
    app.bot_data[ROOM_STORE_KEY] = {}
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            _cleanup_job_callback,
            interval=30,
            first=30,
            name="pointing_cleanup",
        )
    else:
        logger.warning("JobQueue unavailable; pointing cleanup job is disabled.")

    # Restore persisted daily schedules.
    _restore_daily_jobs(app)

    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
