"""Fetch real nearby food places from the Geoapify Places API.

This module provides verified restaurant/street-food data that is used
to ground Gemini suggestions — preventing the AI from hallucinating
place names that do not exist on Google Maps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_PLACES_URL = "https://api.geoapify.com/v2/places"

# Only search for actual dining establishments, not raw-food shops or stores.
_RESTAURANT_CATEGORIES = (
    "catering.restaurant,"
    "catering.fast_food,"
    "catering.food_court,"
    "catering.cafe"
)

# Vietnamese keywords that indicate a place is NOT a restaurant.
# "Cửa hàng gà tươi" is a raw-chicken shop, not a place to eat.
_EXCLUDE_KEYWORDS = (
    "cửa hàng",
    "đại lý",
    "tươi sống",
    "gà tươi",
    "thịt tươi",
    "hải sản tươi",
    "nguyên liệu",
    "bán sỉ",
    "bán lẻ",
    "siêu thị",
    "minimart",
    "tạp hóa",
    "shop",
    "store",
)


@dataclass(frozen=True)
class Place:
    """A verified food place from the Geoapify database."""

    name: str
    address: str
    lat: float
    lon: float
    categories: tuple[str, ...] = ()
    distance_m: int = 0


def _is_restaurant(name: str) -> bool:
    """Return False for places that sell raw ingredients, not cooked food."""
    name_lower = name.lower()
    return not any(kw in name_lower for kw in _EXCLUDE_KEYWORDS)


async def fetch_nearby_places(
    *,
    api_key: str,
    lat: float,
    lon: float,
    radius_km: int,
    limit: int = 40,
) -> list[Place]:
    """Fetch real food / restaurant places near *lat*, *lon*.

    Uses the Geoapify Places API with specific restaurant categories
    (``restaurant``, ``fast_food``, ``food_court``, ``cafe``) to avoid
    returning raw-food stores or non-dining businesses.
    """

    params = {
        "categories": _RESTAURANT_CATEGORIES,
        "filter": f"circle:{lon},{lat},{radius_km * 1000}",
        "bias": f"proximity:{lon},{lat}",
        "limit": limit,
        "lang": "vi",
        "apiKey": api_key,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_PLACES_URL, params=params)

    if resp.status_code != 200:
        logger.warning("Geoapify Places API returned %s", resp.status_code)
        return []

    features = resp.json().get("features", [])
    places: list[Place] = []

    for feat in features:
        props = feat.get("properties", {})
        name = props.get("name")
        if not name:
            continue

        # Skip non-restaurant businesses (raw-food shops, stores, etc.)
        if not _is_restaurant(name):
            logger.debug("Skipping non-restaurant: %s", name)
            continue

        # Build a readable Vietnamese-style address
        parts: list[str] = []
        house = props.get("housenumber", "")
        street = props.get("street", "")
        if street:
            parts.append(f"{house} {street}".strip())
        if props.get("suburb"):
            parts.append(props["suburb"])
        if props.get("district"):
            parts.append(props["district"])
        if props.get("city"):
            parts.append(props["city"])
        address = ", ".join(parts) if parts else props.get("formatted", "")

        try:
            coords = feat["geometry"]["coordinates"]
            p_lon, p_lat = float(coords[0]), float(coords[1])
        except (KeyError, ValueError, TypeError, IndexError):
            continue

        places.append(
            Place(
                name=name,
                address=address,
                lat=p_lat,
                lon=p_lon,
                categories=tuple(props.get("categories", [])),
                distance_m=int(props.get("distance", 0)),
            )
        )

    return places
