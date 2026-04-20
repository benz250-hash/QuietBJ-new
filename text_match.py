from __future__ import annotations
import difflib
import re

DROP_TOKENS = ["北京市","北京","小区","社区","家园","一期","二期","三期","四期","五期"]
DETAIL_PATTERNS = [
    r"\d+号楼", r"\d+栋", r"\d+幢", r"\d+座", r"\d+单元", r"\d+室", r"\d+层",
    r"楼栋", r"#\d+",
]


def strip_unit_details(text: str | None) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    for pattern in DETAIL_PATTERNS:
        value = re.sub(pattern, "", value)
    value = re.sub(r"\s+", "", value)
    return value


def normalize_text(text: str | None) -> str:
    value = strip_unit_details(text).lower().replace(" ", "")
    for token in DROP_TOKENS:
        value = value.replace(token, "")
    return value


def similarity(a: str | None, b: str | None) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()
