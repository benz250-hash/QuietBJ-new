from __future__ import annotations

import base64
import json
import csv
import re
from pathlib import Path
from typing import Any

import streamlit as st

from amap_provider import AMapProvider
from community_repository import CommunityRepository
from config import BACKGROUND_FILE, COMMUNITIES_FILE, COMMUNITY_ZONES_FILE, DEFAULT_BASE_SCORE, get_amap_api_key
from noise_point_engine import NoisePointEngine
from score_engine import ScoreEngine
from shielding_engine import apply_shielding_to_road_impact, get_cached_buildings, infer_shielding, load_building_cache, save_building_cache, upsert_building_point
from text_match import strip_unit_details
from zone_repository import ZoneRepository

st.set_page_config(page_title="QuietBJ｜安宁北京", page_icon="🔇", layout="wide")

BUILDING_OVERRIDES_FILE = Path("building_overrides.csv")
COMMUNITY_BUILDING_CACHE_FILE = Path("community_building_cache.json")

# ---------- shared helpers ----------
def file_to_base64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def label_score(score: int) -> str:
    if score >= 90:
        return "安静度较高"
    if score >= 80:
        return "安静度良好"
    if score >= 70:
        return "环境较稳定"
    if score >= 60:
        return "略受外部环境影响"
    return "外部环境影响较明显"


def build_summary_line(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "当前没有识别到足够强的外部环境影响线索，整体更接近中性楼栋。"
    ordered = sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True)
    labels = [str(item.get("label", "")).strip() for item in ordered[:2] if str(item.get("label", "")).strip()]
    if len(labels) == 1:
        return f"该楼栋当前主要受{labels[0]}影响。"
    return f"该楼栋当前主要受{labels[0]}与{labels[1]}影响。"


def _to_int_distance(value: Any) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def score_signal_by_label(score_engine: ScoreEngine, label: str, distance_m: Any) -> int:
    distance = _to_int_distance(distance_m)
    if distance is None:
        return 0
    text = str(label or "").strip()
    cfg = score_engine.cfg
    if "高速" in text or "快速路" in text:
        return score_engine.band_score(distance, cfg.expressway_bands)
    if "主干路" in text:
        return score_engine.band_score(distance, cfg.arterial_bands)
    if "次干路" in text:
        return score_engine.band_score(distance, cfg.secondary_bands)
    if "小区内部路" in text or "内部路" in text:
        return score_engine.band_score(distance, cfg.internal_bands)
    if "小路" in text or "支路" in text:
        return score_engine.band_score(distance, cfg.local_bands)
    if "轨道" in text or "地铁" in text:
        return score_engine.band_score(distance, cfg.rail_bands)
    if "学校" in text:
        return score_engine.band_score(distance, cfg.school_bands)
    if "医院" in text:
        return score_engine.band_score(distance, cfg.hospital_bands)
    if "餐饮" in text:
        return score_engine.band_score(distance, cfg.restaurant_bands)
    if "商业" in text or "底商" in text or "商场" in text or "超市" in text or "便利店" in text:
        return score_engine.band_score(distance, cfg.commercial_bands)
    return int(distance <= 80)


def refine_noise_summary(noise_summary: dict[str, Any], score_engine: ScoreEngine) -> dict[str, Any]:
    signals = list(noise_summary.get("signals", []) or [])
    refined: list[dict[str, Any]] = []
    for sig in signals:
        row = dict(sig)
        row["penalty"] = score_signal_by_label(score_engine, row.get("label", ""), row.get("distance_m", ""))
        refined.append(row)

    # local/internal synthetic cap if those labels exist
    local_total = sum(
        int(item.get("penalty", 0))
        for item in refined
        if any(x in str(item.get("label", "")) for x in ["小路", "支路", "内部路", "小区内部路"])
    )
    if local_total > 4:
        overflow = local_total - 4
        for item in reversed(refined):
            if overflow <= 0:
                break
            if any(x in str(item.get("label", "")) for x in ["小路", "支路", "内部路", "小区内部路"]):
                current = int(item.get("penalty", 0))
                if current <= 0:
                    continue
                reduce_by = min(current, overflow)
                item["penalty"] = current - reduce_by
                overflow -= reduce_by

    total_penalty = sum(int(item.get("penalty", 0)) for item in refined)
    return {"signals": refined, "total_penalty": total_penalty}


def _distance_between_gcj_points_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    # 用近似平面距离即可，当前只用于同小区量级的相对匹配
    import math
    lat = (a[1] + b[1]) / 2
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    dx = (a[0] - b[0]) * m_per_deg_lon
    dy = (a[1] - b[1]) * m_per_deg_lat
    return math.hypot(dx, dy)


def road_kind_from_label(label: str) -> str:
    text = str(label or "").strip()
    if "高速" in text or "快速路" in text:
        return "expressway"
    if "主干路" in text:
        return "arterial"
    if "次干路" in text:
        return "secondary"
    if "小区内部路" in text or "内部路" in text:
        return "internal"
    if "小路" in text or "支路" in text:
        return "local"
    return ""


