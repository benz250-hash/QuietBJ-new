from __future__ import annotations

from typing import Any


class BuildingEngine:
    """预留给未来楼栋级规则。当前版本默认不额外修正。"""

    def get_adjustment(self, building_row: dict[str, Any] | None = None) -> int:
        return 0
