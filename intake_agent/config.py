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

# Must stay identical to evaluation_agent.config.OLLAMA_NUM_CTX: Ollama keeps one
# runner per (model, context) pair, so a mismatch makes it unload and reload the
# model on every switch between the two agents.
# Sized from tools/measure_prompt_tokens.py — the intake prompt alone measures
# ~8.1k tokens, so 8192 would truncate it before the profile is even generated.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))

# Requests are non-streaming, so this covers the whole generation, not just the
# first byte. When the model is partly offloaded to CPU it generates at roughly
# 11 tok/s, and the intake profile is ~3k tokens, so 300s was below the real
# cost of a single call and every intake died after three retries.
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "1800"))

# Per-file LLM window (head + tail). Every PDF is extracted; there is no
# all-files total omit. The old 24k total cap dropped later PDFs.
MAX_DOCUMENT_CHARS = int(os.environ.get("INTAKE_MAX_DOC_CHARS", "16000"))
MAX_TOTAL_DOCUMENT_CHARS = int(os.environ.get("INTAKE_MAX_TOTAL_DOC_CHARS", "0"))
SOURCE_EXTRACT_CHARS = int(os.environ.get("INTAKE_SOURCE_EXTRACT_CHARS", "12000"))
OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))
# -1 = as many layers as fit on GPU; leftover layers run on CPU.
OLLAMA_NUM_GPU = int(os.environ.get("OLLAMA_NUM_GPU", "-1"))
MAX_QUESTIONNAIRE_CHARS = int(os.environ.get("INTAKE_MAX_Q_CHARS", "12000"))
QUESTIONNAIRE_STRING_LIMIT = int(os.environ.get("INTAKE_Q_STRING_LIMIT", "600"))

# Best-effort fetch of applicant-provided URLs (LinkedIn/Scholar/media/etc.)
URL_FETCH_ENABLED = os.environ.get("INTAKE_URL_FETCH", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
URL_FETCH_TIMEOUT = float(os.environ.get("INTAKE_URL_FETCH_TIMEOUT", "20"))
URL_FETCH_MAX_CHARS = int(os.environ.get("INTAKE_URL_FETCH_MAX_CHARS", "12000"))
URL_FETCH_MAX_URLS = int(os.environ.get("INTAKE_URL_FETCH_MAX_URLS", "15"))
