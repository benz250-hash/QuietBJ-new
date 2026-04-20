from __future__ import annotations

from typing import Any

import requests

from config import AMAP_CITY, TIMEOUT_SECONDS


class AMapProvider:
    GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
    REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
    INPUT_TIPS_URL = "https://restapi.amap.com/v3/assistant/inputtips"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def enabled(self) -> bool:
        return bool(self.api_key)

    def input_tips(self, keywords: str, city: str = AMAP_CITY) -> list[dict[str, Any]]:
        if not self.enabled() or not keywords.strip():
            return []
        params = {
            "key": self.api_key,
            "keywords": keywords.strip(),
            "city": city,
            "citylimit": "true",
            "datatype": "all",
            "output": "JSON",
        }
        try:
            response = requests.get(self.INPUT_TIPS_URL, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        tips = payload.get("tips", []) if str(payload.get("status")) == "1" else []
        return [tip for tip in tips if str(tip.get("name", "")).strip()]

    def geocode(self, address: str, city: str = AMAP_CITY) -> dict[str, Any] | None:
        if not self.enabled() or not address.strip():
            return None
        params = {
            "key": self.api_key,
            "address": address.strip(),
            "city": city,
            "output": "JSON",
        }
        try:
            response = requests.get(self.GEOCODE_URL, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        if str(payload.get("status")) != "1":
            return None
        items = payload.get("geocodes", [])
        return items[0] if items else None

    def reverse_geocode(self, location: str) -> dict[str, Any] | None:
        if not self.enabled() or not location.strip():
            return None
        params = {
            "key": self.api_key,
            "location": location.strip(),
            "extensions": "all",
            "roadlevel": "1",
            "output": "JSON",
        }
        try:
            response = requests.get(self.REGEO_URL, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        if str(payload.get("status")) != "1":
            return None
        return payload.get("regeocode")
