from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Config:
    telegram_token: str
    gemini_api_key: str
    geoapify_api_key: str | None
    address: str
    latitude: float
    longitude: float
    search_radius_km: int


_REQUIRED = [
    "TELEGRAM_BOT_TOKEN",
    "GEMINI_API_KEY",
    "MY_ADDRESS",
    "MY_LATITUDE",
    "MY_LONGITUDE",
]


def load_config() -> Config:
    load_dotenv(override=False)

    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    radius = int(os.environ.get("SEARCH_RADIUS_KM", "2"))
    radius = max(1, min(3, radius))

    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        geoapify_api_key=os.environ.get("GEOAPIFY_API_KEY") or None,
        address=os.environ["MY_ADDRESS"],
        latitude=float(os.environ["MY_LATITUDE"]),
        longitude=float(os.environ["MY_LONGITUDE"]),
        search_radius_km=radius,
    )
