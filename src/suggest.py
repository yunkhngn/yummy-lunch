from __future__ import annotations

from google import genai

from src.weather import WeatherInfo

_MODEL = "gemini-2.5-flash"


def build_prompt(
    *,
    weather: WeatherInfo,
    address: str,
    latitude: float,
    longitude: float,
    radius_km: int,
    meal_period: str,
    past_suggestions: str,
) -> str:
    history_section = ""
    if past_suggestions:
        history_section = f"""
## Đã gợi ý trong tuần (Thứ 2 → Thứ 6)
{past_suggestions}

QUAN TRỌNG: KHÔNG được gợi ý lại bất kỳ món ăn hoặc quán nào đã xuất hiện ở trên. Hãy đề xuất món và quán hoàn toàn khác.
"""

    maps_origin = f"{latitude},{longitude}"

    return f"""Bạn là một chuyên gia ẩm thực địa phương tại Việt Nam. Hãy gợi ý cho tôi hôm nay ăn gì.

## Thông tin hiện tại
- Địa chỉ của tôi: {address}
- Tọa độ: {latitude}, {longitude}
- Thời tiết: {weather.description}, {weather.temp_c}°C (cảm giác {weather.feels_like_c}°C), độ ẩm {weather.humidity}%, gió {weather.wind_speed} m/s
- Bữa ăn: {meal_period}
- Số người: 5–6 người
- Ngân sách: khoảng 50.000 VND/người
- Bán kính tìm kiếm: {radius_km} km
{history_section}
## Yêu cầu
- Chỉ gợi ý đúng một món ăn duy nhất phù hợp với thời tiết hiện tại
- Gợi ý một quán/hàng ăn cụ thể trong bán kính {radius_km} km quanh địa chỉ trên (phải có tên quán và địa chỉ cụ thể)
- Quán phải phù hợp cho nhóm 5–6 người, giá khoảng 50.000 VND/người (bình dân, quán ăn đường phố hoặc quán cơm bình dân)
- Giải thích ngắn gọn tại sao món này hợp với thời tiết hôm nay (một câu)

## Định dạng trả lời (BẮT BUỘC theo đúng định dạng này, chỉ 2 dòng, KHÔNG emoji, KHÔNG markdown)

Dòng 1: [Món] | [Quán + địa chỉ] | [Giá khoảng XX.000 đồng/người] | [Cách khoảng X,X km]
Dòng 2: [liên kết Google Maps chỉ đường]

Liên kết Google Maps dùng định dạng sau (KHÔNG ngắt dòng, một dòng duy nhất):
https://www.google.com/maps/dir/?api=1&origin={maps_origin}&destination=TÊN+QUÁN+ĐỊA+CHỈ+QUÁN&travelmode=walking
(thay TÊN+QUÁN+ĐỊA+CHỈ+QUÁN bằng tên và địa chỉ quán, dùng dấu + thay khoảng trắng)
Nếu quán cách hơn 1 km thì dùng travelmode=two-wheeler thay cho walking (ưu tiên đi bộ khi gần).

KHÔNG dùng emoji. KHÔNG dùng markdown. KHÔNG dùng dấu ** hay #. Chỉ văn bản thuần. Toàn bộ nội dung trả lời phải dùng tiếng Việt có dấu đầy đủ. Tuyệt đối không trả lời quá 2 dòng."""


async def get_suggestion(
    *,
    api_key: str,
    weather: WeatherInfo,
    address: str,
    latitude: float,
    longitude: float,
    radius_km: int,
    meal_period: str,
    past_suggestions: str,
) -> str:
    prompt = build_prompt(
        weather=weather,
        address=address,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        meal_period=meal_period,
        past_suggestions=past_suggestions,
    )

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )
    return response.text
