"""Runtime configuration for the Report Agent."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(os.environ.get("INTAKE_ROOT", Path(__file__).resolve().parent.parent))

EVAL_OUTPUT_DIR = ROOT_DIR / "evaluation_outputs"
INTAKE_OUTPUT_DIR = ROOT_DIR / "intake_outputs"
REPORT_OUTPUT_DIR = ROOT_DIR / "report_outputs"
STATIC_COPY_DIR = Path(__file__).resolve().parent / "static_copy"

# Same Ollama runner as intake/evaluation so the model is not unloaded between agents.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("EVAL_OLLAMA_MODEL") or os.environ.get(
    "OLLAMA_MODEL", "qwen2.5:7b-instruct"
)
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "1800"))
OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))
OLLAMA_NUM_GPU = int(os.environ.get("OLLAMA_NUM_GPU", "-1"))

DEFAULT_DISCLAIMER = (
    "This is a preliminary AI-assisted profile assessment only. "
    "It is not legal advice, not an attorney opinion, and not a determination of "
    "eligibility or petition approval. An immigration attorney should review before "
    "any filing strategy decisions."
)

O1A_CLIENT_DISCLAIMER = (
    "This report is based on preliminary information and documents provided by the applicant. "
    "A final determination regarding the applicant’s eligibility can be made only by an "
    "immigration attorney after a full review of the complete record."
)

O1A_CHALLENGING_CRITERIA = {
    "o1a_awards",
    "o1a_membership",
    "o1a_original_contributions",
}

O1A_CHALLENGING_NOTE = (
    "This is one of the most challenging O-1A criteria. The attorney typically recommends "
    "targeting easier criteria, such as published material or judging the work of others. "
    "However, any evidence submitted under this criterion that does not strictly meet USCIS "
    "requirements may still be considered as part of the totality of the evidence."
)

O1A_DEFAULT_PRIORITY_OPPORTUNITIES = [
    "Published material — this criterion can typically be prepared in a relatively short time.",
    "Judging the work of others — this criterion can typically be prepared in a relatively short time.",
]

# Williams Law palette from the 08/25/2026 O-1A report feedback.
BRAND_CHARCOAL = "37343F"
BRAND_NAVY = "121223"
BRAND_PAPER = "F4F4F9"
BRAND_LAVENDER = "E4E2EF"

RATING_PLAIN = {
    "very_strong": "Very Strong (preliminary)",
    "strong": "Strong (preliminary)",
    "promising": "Promising (preliminary)",
    "developing": "Developing (preliminary)",
    "insufficient_information": "Insufficient Information (preliminary)",
}
