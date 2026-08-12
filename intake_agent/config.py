"""Runtime configuration for the Intake Agent."""

from __future__ import annotations

import os
from pathlib import Path

# Default: workspace root; input data lives under datasets/
ROOT_DIR = Path(os.environ.get("INTAKE_ROOT", Path(__file__).resolve().parent.parent))
DATASETS_DIR = Path(os.environ.get("INTAKE_DATASETS", ROOT_DIR / "datasets"))

USER_INFO_CSV = DATASETS_DIR / "User_Info.csv"
QUESTIONNAIRE_CSV = DATASETS_DIR / "Detailed_questionarie.csv"
LEAD_DOCUMENTS_DIR = DATASETS_DIR / "lead-documents"
OUTPUT_DIR = ROOT_DIR / "intake_outputs"

# Best local model for RTX 4050 6GB: Qwen2.5-7B-Instruct (strong JSON / extraction)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

# Truncate very long resume text so the prompt fits local context
MAX_DOCUMENT_CHARS = int(os.environ.get("INTAKE_MAX_DOC_CHARS", "14000"))
MAX_QUESTIONNAIRE_CHARS = int(os.environ.get("INTAKE_MAX_Q_CHARS", "12000"))