def choose_road_point_for_signal(
    target_point: tuple[float, float],
    signal_distance_m: Any,
    regeo: dict[str, Any] | None,
) -> tuple[float, float] | None:
    roads = list((regeo or {}).get("roads", []) or [])
    candidates: list[tuple[float, tuple[float, float]]] = []
    distance_hint = _to_int_distance(signal_distance_m)
    for road in roads:
        parsed = parse_location_text(str(road.get("location", "")).strip())
        if not parsed:
            continue
        actual = _distance_between_gcj_points_m(target_point, parsed)
        if distance_hint is None:
            gap = actual
        else:
            gap = abs(actual - distance_hint)
        candidates.append((gap, parsed))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def apply_road_shielding(
    noise_summary: dict[str, Any],
    community_row: dict[str, Any],
    building_location_text: str,
    regeo: dict[str, Any] | None,
    cache_path: str | Path = COMMUNITY_BUILDING_CACHE_FILE,
) -> dict[str, Any]:
    target_point = parse_location_text(building_location_text)
    detail_token = str(community_row.get("_detail_token", "")).strip()
    community_name = str(community_row.get("community_name", "")).strip()
    if not target_point or not detail_token or not community_name:
        return noise_summary

    cache = load_building_cache(cache_path)
    building_points = get_cached_buildings(cache, community_name)
    if not building_points:
        return noise_summary

    refined: list[dict[str, Any]] = []
    changed = False
    for sig in list(noise_summary.get("signals", []) or []):
        row = dict(sig)
        kind = road_kind_from_label(row.get("label", ""))
        if not kind:
            refined.append(row)
            continue

        road_point = choose_road_point_for_signal(target_point, row.get("distance_m", ""), regeo)
        if not road_point:
            refined.append(row)
            continue

        shielding = infer_shielding(
            target_point=target_point,
            road_point=road_point,
            building_points=building_points,
            target_building_token=detail_token,
            corridor_width_m=20.0,
        )
        adjusted = apply_shielding_to_road_impact(
            raw_impact=int(row.get("penalty", 0)),
            shielding_level=shielding["shielding_level"],
            road_kind=kind,
        )
        row["raw_penalty"] = adjusted["raw_impact"]
        row["penalty"] = adjusted["adjusted_impact"]
        row["shielding_level"] = adjusted["shielding_level"]
        row["shielding_factor"] = adjusted["factor"]
        row["blocker_count"] = shielding["blocker_count"]
        row["blocker_names"] = shielding["blocker_names"]
        if adjusted["adjusted_impact"] != adjusted["raw_impact"]:
            changed = True
        refined.append(row)

    total_penalty = sum(int(item.get("penalty", 0)) for item in refined)
    result = dict(noise_summary)
    result["signals"] = refined
    result["total_penalty"] = total_penalty
    result["shielding_applied"] = changed
    return result


