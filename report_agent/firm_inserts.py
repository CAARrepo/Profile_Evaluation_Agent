"""Load static firm copy for the client report (rates, case study, timeline).

Source: report_agent/static_copy/AI Initial Evaluation Agent Updates 08182026.docx
The Word file is the attorney original. Runtime reads firm_inserts.json only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import STATIC_COPY_DIR

INSERTS_PATH = STATIC_COPY_DIR / "firm_inserts.json"

_CATEGORY_ALIASES = {
    "o-1a": "O-1A",
    "o1a": "O-1A",
    "o1-a": "O-1A",
    "eb-1a": "EB-1A",
    "eb1a": "EB-1A",
    "eb1-a": "EB-1A",
    "eb-2 niw": "EB-2 NIW",
    "eb2 niw": "EB-2 NIW",
    "eb-2niw": "EB-2 NIW",
    "eb2niw": "EB-2 NIW",
    "niw": "EB-2 NIW",
}


def normalize_category(visa_category: str) -> str:
    key = " ".join(str(visa_category or "").strip().lower().replace("_", " ").split())
    return _CATEGORY_ALIASES.get(key, str(visa_category or "").strip())


@lru_cache(maxsize=1)
def _load_all() -> dict[str, Any]:
    if not INSERTS_PATH.is_file():
        return {}
    return json.loads(INSERTS_PATH.read_text(encoding="utf-8"))


def load_category_inserts(visa_category: str) -> dict[str, Any]:
    """Return static blocks for one visa category, or empty dict if unknown."""
    data = _load_all()
    categories = data.get("categories") or {}
    key = normalize_category(visa_category)
    block = categories.get(key)
    if not isinstance(block, dict):
        return {}
    disclosure = str(data.get("disclosure") or "").strip()
    image_rel = str(block.get("case_study_image") or "").strip()
    image_path = (STATIC_COPY_DIR / image_rel).resolve() if image_rel else None
    return {
        "approval_rate_line": str(block.get("approval_rate_line") or "").strip(),
        "disclosure": disclosure,
        "case_study_heading": str(block.get("case_study_heading") or "").strip(),
        "case_study_title": str(block.get("case_study_title") or "").strip(),
        "case_study_paragraphs": [
            str(p).strip() for p in (block.get("case_study_paragraphs") or []) if str(p).strip()
        ],
        "case_study_image": str(image_path) if image_path and image_path.is_file() else "",
        "case_study_image_caption": str(block.get("case_study_image_caption") or "").strip(),
        "timeline_heading": str(block.get("timeline_heading") or "").strip(),
        "timeline_items": [
            str(item).strip() for item in (block.get("timeline_items") or []) if str(item).strip()
        ],
    }
