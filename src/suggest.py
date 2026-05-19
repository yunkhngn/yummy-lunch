from __future__ import annotations

from dataclasses import dataclass

from google import genai

from src.places import Place
from src.weather import WeatherInfo

_MODEL = "gemini-3.1-flash-lite-preview"


@dataclass
class SuggestionResult:
    """Structured result from the suggestion engine."""

    text: str
    matched_place: Place | None = None


# ---------------------------------------------------------------------------
# Helpers for grounding the prompt with real place data
# ---------------------------------------------------------------------------


def _format_places_list(places: list[Place]) -> str:
    """Format a list of *Place* objects into a numbered prompt section."""
    lines: list[str] = []
    for i, p in enumerate(places, 1):
        dist_km = p.distance_m / 1000
        line = f"{i}. {p.name} — {p.address} (cách {dist_km:.1f} km)"
        lines.append(line)
    return "\n".join(lines)


def match_place(response_text: str, places: list[Place]) -> Place | None:
    """Find which *Place* the AI chose by longest name-match in the response.

    Returns ``None`` when no place from the list can be matched.
    """
    if not places:
        return None
    first_line = response_text.split("\n")[0].lower()
    best: Place | None = None
    best_len = 0
    for place in places:
        name_lower = place.name.lower()
        if name_lower in first_line and len(name_lower) > best_len:
            best = place
            best_len = len(name_lower)
    return best


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


_PLATFORM_NAMES = {
    "shopeefood": "ShopeeFood",
    "grabfood": "GrabFood",
}


def build_thank_you_prompt(boss_name: str) -> str:
    return f"""Bạn là một nhân viên văn phòng người Việt Nam.
Sếp của bạn tên là {boss_name} vừa đặt đồ ăn cho cả nhóm.
Hãy viết một lời cảm ơn chân thành gửi đến {boss_name}.

Yêu cầu:
- Viết đúng 3 đoạn văn, mỗi đoạn cách nhau một dòng trống
- Đoạn 1: Bày tỏ sự biết ơn chân thành vì {boss_name} đã quan tâm đặt đồ ăn cho cả nhóm
- Đoạn 2: Ca ngợi sự chu đáo và tâm lý của {boss_name} một cách tự nhiên, không quá mức
- Đoạn 3: Lời chúc nhẹ nhàng và cam kết làm việc tốt hơn
- Giọng văn: lịch sự, ấm áp, tự nhiên — như nhân viên thân thiết nói chuyện với sếp, có thể có 1-2 câu duyên dáng nhẹ nhàng
- Xưng hô phù hợp, dùng đúng tên {boss_name}
- Mỗi đoạn dài 3-5 câu
- Toàn bộ bằng tiếng Việt có dấu đầy đủ
- KHÔNG dùng emoji
- KHÔNG dùng markdown, KHÔNG dùng dấu ** hay #
- Chỉ văn bản thuần"""


async def get_thank_you_message(*, api_key: str, boss_name: str) -> str:
    prompt = build_thank_you_prompt(boss_name)
    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )
    return response.text or ""


