"""Runtime configuration for the Report Agent."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(os.environ.get("INTAKE_ROOT", Path(__file__).resolve().parent.parent))

EVAL_OUTPUT_DIR = ROOT_DIR / "evaluation_outputs"
INTAKE_OUTPUT_DIR = ROOT_DIR / "intake_outputs"
REPORT_OUTPUT_DIR = ROOT_DIR / "report_outputs"
STATIC_COPY_DIR = Path(__file__).resolve().parent / "static_copy"

DEFAULT_DISCLAIMER = (
    "This is a preliminary AI-assisted profile assessment only. "
    "It is not legal advice, not an attorney opinion, and not a determination of "
    "eligibility or petition approval. An immigration attorney should review before "
    "any filing strategy decisions."
)

RATING_PLAIN = {
    "very_strong": "Very Strong (preliminary)",
    "strong": "Strong (preliminary)",
    "promising": "Promising (preliminary)",
    "developing": "Developing (preliminary)",
    "insufficient_information": "Insufficient Information (preliminary)",
}
