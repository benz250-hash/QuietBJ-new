from __future__ import annotations

from typing import Any

import pandas as pd


class ZoneRepository:
    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath).fillna("")

    def get_by_community(self, community_code: str) -> list[dict[str, Any]]:
        rows = self.df[self.df["community_code"].astype(str) == str(community_code)]
        if rows.empty:
            return []
        return rows.to_dict(orient="records")

    def get_zone(self, community_code: str, zone_code: str) -> dict[str, Any] | None:
        rows = self.df[
            (self.df["community_code"].astype(str) == str(community_code))
            & (self.df["zone_code"].astype(str) == str(zone_code))
        ]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()