def load_building_overrides(path: str | Path = BUILDING_OVERRIDES_FILE) -> dict[tuple[str, str], dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    rows: dict[tuple[str, str], dict[str, str]] = {}
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                community_name = normalize_match_text(str(row.get("community_name", "")).strip())
                building_token = normalize_match_text(str(row.get("building_token", "")).strip())
                if not community_name or not building_token:
                    continue
                rows[(community_name, building_token)] = {
                    "zone_type": str(row.get("zone_type", "")).strip(),
                    "locator_confidence_override": str(row.get("locator_confidence_override", "")).strip(),
                    "notes": str(row.get("notes", "")).strip(),
                }
    except Exception:
        return {}
    return rows


def apply_building_override(community_row: dict[str, Any], query: str, overrides: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    detail_token = str(community_row.get("_detail_token", "")).strip() or extract_building_token(query)
    if not detail_token:
        return community_row
    community_keys = [
        normalize_match_text(str(community_row.get("community_name", "")).strip()),
        normalize_match_text(str(community_row.get("_query_used", "")).strip()),
        normalize_match_text(strip_unit_details(query)),
    ]
    building_key = normalize_match_text(detail_token)
    hit = None
    for key in community_keys:
        if not key:
            continue
        candidate = overrides.get((key, building_key))
        if candidate:
            hit = candidate
            break
    if not hit:
        return community_row

    row = dict(community_row)
    row["_override_zone_type"] = str(hit.get("zone_type", "")).strip()
    row["_override_notes"] = str(hit.get("notes", "")).strip()
    row["_locator_confidence"] = (
        {"high": "高", "medium": "中", "low": "低"}.get(
            str(hit.get("locator_confidence_override", "")).strip().lower(),
            row.get("_locator_confidence", ""),
        )
        or row.get("_locator_confidence", "")
    )
    row["_locator_mode"] = "人工校正"
    note = row["_override_notes"] or f"当前已命中人工校正规则，按 {row['_override_zone_type']} 处理。"
    row["_locator_note"] = note
    map_labels = {
        "street_front": "目标楼栋（人工校正）",
        "edge_building": "目标楼栋（人工校正）",
        "central": "目标楼栋（人工校正）",
        "quiet_inner": "目标楼栋（人工校正）",
        "compound_approx": "园区级近似点（人工校正）",
    }
    row["_map_label"] = map_labels.get(row["_override_zone_type"], row.get("_map_label", "目标楼栋"))
    return row


def update_building_cache_for_current_result(
    community_row: dict[str, Any],
    building_location_text: str,
    cache_path: str | Path = COMMUNITY_BUILDING_CACHE_FILE,
) -> None:
    detail_token = str(community_row.get("_detail_token", "")).strip()
    community_name = str(community_row.get("community_name", "")).strip()
    point = parse_location_text(building_location_text)
    if not detail_token or not community_name or not point:
        return

    cache = load_building_cache(cache_path)
    display_name = str(community_row.get("_display_name", "")).strip() or f"{community_name}{detail_token}"
    building = {
        "name": display_name,
        "building_token": detail_token,
        "lon": point[0],
        "lat": point[1],
    }
    cache = upsert_building_point(
        cache=cache,
        community_name=community_name,
        building=building,
        source="query_trace",
    )
    save_building_cache(cache, cache_path)


def normalize_match_text(value: str) -> str:
    return re.sub(r"[\s\-—_·•,，。/｜|（）()【】\[\]{}<>:：]+", "", str(value or "").strip().lower())


def extract_building_token(value: str) -> str:
    text = str(value or "").strip()
    patterns = [
        r"\d+号楼",
        r"\d+号院",
        r"\d+栋",
        r"\d+座",
        r"[A-Za-z]座",
        r"[A-Za-z]栋",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def candidate_text_from_tip(tip: dict[str, Any]) -> str:
    return " ".join(
        [
            str(tip.get("name", "")).strip(),
            str(tip.get("district", "")).strip(),
            str(tip.get("address", "")).strip(),
        ]
    ).strip()


def build_locator_meta(
    query: str,
    cleaned_query: str,
    tips: list[dict[str, Any]],
    geocode_used: dict[str, Any] | None,
    building_location_text: str,
) -> dict[str, Any]:
    detail_token = extract_building_token(query)
    detail_norm = normalize_match_text(detail_token)
    cleaned_norm = normalize_match_text(cleaned_query or query)

    geocode_candidates = []
    if geocode_used:
        geocode_candidates.extend(
            [
                str(geocode_used.get("formatted_address", "")).strip(),
                str(geocode_used.get("district", "")).strip(),
                str(geocode_used.get("name", "")).strip(),
            ]
        )
    tip_candidates = [candidate_text_from_tip(tip) for tip in tips[:8]]
    all_candidates = [x for x in geocode_candidates + tip_candidates if str(x).strip()]
    all_norm = [normalize_match_text(x) for x in all_candidates]

    detail_hit = bool(detail_norm) and any(detail_norm in item for item in all_norm)
    community_hit = bool(cleaned_norm) and any(cleaned_norm in item for item in all_norm)
    building_like_tip = any(extract_building_token(candidate_text_from_tip(tip)) for tip in tips[:8])

    if detail_token and detail_hit and building_location_text:
        return {
            "confidence": "高",
            "mode": "楼栋级定位",
            "note": f"高德候选中保留了“{detail_token}”这类楼号信息，本次按楼栋级结果展示。",
            "display_name": query,
            "map_label": "目标楼栋（楼栋定位）",
        }

    if detail_token and building_like_tip and community_hit and building_location_text:
        return {
            "confidence": "中",
            "mode": "楼栋近似定位",
            "note": f"当前拿到的是同园区内的建筑级候选，但未稳定命中“{detail_token}”，本次按近似楼栋位置估算。",
            "display_name": f"{cleaned_query or query}（楼栋近似）",
            "map_label": "目标楼栋（近似定位）",
        }

    if detail_token and (community_hit or building_location_text):
        return {
            "confidence": "低",
            "mode": "园区级近似定位",
            "note": f"当前未稳定命中“{detail_token}”，只识别到园区/小区级主 POI，本次按园区级位置估算。",
            "display_name": cleaned_query or query,
            "map_label": "园区级近似点",
        }

    if building_location_text:
        return {
            "confidence": "中",
            "mode": "小区级定位",
            "note": "当前未输入明确楼号，系统按小区/园区级位置估算。",
            "display_name": cleaned_query or query,
            "map_label": "目标位置",
        }

    return {
        "confidence": "低",
        "mode": "未稳定定位",
        "note": "当前没有拿到稳定的楼栋或园区定位结果，请尽量补充更完整的地址。",
        "display_name": cleaned_query or query,
        "map_label": "目标位置",
    }

# ---------- coordinate helpers ----------
PI = 3.1415926535897932384626
A = 6378245.0
EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * abs(lng) ** 0.5
    ret += (20.0 * __import__("math").sin(6.0 * lng * PI) + 20.0 * __import__("math").sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * __import__("math").sin(lat * PI) + 40.0 * __import__("math").sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * __import__("math").sin(lat / 12.0 * PI) + 320.0 * __import__("math").sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * abs(lng) ** 0.5
    ret += (20.0 * __import__("math").sin(6.0 * lng * PI) + 20.0 * __import__("math").sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * __import__("math").sin(lng * PI) + 40.0 * __import__("math").sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * __import__("math").sin(lng / 12.0 * PI) + 300.0 * __import__("math").sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    if _out_of_china(lng, lat):
        return lng, lat
    math = __import__("math")
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    mglat = lat + dlat
    mglng = lng + dlng
    return lng * 2 - mglng, lat * 2 - mglat


def parse_location_text(location_text: str) -> tuple[float, float] | None:
    raw = str(location_text or "").strip()
    if not raw or "," not in raw:
        return None
    try:
        lng_text, lat_text = raw.split(",", 1)
        return float(lng_text), float(lat_text)
    except Exception:
        return None


def gcj_location_text_to_wgs(location_text: str) -> tuple[float, float] | None:
    parsed = parse_location_text(location_text)
    if not parsed:
        return None
    lng, lat = parsed
    return gcj02_to_wgs84(lng, lat)


def build_light_map_sources(
    regeo: dict[str, Any] | None,
    poi_results: dict[str, list[dict[str, Any]]],
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signal_labels = [str(item.get("label", "")).strip() for item in signals]
    rows: list[dict[str, Any]] = []

    roads = list((regeo or {}).get("roads", []) or [])
    if roads:
        road = roads[0]
        parsed = gcj_location_text_to_wgs(str(road.get("location", "")).strip())
        if parsed:
            lng, lat = parsed
            name = str(road.get("name", "")).strip() or "最近道路"
            rows.append({
                "lon": lng, "lat": lat, "name": name, "category": "道路",
                "radius": 72, "fill_r": 216, "fill_g": 91, "fill_b": 66
            })

    category_order = []
    if any("轨道" in x for x in signal_labels):
        category_order.append(("rail", "轨道"))
    if any("学校" in x for x in signal_labels):
        category_order.append(("school", "学校"))
    if any("医院" in x for x in signal_labels):
        category_order.append(("hospital", "医院"))
    if any("商业" in x or "底商" in x for x in signal_labels):
        category_order.append(("commercial", "商业"))
    if any("餐饮" in x for x in signal_labels):
        category_order.append(("restaurant", "餐饮"))

    # Fallback ordering if signals didn't mention enough categories
    for item in [("rail", "轨道"), ("school", "学校"), ("hospital", "医院"), ("commercial", "商业"), ("restaurant", "餐饮")]:
        if item not in category_order:
            category_order.append(item)

    color_map = {
        "轨道": (94, 115, 208),
        "学校": (89, 176, 148),
        "医院": (145, 118, 188),
        "商业": (226, 178, 75),
        "餐饮": (215, 145, 96),
    }

    for key, label in category_order:
        items = list(poi_results.get(key, []) or [])
        if not items:
            continue
        parsed = gcj_location_text_to_wgs(str(items[0].get("location", "")).strip())
        if not parsed:
            continue
        lng, lat = parsed
        r, g, b = color_map[label]
        rows.append({
            "lon": lng, "lat": lat, "name": str(items[0].get("name", "")).strip() or label, "category": label,
            "radius": 58, "fill_r": r, "fill_g": g, "fill_b": b
        })
        if len(rows) >= 4:
            break
    return rows


def render_open_map_card(building_location_text: str, geocode_used: dict[str, Any] | None, regeo: dict[str, Any] | None, poi_results: dict[str, list[dict[str, Any]]], signals: list[dict[str, Any]], community_row: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown('<div class="card-title">环境地图</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">保留高德取数，但展示层回到更稳的 opensource 底图。地图上的目标楼栋点已做 GCJ-02 → WGS84 坐标转换，避免整体错位。</div>', unsafe_allow_html=True)

        center = gcj_location_text_to_wgs(building_location_text)
        if not center:
            st.info("当前没有拿到可用的楼栋坐标，地图暂时无法显示。")
            return

        try:
            import pydeck as pdk
        except Exception:
            st.info("当前运行环境没有可用的地图渲染组件。")
            return

        lon, lat = center
        address_text = str((geocode_used or {}).get("formatted_address", "")).strip() or "—"

        map_label = str(community_row.get("_map_label", "目标楼栋（近似定位）")).strip() or "目标楼栋（近似定位）"
        building_row = [{
            "lon": lon,
            "lat": lat,
            "name": map_label,
            "address": address_text,
        }]
        source_rows = build_light_map_sources(regeo, poi_results, signals)

        st.markdown(
            '<div class="pill-row" style="margin-top:0;margin-bottom:12px;">'
            '<span class="pill">目标楼栋</span>'
            '<span class="pill">最近道路</span>'
            '<span class="pill">最近 3 个主要影响源</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="subtle" style="margin-bottom:10px;">地图定位点：{address_text}。{community_row.get("_locator_note", "当前按楼栋近似位置估算。")} 不代表建筑几何中心。</div>',
            unsafe_allow_html=True,
        )

        layers = [
            pdk.Layer(
                "ScatterplotLayer",
                data=source_rows,
                get_position='[lon, lat]',
                get_fill_color='[fill_r, fill_g, fill_b, 190]',
                get_radius='radius',
                pickable=True,
                stroked=True,
                get_line_color='[255,255,255,220]',
                line_width_min_pixels=2,
            ),
            pdk.Layer(
                "TextLayer",
                data=source_rows,
                get_position='[lon, lat]',
                get_text='category',
                get_color='[54, 66, 60]',
                get_size=12,
                get_alignment_baseline='"top"',
                get_pixel_offset='[0, 14]',
            ),
            pdk.Layer(
                "ScatterplotLayer",
                data=building_row,
                get_position='[lon, lat]',
                get_fill_color='[18, 39, 31, 255]',
                get_radius=92,
                pickable=True,
                stroked=True,
                get_line_color='[255,255,255,255]',
                line_width_min_pixels=3,
            ),
            pdk.Layer(
                "TextLayer",
                data=building_row,
                get_position='[lon, lat]',
                get_text='name',
                get_color='[18, 39, 31]',
                get_size=14,
                get_alignment_baseline='"top"',
                get_pixel_offset='[0, 18]',
            ),
        ]

        tooltip = {
            "html": "<b>{name}</b><br/>{category}",
            "style": {
                "backgroundColor": "#16241e",
                "color": "white",
                "fontSize": "12px",
            },
        }

        deck = pdk.Deck(
            map_provider="carto",
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=15.2, pitch=0),
            layers=layers,
            tooltip=tooltip,
        )
        st.pydeck_chart(deck, use_container_width=True)


def parse_geocode_result(query: str, community_repo: CommunityRepository, amap: AMapProvider) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, str, dict[str, Any] | None]:
    cleaned_query = strip_unit_details(query)
    tips = amap.input_tips(query) if amap.enabled() else []
    district_hint = str(tips[0].get("district", "")).strip() if tips else ""
    community_match = community_repo.search(cleaned_query, district=district_hint)
    geocode_full = amap.geocode(query) if amap.enabled() else None
    geocode_clean = amap.geocode(cleaned_query) if amap.enabled() and not geocode_full else None
    geocode_used = geocode_full or geocode_clean
    building_location_text = str((geocode_used or {}).get("location", "")).strip()
    regeo = amap.reverse_geocode(building_location_text) if amap.enabled() and building_location_text else None
    locator_meta = build_locator_meta(query, cleaned_query, tips, geocode_used, building_location_text)

    if community_match:
        community_row = dict(community_match.row)
        community_row["_match_source"] = f"本地小区库 / {community_match.source}"
        community_row["_match_confidence"] = round(community_match.score, 2)
        community_row["_query_used"] = community_match.query_used
    else:
        community_row = {
            "community_code": "TEMP-DEFAULT",
            "community_name": cleaned_query or query,
            "district": district_hint or str((geocode_used or {}).get("district", "")).strip(),
            "address": str((geocode_used or {}).get("formatted_address", "")).strip(),
            "aliases": "",
            "far_ratio": "",
            "build_year": "",
            "base_score": DEFAULT_BASE_SCORE,
            "_match_source": "未匹配到本地小区样本，当前按标准基准分估算",
            "_match_confidence": "",
            "_query_used": cleaned_query,
        }

    community_row["_detail_token"] = extract_building_token(query)
    community_row["_locator_confidence"] = locator_meta["confidence"]
    community_row["_locator_mode"] = locator_meta["mode"]
    community_row["_locator_note"] = locator_meta["note"]
    community_row["_display_name"] = locator_meta["display_name"]
    community_row["_map_label"] = locator_meta["map_label"]
    return community_row, tips, regeo, building_location_text, geocode_used



def compute_position_result(zone_options: list[dict[str, Any]], community_row: dict[str, Any], score_engine: ScoreEngine, noise_penalty: int, selected_name: str) -> dict[str, Any]:
    zone_map = {str(z.get("zone_name", "")): z for z in zone_options}
    zone_row = zone_map[selected_name]
    zone_adjust = int(float(zone_row.get("adjustment_score", 0)))
    result = score_engine.final_score(
        DEFAULT_BASE_SCORE,
        zone_adjust,
        noise_penalty,
        community_row.get("far_ratio", ""),
        community_row.get("build_year", ""),
    )
    result["zone_name"] = selected_name
    result["zone_description"] = zone_row.get("description", "按当前楼栋位置调整")
    return result


# ---------- styles ----------
def render_styles(result_mode: bool) -> None:
    bg_base64 = file_to_base64(BACKGROUND_FILE)
    app_bg = "#f4f6f3" if result_mode else "transparent"
    main_bg = "#f4f6f3" if result_mode else "transparent"
    bg_layer = "" if result_mode else f'<div class="bg-layer"></div>'
    st.markdown(
        f"""
        <style>
        :root {{
            --font-display: "Songti SC", "Noto Serif SC", "Source Han Serif SC", serif;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
        }}
        html, body, [class*="css"], .stApp {{
            font-family: var(--font-sans) !important;
            color: #17211b;
        }}
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"], section.main {{
            background: {app_bg} !important;
        }}
        .block-container {{
            max-width: 1160px !important;
            padding-top: 0 !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
            padding-bottom: 4rem !important;
        }}
        [data-testid="stMainBlockContainer"] {{background: {main_bg} !important;}}
        .bg-layer {{
            position: fixed; inset: 0; z-index: -20; pointer-events: none;
            background-image: linear-gradient(180deg, rgba(8,16,13,0.22), rgba(8,16,13,0.58)), url("data:image/jpeg;base64,{bg_base64}");
            background-size: cover; background-position: center center; background-repeat: no-repeat;
        }}
        .topbar {{display:flex; justify-content:space-between; align-items:center; padding:16px 0 0; color:white;}}
        .topbar.light {{color:#14211b; padding:18px 0 12px;}}
        .brand {{font-size:14px; font-weight:600; letter-spacing:.10em; opacity:.34; font-family: var(--font-sans) !important;}}
        .hero-wrap {{min-height:46vh; display:flex; align-items:flex-start; justify-content:center; padding-top:5vh; text-align:center; color:white;}}
        .hero-kicker {{font-size:11px; letter-spacing:.24em; text-transform:uppercase; opacity:.86; margin-bottom:12px; font-family: var(--font-sans) !important;}}
        .hero-title {{font-size:clamp(42px,6vw,80px); font-weight:700; line-height:1.02; margin:0; text-shadow:0 8px 30px rgba(0,0,0,.24); font-family: var(--font-display) !important; letter-spacing:-0.02em;}}
        .hero-sub {{max-width:760px; margin:14px auto 0; font-size:16px; line-height:1.72; color:rgba(255,255,255,.96); font-family: var(--font-sans) !important;}}
        .hero-note {{display:inline-block; margin-top:16px; padding:10px 16px; border-radius:999px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.18); color:rgba(255,255,255,.92); font-size:11px; letter-spacing:.04em; font-family: var(--font-sans) !important;}}
        .compact-title {{font-size:13px; letter-spacing:.18em; text-transform:uppercase; color:#6f7c74; margin:4px 0 10px; font-family: var(--font-sans) !important;}}
        .result-page-intro {{color:#55635b; font-size:14px; line-height:1.7; margin-top:2px; margin-bottom:10px;}}

        div[data-testid="stTextInputRootElement"] input {{
            height: 52px !important;
            border-radius: 14px !important;
            border: 1px solid rgba(23,58,45,0.12) !important;
            background: rgba(255,255,255,0.98) !important;
            box-shadow: none !important;
            font-size: 17px !important;
            color: #111111 !important;
            -webkit-text-fill-color: #111111 !important;
            caret-color: #111111 !important;
        }}
        div[data-testid="stTextInputRootElement"] input::placeholder {{
            color: rgba(65,74,70,0.42) !important;
            -webkit-text-fill-color: rgba(65,74,70,0.42) !important;
        }}
        div[data-testid="stWidgetLabel"], div[data-testid="InputInstructions"] {{display:none !important;}}

        div[data-testid="stForm"] {{
            background: {'rgba(255,255,255,0.10)' if not result_mode else '#ffffff'};
            border: 1px solid {'rgba(255,255,255,0.16)' if not result_mode else 'rgba(21,34,26,0.08)'};
            border-radius: 22px;
            padding: 14px;
            backdrop-filter: {'blur(10px)' if not result_mode else 'none'};
            box-shadow: {'0 20px 60px rgba(0,0,0,0.14)' if not result_mode else '0 12px 26px rgba(16,24,19,0.06)'};
        }}
        div[data-testid="stFormSubmitButton"] > button {{height:46px; border-radius:13px; font-weight:700; box-shadow:none !important; font-family: var(--font-sans) !important;}}
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{background:#173a2d !important; border:1px solid #173a2d !important; color:white !important;}}
        div[data-testid="stFormSubmitButton"] > button[kind="secondary"] {{background:rgba(255,255,255,0.92) !important; border:1px solid rgba(24,37,31,0.10) !important; color:#31443b !important;}}
        div[data-testid="stButton"] > button[kind="primary"], div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{background:#173a2d !important; border:1px solid #173a2d !important; color:white !important;}}

        .search-footnote {{margin-top:10px; text-align:center; color:{'rgba(255,255,255,0.74)' if not result_mode else '#67746c'}; font-size:12px;}}
        .card-title {{font-size:24px; font-weight:700; color:#16241e; margin-bottom:6px; font-family: var(--font-display) !important; letter-spacing:-0.01em;}}
        .card-sub {{font-size:14px; line-height:1.7; color:#536159; margin-bottom:10px;}}
        .result-divider {{height:12px;}}
        .subtle {{color:#4f5d55; font-size:13px; line-height:1.7;}}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: rgba(248,250,248,0.98) !important;
            border: 1px solid rgba(21,34,26,0.06) !important;
            border-radius: 22px !important;
            box-shadow: 0 14px 42px rgba(16,24,19,0.08) !important;
            padding: 8px 10px !important;
        }}
        .overview-name {{font-size:38px; line-height:1.08; font-weight:700; color:#15231d; margin:8px 0; font-family: var(--font-display) !important; letter-spacing:-0.02em;}}
        .overview-line {{font-size:16px; line-height:1.7; color:#2f4138;}}
        .pill-row {{display:flex; flex-wrap:wrap; gap:10px; margin-top:14px;}}
        .pill {{padding:8px 12px; border-radius:999px; background:#eef3ef; border:1px solid #dde7e1; color:#264335; font-size:13px;}}
        .score-panel {{background:linear-gradient(180deg, #163a2c 0%, #1b583d 100%); color:white; border-radius:24px; padding:26px; box-shadow:0 18px 42px rgba(21,58,43,0.24); min-height:100%;}}
        .score-kicker {{opacity:.78; letter-spacing:.16em; text-transform:uppercase; font-size:12px; font-family: var(--font-sans) !important;}}
        .score-number {{font-size:88px; line-height:1; font-weight:800; margin:10px 0 6px; font-family: var(--font-sans) !important;}}
        .metric-grid {{display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin-top:16px;}}
        .metric-box {{background:#f5f8f5; border:1px solid #e5ece7; border-radius:18px; padding:14px;}}
        .metric-label {{font-size:12px; color:#728077; margin-bottom:4px;}}
        .metric-value {{font-size:28px; font-weight:800; color:#182820;}}
        .metric-note {{font-size:12px; color:#5e6c64; margin-top:4px;}}
        .deduct-row {{display:flex; justify-content:space-between; align-items:flex-start; gap:14px; padding:14px 0; border-bottom:1px dashed #e2e9e4;}}
        .deduct-row:last-child {{border-bottom:none;}}
        .deduct-title {{font-size:16px; font-weight:700; color:#1b2a23; font-family: var(--font-display) !important;}}
        .deduct-detail {{font-size:13px; color:#67756d; margin-top:4px;}}
        .deduct-right {{font-size:16px; font-weight:700; color:#173a2d; white-space:nowrap;}}

        @media (max-width: 900px) {{
            .block-container {{padding-left:.9rem !important; padding-right:.9rem !important;}}
            .hero-wrap {{min-height:44vh; padding-top:4vh;}}
            .hero-sub {{font-size:14px;}}
            .overview-name {{font-size:32px;}}
            .metric-grid {{grid-template-columns:repeat(2, minmax(0,1fr));}}
        }}
        
/* Strong Streamlit form button overrides */
div[data-testid="stForm"] button[kind="primary"],
div[data-testid="stForm"] button[kind="primaryFormSubmit"],
div[data-testid="stForm"] button[data-testid="baseButton-primary"],
div[data-testid="stForm"] button[data-testid="stBaseButton-primary"] {{
    background: #173a2d !important;
    border: 1px solid #173a2d !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] button[kind="primary"]:hover,
div[data-testid="stForm"] button[kind="primaryFormSubmit"]:hover,
div[data-testid="stForm"] button[data-testid="baseButton-primary"]:hover,
div[data-testid="stForm"] button[data-testid="stBaseButton-primary"]:hover {{
    background: #1d4636 !important;
    border-color: #1d4636 !important;
    color: #ffffff !important;
}}
div[data-testid="stForm"] button[kind="secondary"],
div[data-testid="stForm"] button[kind="secondaryFormSubmit"],
div[data-testid="stForm"] button[data-testid="baseButton-secondary"],
div[data-testid="stForm"] button[data-testid="stBaseButton-secondary"] {{
    background: rgba(255,255,255,0.92) !important;
    border: 1px solid rgba(24,37,31,0.10) !important;
    color: #31443b !important;
    -webkit-text-fill-color: #31443b !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] button[kind="secondary"]:hover,
div[data-testid="stForm"] button[kind="secondaryFormSubmit"]:hover,
div[data-testid="stForm"] button[data-testid="baseButton-secondary"]:hover,
div[data-testid="stForm"] button[data-testid="stBaseButton-secondary"]:hover {{
    background: rgba(255,255,255,0.98) !important;
    border-color: rgba(24,37,31,0.16) !important;
    color: #23352d !important;
}}
div[data-testid="stForm"] button {{
    height: 46px !important;
    border-radius: 13px !important;
    font-weight: 700 !important;
    font-family: var(--font-sans) !important;
}}

</style>
        """,
        unsafe_allow_html=True,
    )
    if bg_layer:
        st.markdown(bg_layer, unsafe_allow_html=True)


# ---------- UI blocks ----------
def render_topbar(light: bool = False) -> None:
    cls = "topbar light" if light else "topbar"
    st.markdown(f'<div class="{cls}"><div class="brand">QuietBJ</div><div></div></div>', unsafe_allow_html=True)


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero-wrap">
            <div>
                <div class="hero-kicker">BEIJING RESIDENTIAL CALM INDEX</div>
                <h1 class="hero-title">安宁北京</h1>
                <div class="hero-sub">楼栋级住宅环境评估引擎。识别小区，定位楼栋，测算道路、商业、学校、医院与轨道暴露。</div>
                <div class="hero-note">标准基准分 · 楼栋位置调整 · 外部环境影响</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_search(compact: bool = False) -> tuple[str, bool, bool]:
    if compact:
        st.markdown('<div class="compact-title">New Search</div>', unsafe_allow_html=True)
        st.markdown('<div class="result-page-intro">继续输入新的北京小区或楼栋地址，系统会重新定位楼栋并更新评估结果。</div>', unsafe_allow_html=True)
        layout = [5.5, 1.25, 1.0]
    else:
        layout = [5.0, 1.3, 1.0]

    with st.form("hero_search", clear_on_submit=False):
        query = st.text_input(
            "hero_query",
            placeholder="输入北京小区或楼栋地址，例如：新龙城6号楼 / 花家地西里2号楼",
            label_visibility="collapsed",
        )
        _, center, _ = st.columns([1.4, 1.2, 1.4])
        with center:
            submit = st.form_submit_button("开始查询", type="primary", use_container_width=True)
        clear = False
    st.markdown(
        f'<div class="search-footnote">建议输入：小区名 + 楼号。系统会先识别小区，再围绕更接近楼栋的坐标测算外部噪音暴露。</div>',
        unsafe_allow_html=True,
    )
    return query, submit, clear


def render_overview_card(query: str, community_row: dict[str, Any], result: dict[str, Any], signals: list[dict[str, Any]]) -> None:
    with st.container(border=True):
        left, right = st.columns([1.25, 0.95], vertical_alignment="top")
        with left:
            st.markdown(f'<div class="overview-name">{community_row.get("_display_name") or community_row.get("community_name", "目标小区")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="overview-line">{build_summary_line(signals)}</div>', unsafe_allow_html=True)
            pills = [f'<span class="pill">标准基准分 {DEFAULT_BASE_SCORE}</span>']
            district = str(community_row.get("district", "")).strip()
            if district:
                pills.append(f'<span class="pill">{district}</span>')
            source = str(community_row.get("_match_source", "")).strip()
            if source:
                pills.append(f'<span class="pill">{source}</span>')
            locator_conf = str(community_row.get("_locator_confidence", "")).strip()
            locator_mode = str(community_row.get("_locator_mode", "")).strip()
            if locator_conf:
                pills.append(f'<span class="pill">定位置信度 {locator_conf}</span>')
            if locator_mode:
                pills.append(f'<span class="pill">{locator_mode}</span>')
            override_zone_type = str(community_row.get("_override_zone_type", "")).strip()
            if override_zone_type:
                pills.append('<span class="pill">人工校正</span>')
            st.markdown('<div class="pill-row">' + ''.join(pills) + '</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="subtle" style="margin-top:12px;">楼栋输入：{query}｜用于小区匹配的文本：{community_row.get("_query_used", "") or query}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="subtle" style="margin-top:6px;"><strong style="color:#173a2d;">识别说明：</strong>{community_row.get("_locator_note", "当前按楼栋近似位置估算。")}</div>',
                unsafe_allow_html=True,
            )
            if override_zone_type:
                st.markdown(
                    f'<div class="subtle" style="margin-top:6px;"><strong style="color:#173a2d;">空间语境：</strong>已命中人工校正规则，当前按 {override_zone_type} 处理。</div>',
                    unsafe_allow_html=True,
                )
            metric_html = [
                ("标准基准分", str(DEFAULT_BASE_SCORE), "统一基准评估"),
                ("楼栋位置调整", f"{result['zone_adjust']:+d}", "来自楼栋位置"),
                ("建筑条件调整", f"{result['build_bonus']:+d}", "来自楼龄代理值"),
                ("外部环境影响", f"{result['noise_penalty']}", "来自道路 / 商业 / 学校 / 轨道"),
            ]
            st.markdown(
                '<div class="metric-grid">' + ''.join(
                    [f'<div class="metric-box"><div class="metric-label">{a}</div><div class="metric-value">{b}</div><div class="metric-note">{c}</div></div>' for a,b,c in metric_html]
                ) + '</div>',
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                f'''
                <div class="score-panel">
                    <div class="score-kicker">Quiet Score</div>
                    <div class="score-number">{result['final_score']}</div>
                    <h3>{label_score(result['final_score'])}</h3>
                    <div style="line-height:1.75; font-size:14px; opacity:0.96;">系统基于楼栋位置、道路距离、商业暴露、学校医院和轨道交通进行估算，用于快速判断这套房是否值得继续看。</div>
                </div>
                ''',
                unsafe_allow_html=True,
            )


def render_penalty_card(noise_summary: dict[str, Any]) -> None:
    signals = noise_summary.get("signals", [])
    with st.container(border=True):
        st.markdown('<div class="card-title">影响来源</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">先看主要影响项，再决定要不要继续实勘。这一层只展示对当前楼栋体感最重要的外部环境因素。</div>', unsafe_allow_html=True)
        if not signals:
            st.info("当前没有识别到明显的外部环境影响，系统没有形成显著的影响值。")
        else:
            rows = []
            for sig in sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True):
                right_text = f'{sig.get("distance_m", "-")}m ｜ 影响值 {int(sig.get("penalty", 0))}'
                raw_penalty = sig.get("raw_penalty")
                shielding_level = str(sig.get("shielding_level", "")).strip()
                blocker_count = int(sig.get("blocker_count", 0) or 0)
                if raw_penalty not in ("", None) and int(raw_penalty) != int(sig.get("penalty", 0)):
                    right_text = f'{sig.get("distance_m", "-")}m ｜ 原始 {int(raw_penalty)} → 遮挡后 {int(sig.get("penalty", 0))}'
                detail_text = str(sig.get("detail", "")).strip()
                if shielding_level and shielding_level != "none":
                    detail_suffix = f'｜前排遮挡 {shielding_level}（挡住 {blocker_count} 栋）'
                    detail_text = (detail_text + detail_suffix).strip("｜")
                rows.append(
                    f'<div class="deduct-row"><div><div class="deduct-title">{sig.get("label", "")}</div><div class="deduct-detail">{detail_text}</div></div><div class="deduct-right">{right_text}</div></div>'
                )
            st.markdown(''.join(rows), unsafe_allow_html=True)
            st.markdown(f"<div class='subtle' style='margin-top:10px;'>总体环境影响值：<strong style='color:#173a2d;'>{int(noise_summary.get('total_penalty', 0))}</strong></div>", unsafe_allow_html=True)


def render_position_card(result: dict[str, Any], zone_labels: list[str], zone_key: str) -> None:
    with st.container(border=True):
        st.markdown('<div class="card-title">楼栋位置调整</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">该部分用于模拟不同楼栋位置语境下的环境差异，例如临街、中央区或内排安静区。</div>', unsafe_allow_html=True)
        st.selectbox("楼栋位置", zone_labels, key=zone_key, label_visibility="collapsed")
        summary = (
            f"当前按“{result['zone_name']}”处理；"
            f"楼栋位置调整 {result['zone_adjust']:+d}，"
            f"建筑条件调整 {result['build_bonus']:+d}，"
            f"密度调整 -{result['density_penalty']}。"
        )
        st.markdown(f"<div class='subtle' style='margin-top:12px;'>{summary}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='subtle' style='margin-top:6px;'>位置说明：{result['zone_description']}。</div>", unsafe_allow_html=True)


def render_debug_card(geocode_used: dict[str, Any] | None, building_location_text: str, community_row: dict[str, Any], tip_list: list[dict[str, Any]], regeo: dict[str, Any] | None) -> None:
    with st.expander("地址识别核查", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**楼栋点位**")
            st.write(f"标准化地址：{str((geocode_used or {}).get('formatted_address', '')).strip() or '—'}")
            st.write(f"location：{building_location_text or '—'}")
            district = str((geocode_used or {}).get("district", "")).strip() or str(community_row.get("district", "")).strip()
            st.write(f"district：{district or '—'}")
            st.write(f"楼号细节：{str(community_row.get('_detail_token', '')).strip() or '—'}")
            st.write(f"定位模式：{str(community_row.get('_locator_mode', '')).strip() or '—'}")
            st.write(f"定位置信度：{str(community_row.get('_locator_confidence', '')).strip() or '—'}")
            st.write(f"人工校正规则：{str(community_row.get('_override_zone_type', '')).strip() or '—'}")
            st.write(f"楼栋缓存：{COMMUNITY_BUILDING_CACHE_FILE.name}")
        with c2:
            st.markdown("**高德候选**")
            if tip_list:
                for tip in tip_list[:5]:
                    st.write(f"- {tip.get('name', '')}｜{tip.get('district', '')} {tip.get('address', '')}")
            else:
                st.write("没有拿到输入提示候选。")
        with st.expander("逆地理编码原始结果", expanded=False):
            st.json(regeo if regeo else {"note": "无"})


def render_cache_tools(community_row: dict[str, Any]) -> None:
    cache = load_building_cache(COMMUNITY_BUILDING_CACHE_FILE)
    community_name = str(community_row.get("community_name", "")).strip()
    current_buildings = get_cached_buildings(cache, community_name) if community_name else []
    cache_json = json.dumps(cache, ensure_ascii=False, indent=2)
    current_payload = {
        "community_name": community_name,
        "building_count": len(current_buildings),
        "buildings": current_buildings,
    }
    current_json = json.dumps(current_payload, ensure_ascii=False, indent=2)

    with st.expander("缓存管理", expanded=False):
        c1, c2, c3 = st.columns([1.25, 1.25, 1.0])
        with c1:
            st.download_button(
                "下载全部缓存 JSON",
                data=cache_json,
                file_name="community_building_cache.json",
                mime="application/json",
                use_container_width=True,
            )
        with c2:
            st.download_button(
                "导出当前小区缓存",
                data=current_json,
                file_name=f"{community_name or 'current_community'}_cache.json",
                mime="application/json",
                use_container_width=True,
            )
        with c3:
            if st.button("清空缓存", type="secondary", use_container_width=True):
                save_building_cache({}, COMMUNITY_BUILDING_CACHE_FILE)
                st.success("缓存已清空。")
                st.rerun()

        st.markdown(
            f"<div class='subtle' style='margin-top:10px;'>当前缓存文件：<strong>{COMMUNITY_BUILDING_CACHE_FILE.name}</strong>｜已缓存楼栋数：<strong>{sum(len(v.get('buildings', [])) for v in cache.values())}</strong>｜当前小区缓存：<strong>{len(current_buildings)}</strong></div>",
            unsafe_allow_html=True,
        )


# ---------- app ----------
def main() -> None:
    if "last_query" not in st.session_state:
        st.session_state["last_query"] = ""

    result_mode = bool(st.session_state.get("last_query", "").strip())
    render_styles(result_mode=result_mode)

    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    building_overrides = load_building_overrides()
    amap = AMapProvider(get_amap_api_key(st.secrets))
    score_engine = ScoreEngine()

    if result_mode:
        render_topbar(light=True)
        submitted = False
        clear = False
    else:
        render_topbar(light=False)
        render_hero()
        left, center, right = st.columns([1.0, 4.9, 1.0])
        with center:
            query, submitted, clear = render_search(compact=False)

    if clear:
        st.session_state["last_query"] = ""
        # Clear any remembered zone selection too.
        for key in list(st.session_state.keys()):
            if key.startswith("zone_select::"):
                del st.session_state[key]
        st.rerun()
    if submitted:
        st.session_state["last_query"] = query.strip()
        st.rerun()

    query = st.session_state.get("last_query", "").strip()
    if not query:
        return

    community_row, tip_list, regeo, building_location_text, geocode_used = parse_geocode_result(query, community_repo, amap)
    community_row = apply_building_override(community_row, query, building_overrides)
    update_building_cache_for_current_result(community_row, building_location_text)
    poi_results: dict[str, list[dict[str, Any]]] = {}
    if amap.enabled() and building_location_text:
        poi_results = {
            "school": amap.search_around(building_location_text, "学校", radius=1200),
            "hospital": amap.search_around(building_location_text, "医院", radius=1500),
            "commercial": amap.search_around(building_location_text, "便利店 超市 商场 购物服务 生活服务", radius=300),
            "restaurant": amap.search_around(building_location_text, "餐饮服务", radius=300),
            "rail": amap.search_around(building_location_text, "地铁站", radius=800),
        }
    raw_noise_summary = NoisePointEngine().evaluate(regeo, poi_results)
    noise_summary = refine_noise_summary(raw_noise_summary, score_engine)
    noise_summary = apply_road_shielding(noise_summary, community_row, building_location_text, regeo)

    community_code = str(community_row.get("community_code", ""))
    zone_options = zone_repo.get_by_community(community_code)
    if not zone_options:
        zone_options = [
            {"zone_code": "street_front", "zone_name": "临主路首排", "adjustment_score": -8, "description": "直接朝向主路或高速一侧，车辆持续噪音更强。"},
            {"zone_code": "secondary_street", "zone_name": "次临街区", "adjustment_score": -4, "description": "不在首排，但仍会明显感受到道路噪音。"},
            {"zone_code": "central_inner", "zone_name": "小区中央", "adjustment_score": 0, "description": "按小区平均位置处理。"},
            {"zone_code": "quiet_inner", "zone_name": "内排安静区", "adjustment_score": 6, "description": "更靠小区内部，有前排遮挡，通常更安静。"},
            {"zone_code": "gate_side", "zone_name": "出入口附近", "adjustment_score": -5, "description": "出入口、人车流与停车场会增加体感噪音。"},
            {"zone_code": "commercial_edge", "zone_name": "靠底商/商业", "adjustment_score": -6, "description": "沿街底商、餐饮和生活服务会抬高噪音。"},
        ]

    zone_labels = [str(z.get("zone_name", "")) for z in zone_options]
    override_zone_type = str(community_row.get("_override_zone_type", "")).strip()
    if override_zone_type:
        default_idx = next((i for i, z in enumerate(zone_options) if str(z.get("zone_code", "")).strip() == override_zone_type), 0)
    else:
        default_idx = next((i for i, z in enumerate(zone_options) if str(z.get("zone_code", "")) in {"central_inner", "DEFAULT", "default"}), 0)
    zone_key = f"zone_select::{community_code or 'default'}"
    if zone_key not in st.session_state:
        st.session_state[zone_key] = zone_labels[default_idx]
    selected_name = st.session_state[zone_key]
    if selected_name not in zone_labels:
        selected_name = zone_labels[default_idx]
        st.session_state[zone_key] = selected_name

    result = compute_position_result(zone_options, community_row, score_engine, int(noise_summary.get("total_penalty", 0)), selected_name)

    render_overview_card(query, community_row, result, noise_summary.get("signals", []))
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_open_map_card(building_location_text, geocode_used, regeo, poi_results, noise_summary.get("signals", []), community_row)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_penalty_card(noise_summary)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_position_card(result, zone_labels, zone_key)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_debug_card(geocode_used, building_location_text, community_row, tip_list, regeo)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_cache_tools(community_row)


if __name__ == "__main__":
    main()
