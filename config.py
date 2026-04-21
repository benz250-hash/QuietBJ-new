from __future__ import annotations

import os
from pathlib import Path
from typing import Any

BACKGROUND_FILE = Path("background.jpg")
COMMUNITIES_FILE = Path("communities.csv")
COMMUNITY_ZONES_FILE = Path("community_zones.csv")

DEFAULT_BASE_SCORE = 85
AMAP_CITY = "北京市"
TIMEOUT_SECONDS = 8


def _read_secret(secrets: Any = None, name: str = "") -> str:
    if not name:
        return ""
    try:
        if secrets is not None:
            value = str(secrets.get(name, "")).strip()
            if value:
                return value
    except Exception:
        pass
    return os.getenv(name, "").strip()


def get_amap_api_key(secrets: Any = None) -> str:
    return _read_secret(secrets, "AMAP_API_KEY")


def get_amap_js_api_key(secrets: Any = None) -> str:
    value = _read_secret(secrets, "AMAP_JS_API_KEY")
    if value:
        return value
    return _read_secret(secrets, "AMAP_API_KEY")


def get_amap_js_security_code(secrets: Any = None) -> str:
    return _read_secret(secrets, "AMAP_JS_SECURITY_CODE")
