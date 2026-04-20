from __future__ import annotations

from typing import Any


class ZoneEngine:
    def get_adjustment(self, zone_row: dict[str, Any] | None) -> int:
        if not zone_row:
            return 0
        value = zone_row.get("adjustment_score", 0)
        try:
            return int(round(float(value)))
        except Exception:
            return 0

    def explain(self, zone_row: dict[str, Any] | None) -> str:
        if not zone_row:
            return "未选择楼栋位置，按小区基础分展示。"
        description = str(zone_row.get("description", "")).strip()
        if description:
            return description
        name = str(zone_row.get("zone_name", "该位置")).strip() or "该位置"
        score = self.get_adjustment(zone_row)
        if score > 0:
            return f"{name} 相对更安静，修正 {score:+d} 分。"
        if score < 0:
            return f"{name} 更容易受外部干扰，修正 {score:+d} 分。"
        return f"{name} 与小区平均位置接近，不做修正。"
