from __future__ import annotations

from dataclasses import dataclass

import httpx

_BASE_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class WeatherInfo:
    condition: str
    description: str
    temp_c: float
    feels_like_c: float
    humidity: int
    wind_speed: float
    city: str


async def fetch_weather(
    *, lat: float, lon: float
) -> WeatherInfo:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_BASE_URL, params=params)

    if resp.status_code != 200:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        msg = body.get("reason", "unknown") if isinstance(body, dict) else "unknown"
        raise RuntimeError(f"Weather API error {resp.status_code}: {msg}")

    data = resp.json()
    current = data["current"]
    code = int(current.get("weather_code", -1))
    if code in {0}:
        condition, description = "Clear", "trời quang"
    elif code in {1, 2, 3}:
        condition, description = "Clouds", "nhiều mây"
    elif code in {45, 48}:
        condition, description = "Fog", "sương mù"
    elif code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        condition, description = "Rain", "mưa"
    elif code in {71, 73, 75, 77, 85, 86}:
        condition, description = "Snow", "tuyết"
    elif code in {95, 96, 99}:
        condition, description = "Thunderstorm", "dông"
    else:
        condition, description = "Unknown", "không xác định"

    return WeatherInfo(
        condition=condition,
        description=description,
        temp_c=float(current["temperature_2m"]),
        feels_like_c=float(current["apparent_temperature"]),
        humidity=int(current["relative_humidity_2m"]),
        wind_speed=float(current["wind_speed_10m"]),
        city=f"{lat},{lon}",
    )
