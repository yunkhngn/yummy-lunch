from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hôm nay ăn gì?\n\n"
        "/eat — Gợi ý món ăn theo thời tiết\n"
        "/history — Xem đã gợi ý gì trong tuần\n"
        "/reset — Xóa lịch sử tuần",
    )


async def cmd_eat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["config"]
    meal = _get_meal_period()

    await update.message.reply_text(f"Đang tìm món ngon cho {meal}...")

    try:
        weather = await fetch_weather(
            api_key=cfg.openweather_api_key,
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

        weather_line = (
            f"{weather.city}: {weather.description}, {weather.temp_c}°C"
        )
        reply = f"{weather_line}\n\n{suggestion}"

        if len(reply) > 4096:
            for i in range(0, len(reply), 4096):
                await update.message.reply_text(reply[i : i + 4096])
        else:
            await update.message.reply_text(reply)

        save_entry(filepath=_HISTORY_FILE, meal=meal, suggestion=suggestion)

    except Exception:
        logger.exception("Error in /eat command")
        await update.message.reply_text(
            "Có lỗi xảy ra. Vui lòng thử lại sau.",
        )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    past = get_past_suggestions(_HISTORY_FILE)
    if past:
        await update.message.reply_text(f"Đã gợi ý trong tuần:\n\n{past}")
    else:
        await update.message.reply_text(
            "Chưa có gợi ý nào trong tuần này. Dùng /eat để bắt đầu.",
        )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_history(_HISTORY_FILE)
    await update.message.reply_text(
        "Đã xóa lịch sử tuần. Dùng /eat để nhận gợi ý mới.",
    )


def main() -> None:
    cfg = load_config()

    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data["config"] = cfg

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("eat", cmd_eat))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("reset", cmd_reset))

    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
