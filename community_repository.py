from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd
from text_match import normalize_text, similarity, strip_unit_details

@dataclass
class CommunityMatch:
    row: dict[str, Any]
    score: float
    source: str
    query_used: str = ""

class CommunityRepository:
    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath).fillna("")

    def search(self, query: str, district: str = "", threshold: float = 0.74) -> CommunityMatch | None:
        cleaned = strip_unit_details(query)
        norm_query = normalize_text(cleaned)
        norm_district = normalize_text(district)
        if not norm_query:
            return None
        best = None
        best_score = 0.0
        best_source = ""
        for _, row in self.df.iterrows():
            row_dict = row.to_dict()
            candidates = [(str(row_dict.get('community_name','')), 'community_name')]
            address = str(row_dict.get('address',''))
            if address:
                candidates.append((address, 'address'))
            aliases = str(row_dict.get('aliases',''))
            if aliases:
                candidates.extend((x.strip(),'alias') for x in aliases.split('|') if x.strip())
            row_district = normalize_text(str(row_dict.get('district','')))
            for cand, source in candidates:
                nc = normalize_text(cand)
                if not nc:
                    continue
                if nc == norm_query:
                    return CommunityMatch(row=row_dict, score=1.0, source=source, query_used=cleaned)
                s = similarity(norm_query, nc)
                if norm_query in nc or nc in norm_query:
                    s += 0.06
                if norm_district and row_district == norm_district:
                    s += 0.05
                if s > best_score:
                    best = row_dict
                    best_score = s
                    best_source = source
        if best is not None and best_score >= threshold:
            return CommunityMatch(row=best, score=best_score, source=best_source, query_used=cleaned)
        return None
