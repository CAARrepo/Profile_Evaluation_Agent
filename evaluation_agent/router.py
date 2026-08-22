"""Detect visa category and route to the correct evaluator."""

from __future__ import annotations

from typing import Any

from .schema import VisaCategory

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
}
_NIW_TOKENS = {
    "EB2_NIW",
    "EB-2 NIW",
    "EB2-NIW",
    "NIW",
    "EB2NIW",
    "EB_2_NIW",
}


def detect_visa_category(intake: dict[str, Any], override: str | None = None) -> VisaCategory:
    if override:
        return normalize_category(override)

    identity = intake.get("identity") or {}
    raw = (
        intake.get("visa_category")
        or identity.get("immigration_category")
        or intake.get("immigration_category")
        or ""
    )
    return normalize_category(str(raw))


def normalize_category(raw: str) -> VisaCategory:
    token = raw.strip().upper().replace(" ", "_")
    compact = token.replace("-", "_")

    if compact in {t.replace("-", "_") for t in _O1A_TOKENS} or compact.startswith("O1"):
        return "O-1A"
    if compact in {t.replace("-", "_") for t in _EB1A_TOKENS} or "EB1A" in compact:
        return "EB-1A"
    if compact in {t.replace("-", "_") for t in _NIW_TOKENS} or "NIW" in compact:
        return "EB-2 NIW"

    raise ValueError(
        f"Unsupported or unknown immigration category for evaluation: {raw!r}. "
        "Expected O-1A, EB-1A, or EB-2 NIW."
    )
