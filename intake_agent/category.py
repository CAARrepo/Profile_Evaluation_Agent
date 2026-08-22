"""Map lead immigration_category values to O-1A, EB-1A, or EB-2 NIW."""

from __future__ import annotations

from typing import Any

SUPPORTED_CATEGORIES = ("O-1A", "EB-1A", "EB-2 NIW")

_O1A_TOKENS = {
    "O1_VISA",
    "O1A",
    "O-1A",
    "O1",
    "O-1",
    "O1A_VISA",
}
_EB1A_TOKENS = {
    "EB1A",
    "EB-1A",
    "EB1_A",
    "EB_1A",
    "EB1A_VISA",
    "EB1_VISA",
}
_NIW_TOKENS = {
    "EB2_NIW",
    "EB-2 NIW",
    "EB2-NIW",
    "NIW",
    "EB2NIW",
    "EB_2_NIW",
    "EB2_VISA",
}


def _compact(raw: str) -> str:
    return raw.strip().upper().replace(" ", "_").replace("-", "_")


def detect_intake_category(lead: dict[str, Any] | str | None) -> str:
    """Return 'O-1A', 'EB-1A', or 'EB-2 NIW', or '' if unknown."""
    if isinstance(lead, dict):
        raw = str(lead.get("immigration_category") or "")
    else:
        raw = str(lead or "")
    compact = _compact(raw)
    if not compact:
        return ""
    if compact in {_compact(t) for t in _O1A_TOKENS} or compact.startswith("O1"):
        return "O-1A"
    if compact in {_compact(t) for t in _EB1A_TOKENS} or "EB1A" in compact:
        return "EB-1A"
    if compact in {_compact(t) for t in _NIW_TOKENS} or "NIW" in compact:
        return "EB-2 NIW"
    return ""
