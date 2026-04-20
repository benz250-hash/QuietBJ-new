from __future__ import annotations
from typing import Any
import pandas as pd

class ZoneRepository:
    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath).fillna("")

    def get_by_community(self, community_code: str) -> list[dict[str, Any]]:
        rows = self.df[self.df['community_code'].astype(str) == str(community_code)]
        return rows.to_dict(orient='records') if not rows.empty else []
