from __future__ import annotations

import asyncio
from datetime import datetime

from src.config import DATA_DIR, load_config
from src.history import get_past_suggestions, save_entry
from src.suggest import get_suggestion
from src.weather import fetch_weather

_HISTORY_FILE = DATA_DIR / "history.json"


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


async def main() -> None:
    print("Hôm nay ăn gì — chế độ dòng lệnh\n")

    cfg = load_config()
    meal = _get_meal_period()
    print(f"Địa chỉ: {cfg.address}")
    print(f"Bán kính: {cfg.search_radius_km} km")
    print(f"Bữa ăn: {meal}\n")

    print("Đang lấy thời tiết...")
    weather = await fetch_weather(
        api_key=cfg.openweather_api_key,
        lat=cfg.latitude,
        lon=cfg.longitude,
    )
    print(f"  {weather.city}: {weather.description}, {weather.temp_c}°C\n")

    past = get_past_suggestions(_HISTORY_FILE)
    if past:
        print(f"Đã gợi ý trong tuần:\n{past}\n")

    print("Đang hỏi Gemini...\n")
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
    print(suggestion)

    save_entry(filepath=_HISTORY_FILE, meal=meal, suggestion=suggestion)
    print("\nĐã lưu vào lịch sử tuần.")


if __name__ == "__main__":
    asyncio.run(main())