def build_prompt(
    *,
    weather: WeatherInfo,
    address: str,
    latitude: float,
    longitude: float,
    radius_km: int,
    meal_period: str,
    past_suggestions: str,
    nearby_places: list[Place] | None = None,
    platform: str = "dine_in",
) -> str:
    platform_name = _PLATFORM_NAMES.get(platform)
    is_delivery = platform_name is not None

    history_section = ""
    if past_suggestions:
        history_section = f"""
## Đã gợi ý trong tuần (Thứ 2 → Thứ 6)
{past_suggestions}

QUAN TRỌNG: KHÔNG được gợi ý lại bất kỳ món ăn hoặc quán nào đã xuất hiện ở trên. Hãy đề xuất món và quán hoàn toàn khác.
"""

    # ---- grounding section: real places from Geoapify ---------------------
    places_section = ""
    if nearby_places:
        places_list = _format_places_list(nearby_places)
        places_section = f"""
## Danh sách quán ăn thực tế gần đây (ĐÃ XÁC MINH TỒN TẠI)
BẮT BUỘC chọn MỘT quán từ danh sách dưới đây. TUYỆT ĐỐI KHÔNG được bịa ra quán không có trong danh sách.
Sử dụng ĐÚNG tên quán và địa chỉ như trong danh sách.

{places_list}
"""

    # ---- constraint wording depends on whether we have real data ----------
    if nearby_places:
        constraint = (
            "- BẮT BUỘC chọn quán từ danh sách đã cho ở trên. "
            "Dùng đúng tên quán và địa chỉ trong danh sách. "
            "KHÔNG tự bịa quán.\n"
        )
    else:
        constraint = (
            f"- Gợi ý một quán/hàng ăn cụ thể THỰC SỰ TỒN TẠI trong bán kính {radius_km} km "
            "quanh địa chỉ trên (phải có tên quán và địa chỉ cụ thể)\n"
        )

    # ---- delivery-specific requirements -----------------------------------
    delivery_extra = ""
    if is_delivery:
        delivery_extra = (
            f"- Quán phải phổ biến và có khả năng cao có trên {platform_name} "
            "(ưu tiên quán có giao hàng qua app)\n"
            "- Món phải phù hợp để giao hàng (không bị nguội/hỏng khi ship)\n"
        )

    maps_origin = f"{latitude},{longitude}"

    # ---- format section differs for dine-in vs delivery -------------------
    if is_delivery:
        format_section = f"""## Định dạng trả lời (BẮT BUỘC theo đúng định dạng này, chỉ 1 dòng, KHÔNG emoji, KHÔNG markdown)

[Món] | [Quán + địa chỉ] | [Giá khoảng XX.000 đồng/người] | [Cách khoảng X,X km]

KHÔNG thêm link. KHÔNG thêm dòng nào khác. Chỉ văn bản thuần.
Toàn bộ nội dung trả lời phải dùng tiếng Việt có dấu đầy đủ. Tuyệt đối không trả lời quá 1 dòng."""
    else:
        format_section = f"""## Định dạng trả lời (BẮT BUỘC theo đúng định dạng này, chỉ 2 dòng, KHÔNG emoji, KHÔNG markdown)

Dòng 1: [Món] | [Quán + địa chỉ] | [Giá khoảng XX.000 đồng/người] | [Cách khoảng X,X km]
Dòng 2: [liên kết Google Maps chỉ đường]

Liên kết Google Maps dùng định dạng sau (KHÔNG ngắt dòng, một dòng duy nhất):
https://www.google.com/maps/dir/?api=1&origin={maps_origin}&destination=TÊN+QUÁN+ĐỊA+CHỈ+QUÁN&travelmode=walking
(thay TÊN+QUÁN+ĐỊA+CHỈ+QUÁN bằng tên và địa chỉ quán, dùng dấu + thay khoảng trắng)
Nếu quán cách hơn 1 km thì dùng travelmode=two-wheeler thay cho walking (ưu tiên đi bộ khi gần).

KHÔNG dùng emoji. KHÔNG dùng markdown. KHÔNG dùng dấu ** hay #. Chỉ văn bản thuần.
Toàn bộ nội dung trả lời phải dùng tiếng Việt có dấu đầy đủ. Tuyệt đối không trả lời quá 2 dòng."""

    return f"""Bạn là một chuyên gia ẩm thực địa phương tại Việt Nam. Hãy gợi ý cho tôi hôm nay ăn gì.

## Thông tin hiện tại
- Địa chỉ của tôi: {address}
- Tọa độ: {latitude}, {longitude}
- Thời tiết: {weather.description}, {weather.temp_c}°C (cảm giác {weather.feels_like_c}°C), độ ẩm {weather.humidity}%, gió {weather.wind_speed} m/s
- Bữa ăn: {meal_period}
- Số người: 5–6 người
- Ngân sách: khoảng 50.000 VND/người
- Bán kính tìm kiếm: {radius_km} km
{history_section}{places_section}
## Yêu cầu
- Chỉ gợi ý đúng một món ăn duy nhất phù hợp với thời tiết hiện tại
{constraint}{delivery_extra}- Quán phải phù hợp cho nhóm 5–6 người, giá khoảng 50.000 VND/người (bình dân, quán ăn đường phố hoặc quán cơm bình dân)
- Giải thích ngắn gọn tại sao món này hợp với thời tiết hôm nay (một câu)

{format_section}"""


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
    nearby_places: list[Place] | None = None,
    platform: str = "dine_in",
) -> SuggestionResult:
    prompt = build_prompt(
        weather=weather,
        address=address,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        meal_period=meal_period,
        past_suggestions=past_suggestions,
        nearby_places=nearby_places,
        platform=platform,
    )

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )

    text = response.text or ""
    matched = match_place(text, nearby_places or [])
    return SuggestionResult(text=text, matched_place=matched)
