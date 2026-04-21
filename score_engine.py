
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoreConfig:
    standard_base_score: int = 75

    # 轻量 TNM 化：道路等级权重
    road_class_weights: dict[str, float] = None  # type: ignore[assignment]

    # 距离分段影响值
    expressway_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    arterial_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    secondary_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    rail_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    school_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    hospital_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    commercial_bands: list[tuple[int, int]] = None  # type: ignore[assignment]
    restaurant_bands: list[tuple[int, int]] = None  # type: ignore[assignment]

    zone_adjustments: dict[str, int] = None  # type: ignore[assignment]
    locator_confidence_display: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.road_class_weights is None:
            object.__setattr__(self, "road_class_weights", {
                "expressway": 1.00,   # 高速 / 快速路
                "arterial":   0.72,   # 主干路
                "secondary":  0.42,   # 次干路
            })
        if self.expressway_bands is None:
            object.__setattr__(self, "expressway_bands", [(120, 18), (250, 12), (500, 6)])
        if self.arterial_bands is None:
            object.__setattr__(self, "arterial_bands", [(80, 10), (180, 6), (350, 3)])
        if self.secondary_bands is None:
            object.__setattr__(self, "secondary_bands", [(60, 4), (120, 2), (220, 1)])
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
                "street_front": -8,   # 临街首排
                "edge_building": -3,  # 边缘楼栋
                "central": 0,         # 小区中央
                "quiet_inner": 6,     # 内排安静区
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
    轻量 TNM 化 v1

    当前主页面仍然传入一个已汇总的 noise_penalty，
    所以 final_score() 继续兼容旧接口。
    但这里已经把 v1 参数表固化进来，便于后续逐步把
    道路/轨道/生活源从“单一总影响值”拆成结构化输入。
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

    def weighted_road_score(self, road_class: str, distance_m: float | None) -> int:
        class_key = str(road_class or "").strip().lower()
        weight = self.cfg.road_class_weights.get(class_key, 0.0)
        if class_key == "expressway":
            base = self.band_score(distance_m, self.cfg.expressway_bands)
        elif class_key == "arterial":
            base = self.band_score(distance_m, self.cfg.arterial_bands)
        else:
            base = self.band_score(distance_m, self.cfg.secondary_bands)
        return round(base * weight)

    def source_impact_scores(
        self,
        nearest_expressway_dist: float | None = None,
        nearest_arterial_dist: float | None = None,
        nearest_secondary_dist: float | None = None,
        nearest_rail_dist: float | None = None,
        nearest_school_dist: float | None = None,
        nearest_hospital_dist: float | None = None,
        nearest_commercial_dist: float | None = None,
        nearest_restaurant_dist: float | None = None,
    ) -> dict[str, int]:
        road_impact = (
            self.weighted_road_score("expressway", nearest_expressway_dist)
            + self.weighted_road_score("arterial", nearest_arterial_dist)
            + self.weighted_road_score("secondary", nearest_secondary_dist)
        )
        rail_impact = self.band_score(nearest_rail_dist, self.cfg.rail_bands)
        school_impact = self.band_score(nearest_school_dist, self.cfg.school_bands)
        hospital_impact = self.band_score(nearest_hospital_dist, self.cfg.hospital_bands)
        commercial_impact = self.band_score(nearest_commercial_dist, self.cfg.commercial_bands)
        restaurant_impact = self.band_score(nearest_restaurant_dist, self.cfg.restaurant_bands)
        return {
            "road_impact": road_impact,
            "rail_impact": rail_impact,
            "school_impact": school_impact,
            "hospital_impact": hospital_impact,
            "commercial_impact": commercial_impact,
            "restaurant_impact": restaurant_impact,
            "external_environment_impact": round(
                road_impact
                + rail_impact
                + school_impact
                + hospital_impact
                + commercial_impact
                + restaurant_impact
            ),
        }

    def building_adjustment(self, build_year: Any) -> int:
        year = self._coerce_float(build_year)
        if year is None:
            return 0

        # 2025 后：按你要求提升静音要求权重
        # 这里不宣称“官方直接给分”，只是模型层的 v1 启动参数。
        if year >= 2025:
            return 5
        # “第四代住宅”在没有稳定官方字段前，先用新建年份做代理。
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
        # 兼容旧页面：当前 app 仍直接传 adjustment_score 数值进来。
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

        说明：
        - standard_base_score：标准基准分
        - zone_adjust：空间缓冲项/楼栋位置调整
        - noise_penalty：当前页面已经汇总好的外部环境影响值
        - far_ratio：容积率代理值
        - build_year：楼龄/新建标准代理值
        """
        base_score = int(round(self._coerce_float(standard_base_score) or self.cfg.standard_base_score))
        zone_adjust_value = self.normalize_zone_adjustment(zone_adjust)
        build_bonus = self.building_adjustment(build_year)
        density_adjustment_value = self.density_adjustment(far_ratio)
        density_penalty = abs(density_adjustment_value)
        external_environment_impact = int(round(self._coerce_float(noise_penalty) or 0))

        final_score = self.clamp_score(
            base_score
            + zone_adjust_value
            + build_bonus
            + min(density_adjustment_value, 0)
            + max(density_adjustment_value, 0)
            - external_environment_impact
        )
        return {
            "base_score": base_score,
            "zone_adjust": zone_adjust_value,
            "build_bonus": build_bonus,
            "density_adjustment": density_adjustment_value,
            "density_penalty": density_penalty,
            "noise_penalty": external_environment_impact,
            "external_environment_impact": external_environment_impact,
            "final_score": final_score,
        }
