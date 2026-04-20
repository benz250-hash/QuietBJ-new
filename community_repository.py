from __future__ import annotations

from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
from typing import Any

import pandas as pd

from text_match import normalize_text, similarity, strip_unit_details


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
        community_name = str(row.get("community_name", "")).strip()
        address = str(row.get("address", "")).strip()
        aliases = str(row.get("aliases", "")).strip()
        district = str(row.get("district", "")).strip()
        subdistrict = str(row.get("subdistrict", "")).strip()

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

    def _exact_match(self, query: str) -> CommunityMatch | None:
        q = normalize_text(query)
        q_raw = strip_unit_details(query)
        for _, row in self.df.iterrows():
            row_dict = row.to_dict()
            for candidate, source in self._candidate_fields(row_dict):
                if normalize_text(candidate) == q:
                    return CommunityMatch(row=row_dict, score=1.0, source=source, query_used=q_raw)
        return None

    def search(
        self,
        query: str,
        threshold: float = 0.78,
        district: str = "",
        subdistrict: str = "",
        location: tuple[float, float] | None = None,
        max_distance_km: float = 1.2,
    ) -> CommunityMatch | None:
        cleaned_query = strip_unit_details(query)
        norm_query = normalize_text(cleaned_query)
        if not norm_query:
            return None

        exact = self._exact_match(cleaned_query)
        if exact:
            return exact

        norm_district = normalize_text(district)
        norm_subdistrict = normalize_text(subdistrict)
        best_match: CommunityMatch | None = None

        for _, row in self.df.iterrows():
            row_dict = row.to_dict()
            row_best_score = 0.0
            row_best_source = ""
            row_district = normalize_text(str(row_dict.get("district", "")))
            row_subdistrict = normalize_text(str(row_dict.get("subdistrict", "")))

            for candidate, source in self._candidate_fields(row_dict):
                norm_candidate = normalize_text(candidate)
                if not norm_candidate:
                    continue

                score = similarity(norm_query, norm_candidate)
                if norm_query in norm_candidate or norm_candidate in norm_query:
                    score += 0.05
                if len(norm_query) >= 3 and len(norm_candidate) >= 3 and norm_query[:3] == norm_candidate[:3]:
                    score += 0.04
                if norm_district and row_district == norm_district:
                    score += 0.06
                elif norm_district and row_district and row_district != norm_district:
                    score -= 0.12
                if norm_subdistrict and row_subdistrict == norm_subdistrict:
                    score += 0.04

                if score > row_best_score:
                    row_best_score = score
                    row_best_source = source

            distance_km = self._distance_km(row_dict, location)
            if distance_km is not None:
                if distance_km <= 0.35:
                    row_best_score += 0.18
                elif distance_km <= 0.8:
                    row_best_score += 0.10
                elif distance_km <= max_distance_km:
                    row_best_score += 0.04
                else:
                    row_best_score -= 0.50

            # Reject obvious false positives when neither name nor district is strong enough.
            if row_best_score < threshold:
                continue
            if distance_km is not None and distance_km > max_distance_km:
                continue
            if norm_district and row_district and row_district != norm_district and row_best_score < 0.92:
                continue

            candidate_match = CommunityMatch(
                row=row_dict,
                score=row_best_score,
                source=row_best_source or "context",
                query_used=cleaned_query,
                distance_km=distance_km,
            )
            if best_match is None or candidate_match.score > best_match.score:
                best_match = candidate_match

        return best_match

    def get_by_code(self, community_code: str) -> dict[str, Any] | None:
        rows = self.df[self.df["community_code"].astype(str) == str(community_code)]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()
