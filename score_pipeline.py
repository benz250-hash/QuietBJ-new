from __future__ import annotations

from typing import Any

from building_engine import BuildingEngine
from community_engine import CommunityEngine
from zone_engine import ZoneEngine


class ScorePipeline:
    def __init__(self, community_engine: CommunityEngine, zone_engine: ZoneEngine, building_engine: BuildingEngine | None = None):
        self.community_engine = community_engine
        self.zone_engine = zone_engine
        self.building_engine = building_engine or BuildingEngine()

    def run(self, community_row: dict[str, Any], zone_row: dict[str, Any] | None = None, building_row: dict[str, Any] | None = None) -> dict[str, Any]:
        base_score = self.community_engine.calculate_base_score(community_row)
        zone_adjustment = self.zone_engine.get_adjustment(zone_row)
        building_adjustment = self.building_engine.get_adjustment(building_row)
        final_score = max(50, min(100, round(base_score + zone_adjustment + building_adjustment)))
        return {
            "base_score": base_score,
            "zone_adjustment": zone_adjustment,
            "building_adjustment": building_adjustment,
            "final_score": final_score,
        }
