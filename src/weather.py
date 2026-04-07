from __future__ import annotations

from dataclasses import dataclass

import httpx

_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


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
    *, api_key: str, lat: float, lon: float
) -> WeatherInfo:
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": "vi",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_BASE_URL, params=params)

    if resp.status_code != 200:
        body = resp.json() if resp.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}
        msg = body.get("message", "unknown") if isinstance(body, dict) else "unknown"
        raise RuntimeError(f"Weather API error {resp.status_code}: {msg}")

    data = resp.json()
    return WeatherInfo(
        condition=data["weather"][0]["main"],
        description=data["weather"][0]["description"],
        temp_c=data["main"]["temp"],
        feels_like_c=data["main"]["feels_like"],
        humidity=data["main"]["humidity"],
        wind_speed=data["wind"]["speed"],
        city=data["name"],
    )
