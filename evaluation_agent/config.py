"""Runtime configuration for the Evaluation Agent."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(os.environ.get("INTAKE_ROOT", Path(__file__).resolve().parent.parent))

# Prefer knowledge_base/; also accept project-root copies if present.
KNOWLEDGE_BASE_DIR = Path(
    os.environ.get("EVAL_KB_DIR", ROOT_DIR / "knowledge_base")
)

INTAKE_OUTPUT_DIR = ROOT_DIR / "intake_outputs"
EVAL_OUTPUT_DIR = ROOT_DIR / "evaluation_outputs"

KB_FILENAMES = {
    "O-1A": "O1A_evaluation_knowledge_base.json",
    "EB-1A": "EB1A_evaluation_knowledge_base.json",
    "EB-2 NIW": "EB2_NIW_evaluation_knowledge_base.json",
}

DEFAULT_DISCLAIMER = (
    "Preliminary AI-assisted profile assessment only. "
    "Final eligibility requires attorney review."
)

# Local Ollama (override with EVAL_OLLAMA_MODEL / OLLAMA_MODEL / OLLAMA_HOST)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("EVAL_OLLAMA_MODEL") or os.environ.get(
    "OLLAMA_MODEL", "qwen2.5:7b-instruct"
)
