from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from text_match import normalize_text, similarity


@dataclass
class CommunityMatch:
    row: dict[str, Any]
    score: float
    source: str


class CommunityRepository:
    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath).fillna("")

    def all_names(self) -> list[str]:
        return self.df["community_name"].astype(str).tolist()

    def search(self, query: str, threshold: float = 0.58) -> CommunityMatch | None:
        norm_query = normalize_text(query)
        if not norm_query:
            return None

        best_row = None
        best_score = 0.0
        best_source = ""

        for _, row in self.df.iterrows():
            candidates: list[tuple[str, str]] = []
            community_name = str(row.get("community_name", ""))
            address = str(row.get("address", ""))
            aliases = str(row.get("aliases", ""))

            if community_name:
                candidates.append((community_name, "community_name"))
            if address:
                candidates.append((address, "address"))
            if aliases:
                candidates.extend((part.strip(), "alias") for part in aliases.split("|") if part.strip())

            for candidate, source in candidates:
                norm_candidate = normalize_text(candidate)
                if not norm_candidate:
                    continue
                if norm_candidate == norm_query:
                    return CommunityMatch(row=row.to_dict(), score=1.0, source=source)
                contains_bonus = 0.06 if (norm_query in norm_candidate or norm_candidate in norm_query) else 0.0
                score = similarity(norm_query, norm_candidate) + contains_bonus
                if score > best_score:
                    best_score = score
                    best_row = row.to_dict()
                    best_source = source

        if best_row and best_score >= threshold:
            return CommunityMatch(row=best_row, score=best_score, source=best_source)
        return None

    def get_by_code(self, community_code: str) -> dict[str, Any] | None:
        rows = self.df[self.df["community_code"].astype(str) == str(community_code)]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()
