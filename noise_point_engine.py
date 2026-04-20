from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NoiseSignal:
    label: str
    distance_m: int | None
    penalty: int
    detail: str


class NoisePointEngine:
    DEFAULT_RADIUS = 1200

    def __init__(self) -> None:
        self.poi_specs = [
            {"key": "school", "label": "学校", "keyword": "学校", "radius": 1200},
            {"key": "hospital", "label": "医院", "keyword": "医院", "radius": 1500},
            {"key": "commercial", "label": "商业/底商", "keyword": "购物中心", "radius": 1000},
            {"key": "restaurant", "label": "餐饮聚集", "keyword": "餐饮服务", "radius": 800},
        ]

    def _nearest_distance(self, pois: list[dict[str, Any]]) -> int | None:
        distances: list[int] = []
        for poi in pois:
            raw = str(poi.get("distance", "")).strip()
            try:
                distances.append(int(float(raw)))
            except Exception:
                continue
        return min(distances) if distances else None

    def _road_penalty(self, roads: list[dict[str, Any]]) -> NoiseSignal | None:
        nearest: int | None = None
        road_name = ""
        for road in roads[:5]:
            raw = str(road.get("distance", "")).strip()
            try:
                distance = int(float(raw))
            except Exception:
                continue
            if nearest is None or distance < nearest:
                nearest = distance
                road_name = str(road.get("name", "")).strip()
        if nearest is None:
            return None
        if nearest <= 60:
            penalty = 12
        elif nearest <= 120:
            penalty = 8
        elif nearest <= 250:
            penalty = 4
        else:
            penalty = 0
        return NoiseSignal("主干路", nearest, penalty, road_name or "主干路")

    def _poi_penalty(self, label: str, nearest: int | None, count: int) -> NoiseSignal | None:
        if nearest is None:
            return None
        penalty = 0
        if label == "学校":
            penalty = 5 if nearest <= 100 else 3 if nearest <= 250 else 1 if nearest <= 500 else 0
        elif label == "医院":
            penalty = 4 if nearest <= 120 else 2 if nearest <= 300 else 1 if nearest <= 600 else 0
        elif label == "商业/底商":
            penalty = 6 if nearest <= 80 else 4 if nearest <= 180 else 2 if nearest <= 350 else 0
            if count >= 4:
                penalty += 1
        elif label == "餐饮聚集":
            penalty = 5 if nearest <= 60 else 3 if nearest <= 160 else 1 if nearest <= 300 else 0
            if count >= 6:
                penalty += 1
        if penalty <= 0:
            return None
        return NoiseSignal(label, nearest, penalty, f"最近 {nearest}m｜周边 {count} 个")

    def evaluate(self, regeo: dict[str, Any] | None, poi_results: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
        roads = []
        if isinstance(regeo, dict):
            roads = regeo.get("roads", []) if isinstance(regeo.get("roads", []), list) else []

        signals: list[NoiseSignal] = []
        road_signal = self._road_penalty(roads)
        if road_signal:
            signals.append(road_signal)

        poi_results = poi_results or {}
        for spec in self.poi_specs:
            pois = poi_results.get(spec["key"], [])
            nearest = self._nearest_distance(pois)
            signal = self._poi_penalty(spec["label"], nearest, len(pois))
            if signal:
                signals.append(signal)

        total_penalty = sum(item.penalty for item in signals)
        return {
            "signals": [item.__dict__ for item in signals],
            "total_penalty": total_penalty,
        }
