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
    def _nearest_distance(self, items: list[dict[str, Any]]) -> int | None:
        vals=[]
        for item in items:
            raw=str(item.get('distance','')).strip()
            try:
                vals.append(int(float(raw)))
            except Exception:
                continue
        return min(vals) if vals else None

    def road_signals(self, regeo: dict[str, Any] | None) -> list[NoiseSignal]:
        if not isinstance(regeo, dict):
            return []
        roads = regeo.get('roads', []) if isinstance(regeo.get('roads', []), list) else []
        highway_nearest = None
        highway_name = ''
        trunk_nearest = None
        trunk_name = ''
        for road in roads[:10]:
            name = str(road.get('name','')).strip()
            raw = str(road.get('distance','')).strip()
            try:
                dist = int(float(raw))
            except Exception:
                continue
            if any(tok in name for tok in ['高速','快速','环路','京藏','京承','京开','机场']):
                if highway_nearest is None or dist < highway_nearest:
                    highway_nearest = dist; highway_name = name
            else:
                if trunk_nearest is None or dist < trunk_nearest:
                    trunk_nearest = dist; trunk_name = name
        out=[]
        if highway_nearest is not None:
            if highway_nearest <= 120: pen = 18
            elif highway_nearest <= 250: pen = 12
            elif highway_nearest <= 500: pen = 6
            else: pen = 0
            if pen>0: out.append(NoiseSignal('高速/快速路', highway_nearest, pen, highway_name or '高速/快速路'))
        if trunk_nearest is not None:
            if trunk_nearest <= 80: pen = 10
            elif trunk_nearest <= 180: pen = 6
            elif trunk_nearest <= 350: pen = 3
            else: pen = 0
            if pen>0: out.append(NoiseSignal('主干路', trunk_nearest, pen, trunk_name or '主干路'))
        return out

    def poi_signal(self, label: str, pois: list[dict[str, Any]]) -> NoiseSignal | None:
        nearest = self._nearest_distance(pois)
        if nearest is None:
            return None
        cnt = len(pois)
        pen = 0
        if label == '学校':
            pen = 4 if nearest <= 120 else 2 if nearest <= 250 else 0
        elif label == '医院':
            pen = 3 if nearest <= 150 else 1 if nearest <= 300 else 0
        elif label == '商业/底商':
            pen = 6 if nearest <= 60 else 4 if nearest <= 140 else 2 if nearest <= 300 else 0
            if cnt >= 5: pen += 1
        elif label == '餐饮聚集':
            pen = 4 if nearest <= 80 else 2 if nearest <= 160 else 1 if nearest <= 300 else 0
            if cnt >= 8: pen += 1
        elif label == '轨道交通':
            pen = 6 if nearest <= 150 else 3 if nearest <= 300 else 1 if nearest <= 500 else 0
        if pen <= 0:
            return None
        return NoiseSignal(label, nearest, pen, f'最近 {nearest}m｜命中 {cnt} 个')

    def evaluate(self, regeo: dict[str, Any] | None, poi_results: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
        signals = self.road_signals(regeo)
        poi_results = poi_results or {}
        for label, key in [('学校','school'),('医院','hospital'),('商业/底商','commercial'),('餐饮聚集','restaurant'),('轨道交通','rail')]:
            sig = self.poi_signal(label, poi_results.get(key, []))
            if sig:
                signals.append(sig)
        return {'signals':[s.__dict__ for s in signals], 'total_penalty': sum(s.penalty for s in signals)}
