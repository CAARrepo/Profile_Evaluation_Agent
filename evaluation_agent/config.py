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

# Must stay identical to intake_agent.config.OLLAMA_NUM_CTX: Ollama keeps one
# runner per (model, context) pair, so a mismatch makes it unload and reload the
# model on every switch between the two agents.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))

# Non-streaming requests, so this covers the whole generation. Kept in step with
# intake_agent.config.OLLAMA_TIMEOUT.
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "1800"))
OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))
OLLAMA_NUM_GPU = int(os.environ.get("OLLAMA_NUM_GPU", "-1"))

KB_FILENAMES = {
    "O-1A": "O1A_evaluation_knowledge_base.json",
    "EB-1A": "EB1A_evaluation_knowledge_base.json",
    "EB-2 NIW": "EB2_NIW_evaluation_knowledge_base.json",
}

# Each category owns a folder under knowledge_base/. The matching
# "<home>_original" folder is an untouched archive: read it only as a fallback,
# never write to it.
KB_HOMES = {
    "O-1A": "O1A_Knowledge_Base",
    "EB-1A": "EB1A_Knowledge_Base",
    "EB-2 NIW": "EB2NIW_Knowledge_Base",
}
KB_ARCHIVE_SUFFIX = "_original"

# Layout inside a category folder.
CONTROLLING_SOURCES_DIRNAME = "01_Controlling_Sources"
CFR_DIRNAME = "CFR"
POLICY_MANUAL_DIRNAME = "USCIS_Policy_Manual"
AAO_DECISIONS_DIRNAME = "02_AAO_Non_Precedent_Decisions"
AAO_CATALOG_RELPATH = Path("00_Catalog") / "aao_decisions_catalog.json"
AAO_CRITERION_INDEX_RELPATH = Path("00_Catalog") / "criterion_index.json"

# Every AAO decision in 02_AAO_Non_Precedent_Decisions/ must be surfaced with
# this caveat. Matter of Dhanasar is precedent and is excluded from that folder.
AAO_AUTHORITY_LABEL = "AAO non-precedent—non-binding"

DEFAULT_DISCLAIMER = (
    "Preliminary AI-assisted profile assessment only. "
    "Final eligibility requires attorney review."
)

# Local Ollama (override with EVAL_OLLAMA_MODEL / OLLAMA_MODEL / OLLAMA_HOST)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("EVAL_OLLAMA_MODEL") or os.environ.get(
    "OLLAMA_MODEL", "qwen2.5:7b-instruct"
)
