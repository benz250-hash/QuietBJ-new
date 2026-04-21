from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoreConfig:
    standard_base_score: int = 85

    # 轻量 TNM 化 v2：道路分层
    expressway_bands: list[tuple[int, int]] | None = None
    arterial_bands: list[tuple[int, int]] | None = None
    secondary_bands: list[tuple[int, int]] | None = None
    local_bands: list[tuple[int, int]] | None = None
    internal_bands: list[tuple[int, int]] | None = None

    # 其他影响源
    rail_bands: list[tuple[int, int]] | None = None
    school_bands: list[tuple[int, int]] | None = None
    hospital_bands: list[tuple[int, int]] | None = None
    commercial_bands: list[tuple[int, int]] | None = None
    restaurant_bands: list[tuple[int, int]] | None = None

    zone_adjustments: dict[str, int] | None = None
    locator_confidence_display: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # 更符合常识的非线性距离分段：
        # 高等级道路影响上限更高、衰减更慢；低等级道路只在近距离明显。
        if self.expressway_bands is None:
            object.__setattr__(self, "expressway_bands", [(50, 16), (100, 14), (150, 12), (250, 9), (400, 6), (600, 3)])
        if self.arterial_bands is None:
            object.__setattr__(self, "arterial_bands", [(30, 10), (60, 8), (100, 6), (180, 4), (300, 2)])
        if self.secondary_bands is None:
            object.__setattr__(self, "secondary_bands", [(20, 5), (40, 4), (80, 2), (150, 1)])
        if self.local_bands is None:
            object.__setattr__(self, "local_bands", [(10, 2), (20, 1), (35, 1), (60, 0)])
        if self.internal_bands is None:
            object.__setattr__(self, "internal_bands", [(8, 1), (15, 1), (30, 0)])

        if self.rail_bands is None:
            object.__setattr__(self, "rail_bands", [(150, 6), (300, 3), (500, 1)])
        if self.school_bands is None:
            object.__setattr__(self, "school_bands", [(120, 4), (250, 2)])
        if self.hospital_bands is None:
            object.__setattr__(self, "hospital_bands", [(150, 3), (300, 1)])
        if self.commercial_bands is None:
            object.__setattr__(self, "commercial_bands", [(80, 5), (160, 3)])
        if self.restaurant_bands is None:
            object.__setattr__(self, "restaurant_bands", [(120, 4), (250, 2)])

        if self.zone_adjustments is None:
            object.__setattr__(self, "zone_adjustments", {
                "street_front": -8,
                "edge_building": -3,
                "central": 0,
                "quiet_inner": 6,
                "compound_approx": 0,
            })
        if self.locator_confidence_display is None:
            object.__setattr__(self, "locator_confidence_display", {
                "building_exact": "高",
                "building_approx": "中",
                "compound_approx": "低",
                "unstable": "低",
            })


