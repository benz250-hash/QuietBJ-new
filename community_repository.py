from __future__ import annotations

from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
from typing import Any

import pandas as pd

from text_match import normalize_text, similarity


@dataclass
class CommunityMatch:
    row: dict[str, Any]
    score: float
    source: str
    query_used: str = ""
    distance_km: float | None = None


class CommunityRepository:
    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath).fillna("")

    def all_names(self) -> list[str]:
        return self.df["community_name"].astype(str).tolist()

    def _candidate_fields(self, row: dict[str, Any]) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        community_name = str(row.get("community_name", ""))
        address = str(row.get("address", ""))
        aliases = str(row.get("aliases", ""))
        district = str(row.get("district", ""))
        subdistrict = str(row.get("subdistrict", ""))

        if community_name:
            candidates.append((community_name, "community_name"))
        if address:
            candidates.append((address, "address"))
        if aliases:
            candidates.extend((part.strip(), "alias") for part in aliases.split("|") if part.strip())
        if district and community_name:
            candidates.append((f"{district}{community_name}", "district+community"))
        if district and subdistrict and community_name:
            candidates.append((f"{district}{subdistrict}{community_name}", "district+subdistrict+community"))
        return candidates

    def _distance_km(self, row: dict[str, Any], location: tuple[float, float] | None) -> float | None:
        if location is None:
            return None
        try:
            lon1, lat1 = location
            lon2 = float(row.get("longitude", ""))
            lat2 = float(row.get("latitude", ""))
        except Exception:
            return None
        r = 6371.0
        dlon = radians(lon2 - lon1)
        dlat = radians(lat2 - lat1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return r * c

    def search(
        self,
        query: str,
        threshold: float = 0.58,
        district: str = "",
        subdistrict: str = "",
        location: tuple[float, float] | None = None,
    ) -> CommunityMatch | None:
        norm_query = normalize_text(query)
        if not norm_query:
            return None

        norm_district = normalize_text(district)
        norm_subdistrict = normalize_text(subdistrict)
        best_match: CommunityMatch | None = None

        for _, row in self.df.iterrows():
            row_dict = row.to_dict()
            best_row_score = 0.0
            best_source = ""

            for candidate, source in self._candidate_fields(row_dict):
                norm_candidate = normalize_text(candidate)
                if not norm_candidate:
                    continue
                if norm_candidate == norm_query:
                    return CommunityMatch(row=row_dict, score=1.0, source=source, query_used=query)

                score = similarity(norm_query, norm_candidate)
                if norm_query in norm_candidate or norm_candidate in norm_query:
                    score += 0.08

                row_district = normalize_text(str(row_dict.get("district", "")))
                row_subdistrict = normalize_text(str(row_dict.get("subdistrict", "")))
                if norm_district and row_district == norm_district:
                    score += 0.08
                if norm_subdistrict and row_subdistrict == norm_subdistrict:
                    score += 0.05

                if score > best_row_score:
                    best_row_score = score
                    best_source = source

            distance_km = self._distance_km(row_dict, location)
            if distance_km is not None:
                if distance_km <= 0.35:
                    best_row_score += 0.18
                elif distance_km <= 0.8:
                    best_row_score += 0.14
                elif distance_km <= 1.5:
                    best_row_score += 0.10
                elif distance_km <= 3:
                    best_row_score += 0.06
                elif distance_km <= 6:
                    best_row_score += 0.03
                elif distance_km >= 15:
                    best_row_score -= 0.05

            if best_match is None or best_row_score > best_match.score:
                best_match = CommunityMatch(
                    row=row_dict,
                    score=best_row_score,
                    source=best_source or "context",
                    query_used=query,
                    distance_km=distance_km,
                )

        if best_match and best_match.score >= threshold:
            return best_match
        return None

    def get_by_code(self, community_code: str) -> dict[str, Any] | None:
        rows = self.df[self.df["community_code"].astype(str) == str(community_code)]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()
