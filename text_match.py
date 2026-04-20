from __future__ import annotations

import difflib


DROP_TOKENS = [
    "北京市", "北京", "小区", "社区", "家园", "一期", "二期", "三期", "四期", "五期",
    "号楼", "幢", "栋", "单元", "室", "座",
]


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    value = str(text).strip().lower().replace(" ", "")
    for token in DROP_TOKENS:
        value = value.replace(token, "")
    return value


def similarity(a: str | None, b: str | None) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()
