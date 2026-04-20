from __future__ import annotations

from typing import Any


class CommunityEngine:
    def calculate_base_score(self, community_row: dict[str, Any]) -> int:
        value = community_row.get("base_score", 75)
        try:
            return int(round(float(value)))
        except Exception:
            return 75

    def summarize(self, community_row: dict[str, Any]) -> list[str]:
        chips: list[str] = []
        district = str(community_row.get("district", "")).strip()
        far_ratio = str(community_row.get("far_ratio", "")).strip()
        road_note = str(community_row.get("road_note", "")).strip()
        if district:
            chips.append(district)
        if far_ratio:
            chips.append(f"容积率 {far_ratio}")
        if road_note:
            chips.append(road_note)
        return chips[:3]
