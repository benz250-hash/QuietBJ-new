from __future__ import annotations
from typing import Any
from config import DEFAULT_BASE_SCORE

class ScoreEngine:
    def density_penalty(self, far_ratio: Any) -> int:
        try:
            far = float(far_ratio)
        except Exception:
            return 0
        if far > 3.0:
            return 6
        if far > 2.2:
            return 3
        if far < 1.5:
            return -2
        return 0

    def building_bonus(self, build_year: Any) -> int:
        try:
            year = int(float(build_year))
        except Exception:
            return 0
        if year >= 2015:
            return 3
        if year >= 2005:
            return 1
        return 0

    def clamp(self, score: int) -> int:
        return max(50, min(95, round(score)))

    def final_score(self, base_score: int, zone_adjust: int, noise_penalty: int, far_ratio: Any, build_year: Any) -> dict[str, int]:
        density_penalty = self.density_penalty(far_ratio)
        build_bonus = self.building_bonus(build_year)
        raw = base_score + zone_adjust + build_bonus - density_penalty - noise_penalty
        return {
            'base_score': base_score,
            'zone_adjust': zone_adjust,
            'build_bonus': build_bonus,
            'density_penalty': density_penalty,
            'noise_penalty': noise_penalty,
            'final_score': self.clamp(raw),
        }
