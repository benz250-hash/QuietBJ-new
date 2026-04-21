from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


CACHE_FILE = Path("community_building_cache.json")

# 你刚刚确认要“稍微大一点”的遮挡权重
ROAD_SHIELDING_FACTOR = {
    "none": 1.00,
    "partial": 0.72,
    "strong": 0.50,
}

LOCAL_SHIELDING_FACTOR = {
    "none": 1.00,
    "partial": 0.82,
    "strong": 0.62,
}


def _norm_text(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch not in " \t\r\n-—_·•,，。/｜|（）()【】[]{}<>:：")


def load_building_cache(path: str | Path = CACHE_FILE) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_building_cache(data: dict[str, Any], path: str | Path = CACHE_FILE) -> None:
    file_path = Path(path)
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_cached_buildings(cache: dict[str, Any], community_name: str) -> list[dict[str, Any]]:
    target = _norm_text(community_name)
    if not target:
        return []
    for key, value in cache.items():
        if _norm_text(key) == target:
            return list(value.get("buildings", []))
    return []


def upsert_community_buildings(
    cache: dict[str, Any],
    community_name: str,
    buildings: list[dict[str, Any]],
    source: str = "amap_poi_search",
    updated_at: str = "",
) -> dict[str, Any]:
    cache = dict(cache)
    cache[community_name] = {
        "source": source,
        "updated_at": updated_at,
        "buildings": buildings,
    }
    return cache


def _to_point(item: dict[str, Any]) -> tuple[float, float] | None:
    try:
        lon = float(item["lon"])
        lat = float(item["lat"])
        return lon, lat
    except Exception:
        return None


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _norm2(a: tuple[float, float]) -> float:
    return a[0] * a[0] + a[1] * a[1]


def _meters_per_degree(lat: float) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def _to_local_xy(point: tuple[float, float], origin: tuple[float, float]) -> tuple[float, float]:
    m_lon, m_lat = _meters_per_degree(origin[1])
    dx = (point[0] - origin[0]) * m_lon
    dy = (point[1] - origin[1]) * m_lat
    return dx, dy


def _distance_point_to_segment_m(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    origin = a
    px, py = _to_local_xy(p, origin)
    ax, ay = 0.0, 0.0
    bx, by = _to_local_xy(b, origin)

    ab = (bx - ax, by - ay)
    ap = (px - ax, py - ay)
    ab2 = _norm2(ab)
    if ab2 == 0:
        return math.hypot(px - ax, py - ay)

    t = max(0.0, min(1.0, _dot(ap, ab) / ab2))
    cx = ax + t * ab[0]
    cy = ay + t * ab[1]
    return math.hypot(px - cx, py - cy)


def _is_between_target_and_road(
    blocker: tuple[float, float],
    target: tuple[float, float],
    road: tuple[float, float],
) -> bool:
    origin = target
    bx, by = _to_local_xy(blocker, origin)
    rx, ry = _to_local_xy(road, origin)
    br = bx * rx + by * ry
    rr = rx * rx + ry * ry
    return br > 0 and br < rr


def infer_shielding(
    target_point: tuple[float, float],
    road_point: tuple[float, float],
    building_points: list[dict[str, Any]],
    target_building_token: str = "",
    corridor_width_m: float = 20.0,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    target_token_norm = _norm_text(target_building_token)

    for item in building_points:
        point = _to_point(item)
        if point is None:
            continue

        token = str(item.get("building_token", "")).strip()
        token_norm = _norm_text(token)
        if target_token_norm and token_norm == target_token_norm:
            continue

        if not _is_between_target_and_road(point, target_point, road_point):
            continue

        offset_m = _distance_point_to_segment_m(point, target_point, road_point)
        if offset_m > corridor_width_m:
            continue

        blockers.append(
            {
                "name": str(item.get("name", "")).strip(),
                "building_token": token,
                "offset_m": round(offset_m, 1),
            }
        )

    blocker_count = len(blockers)
    if blocker_count == 0:
        shielding_level = "none"
    elif blocker_count == 1:
        shielding_level = "partial"
    else:
        shielding_level = "strong"

    return {
        "shielding_level": shielding_level,
        "blocker_count": blocker_count,
        "blocker_names": [x["name"] for x in blockers[:3]],
        "blockers": blockers[:5],
        "corridor_width_m": corridor_width_m,
    }


def apply_shielding_to_road_impact(
    raw_impact: int,
    shielding_level: str,
    road_kind: str = "arterial",
) -> dict[str, Any]:
    level = str(shielding_level or "none").strip().lower()
    if road_kind in {"local", "internal"}:
        factor = LOCAL_SHIELDING_FACTOR.get(level, 1.0)
    else:
        factor = ROAD_SHIELDING_FACTOR.get(level, 1.0)

    adjusted = max(1, round(int(raw_impact) * factor)) if int(raw_impact) > 0 else 0
    return {
        "raw_impact": int(raw_impact),
        "shielding_level": level,
        "factor": factor,
        "adjusted_impact": adjusted,
    }