class ScoreEngine:
    """
    轻量 TNM 化 v2

    设计原则：
    1. 先给不同等级道路一个非线性距离分段值
    2. 每个等级只取最近一条代表路，避免重复叠加把分数算爆
    3. 高速/快速路 100 米影响应明显大于 10 米小路影响
    4. 小路/内部路只做弱影响，更适合拉开边缘感，而不是压过主路
    5. final_score() 继续兼容旧页面接口
    """

    def __init__(self, config: ScoreConfig | None = None) -> None:
        self.cfg = config or ScoreConfig()

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value in ("", None):
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def band_score(distance_m: float | None, bands: list[tuple[int, int]]) -> int:
        if distance_m is None:
            return 0
        for upper, score in bands:
            if distance_m <= upper:
                return score
        return 0

    def road_impact_scores(
        self,
        nearest_expressway_dist: Any = None,
        nearest_arterial_dist: Any = None,
        nearest_secondary_dist: Any = None,
        nearest_local_dist: Any = None,
        nearest_internal_dist: Any = None,
    ) -> dict[str, int]:
        expressway_score = self.band_score(self._coerce_float(nearest_expressway_dist), self.cfg.expressway_bands)
        arterial_score = self.band_score(self._coerce_float(nearest_arterial_dist), self.cfg.arterial_bands)
        secondary_score = self.band_score(self._coerce_float(nearest_secondary_dist), self.cfg.secondary_bands)
        local_score = self.band_score(self._coerce_float(nearest_local_dist), self.cfg.local_bands)
        internal_score = self.band_score(self._coerce_float(nearest_internal_dist), self.cfg.internal_bands)

        # 小路 + 内部路总上限，避免安静小区因为路网密而被算爆
        local_internal_total = min(local_score + internal_score, 4)

        road_impact = expressway_score + arterial_score + secondary_score + local_internal_total
        return {
            "expressway_impact": expressway_score,
            "arterial_impact": arterial_score,
            "secondary_impact": secondary_score,
            "local_impact": local_score,
            "internal_impact": internal_score,
            "local_internal_total": local_internal_total,
            "road_impact": road_impact,
        }

    def source_impact_scores(
        self,
        nearest_expressway_dist: Any = None,
        nearest_arterial_dist: Any = None,
        nearest_secondary_dist: Any = None,
        nearest_local_dist: Any = None,
        nearest_internal_dist: Any = None,
        nearest_rail_dist: Any = None,
        nearest_school_dist: Any = None,
        nearest_hospital_dist: Any = None,
        nearest_commercial_dist: Any = None,
        nearest_restaurant_dist: Any = None,
    ) -> dict[str, int]:
        road_items = self.road_impact_scores(
            nearest_expressway_dist=nearest_expressway_dist,
            nearest_arterial_dist=nearest_arterial_dist,
            nearest_secondary_dist=nearest_secondary_dist,
            nearest_local_dist=nearest_local_dist,
            nearest_internal_dist=nearest_internal_dist,
        )
        rail_impact = self.band_score(self._coerce_float(nearest_rail_dist), self.cfg.rail_bands)
        school_impact = self.band_score(self._coerce_float(nearest_school_dist), self.cfg.school_bands)
        hospital_impact = self.band_score(self._coerce_float(nearest_hospital_dist), self.cfg.hospital_bands)
        commercial_impact = self.band_score(self._coerce_float(nearest_commercial_dist), self.cfg.commercial_bands)
        restaurant_impact = self.band_score(self._coerce_float(nearest_restaurant_dist), self.cfg.restaurant_bands)

        external_environment_impact = round(
            road_items["road_impact"]
            + rail_impact
            + school_impact
            + hospital_impact
            + commercial_impact
            + restaurant_impact
        )
        return {
            **road_items,
            "rail_impact": rail_impact,
            "school_impact": school_impact,
            "hospital_impact": hospital_impact,
            "commercial_impact": commercial_impact,
            "restaurant_impact": restaurant_impact,
            "external_environment_impact": external_environment_impact,
        }

    def building_adjustment(self, build_year: Any) -> int:
        year = self._coerce_float(build_year)
        if year is None:
            return 0
        if year >= 2025:
            return 5
        if year >= 2015:
            return 3
        if year >= 2005:
            return 1
        return 0

    def density_adjustment(self, far_ratio: Any) -> int:
        ratio = self._coerce_float(far_ratio)
        if ratio is None:
            return 0
        if ratio < 1.5:
            return 2
        if ratio < 2.2:
            return 0
        if ratio < 3.0:
            return -3
        return -6

    def normalize_zone_adjustment(self, zone_adjust: Any) -> int:
        value = self._coerce_float(zone_adjust)
        return int(round(value or 0))

    @staticmethod
    def clamp_score(score: int) -> int:
        return max(50, min(95, int(round(score))))

    def final_score(
        self,
        standard_base_score: Any,
        zone_adjust: Any,
        noise_penalty: Any,
        far_ratio: Any,
        build_year: Any,
    ) -> dict[str, Any]:
        """
        兼容旧接口：
        final_score(DEFAULT_BASE_SCORE, zone_adjust, noise_penalty, far_ratio, build_year)

        当前页面仍然先把外部环境影响汇总成一个 total_penalty/noise_penalty 再传进来。
        这版 score_engine 先把道路/轨道/生活源的参数骨架升级好，后续页面再逐步切到结构化输入。
        """
        base_score = int(round(self._coerce_float(standard_base_score) or self.cfg.standard_base_score))
        zone_adjust_value = self.normalize_zone_adjustment(zone_adjust)
        build_bonus = self.building_adjustment(build_year)
        density_adjustment_value = self.density_adjustment(far_ratio)
        external_environment_impact = int(round(self._coerce_float(noise_penalty) or 0))

        final_score = self.clamp_score(
            base_score
            + zone_adjust_value
            + build_bonus
            + density_adjustment_value
            - external_environment_impact
        )

        return {
            "base_score": base_score,
            "zone_adjust": zone_adjust_value,
            "build_bonus": build_bonus,
            "density_adjustment": density_adjustment_value,
            "density_penalty": abs(min(density_adjustment_value, 0)),
            "noise_penalty": external_environment_impact,
            "external_environment_impact": external_environment_impact,
            "final_score": final_score,
        }
