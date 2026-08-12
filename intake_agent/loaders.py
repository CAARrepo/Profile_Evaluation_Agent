"""Load lead, questionnaire, and document inputs for one evaluation case."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional

from .config import LEAD_DOCUMENTS_DIR, QUESTIONNAIRE_CSV, USER_INFO_CSV
from .extractors import extract_text
from .schema import CaseBundle


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_leads(path: Path = USER_INFO_CSV) -> list[dict[str, str]]:
    return _read_csv_dicts(path)


def load_questionnaires(path: Path = QUESTIONNAIRE_CSV) -> dict[str, dict[str, Any]]:
    """Map lead_id -> parsed questionnaire answers JSON."""
    out: dict[str, dict[str, Any]] = {}
    for row in _read_csv_dicts(path):
        lead_id = row.get("lead_id") or ""
        raw = row.get("answers") or "{}"
        try:
            answers = json.loads(raw)
        except json.JSONDecodeError:
            answers = {"_parse_error": True, "raw": raw}
        out[lead_id] = {
            "id": row.get("id"),
            "lead_id": lead_id,
            "answers": answers,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
    return out


def list_o1_leads(path: Path = USER_INFO_CSV) -> list[dict[str, str]]:
    """Leads tagged O1_VISA in export data (evaluated as O-1A in this pipeline)."""
    return [r for r in load_leads(path) if (r.get("immigration_category") or "").upper() == "O1_VISA"]


def _hydrate_onedrive_file(path: Path) -> None:
    """Best-effort: touch cloud-only OneDrive placeholders so content downloads."""
    try:
        if path.is_file():
            with path.open("rb") as f:
                f.read(1)
    except OSError:
        pass


def collect_lead_documents(lead_id: str, docs_root: Path = LEAD_DOCUMENTS_DIR) -> list[Path]:
    lead_dir = docs_root / lead_id
    if not lead_dir.exists():
        return []
    files: list[Path] = []
    for p in lead_dir.rglob("*"):
        if not p.is_file():
            continue
        # Skip macOS junk / zero-byte cloud stubs after failed hydrate
        if p.name.startswith("."):
            continue
        _hydrate_onedrive_file(p)
        if p.stat().st_size <= 0:
            continue
        files.append(p)
    return sorted(files)


def extract_documents(paths: list[Path], max_chars: Optional[int] = None) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in paths:
        try:
            text = extract_text(path)
        except Exception as exc:  # noqa: BLE001 - keep case moving
            text = f"[extraction_failed: {exc}]"
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]..."
        rel = str(path.relative_to(LEAD_DOCUMENTS_DIR)) if LEAD_DOCUMENTS_DIR in path.parents else path.name
        docs.append(
            {
                "path": str(path),
                "relative_path": rel,
                "filename": path.name,
                "text": text,
            }
        )
    return docs


def load_case(
    lead_id: str,
    *,
    user_csv: Path = USER_INFO_CSV,
    questionnaire_csv: Path = QUESTIONNAIRE_CSV,
    docs_root: Path = LEAD_DOCUMENTS_DIR,
    max_doc_chars: Optional[int] = None,
) -> CaseBundle:
    leads = {r["id"]: r for r in load_leads(user_csv)}
    if lead_id not in leads:
        raise KeyError(f"Lead not found in User_Info.csv: {lead_id}")

    questionnaires = load_questionnaires(questionnaire_csv)
    q = questionnaires.get(lead_id)

    paths = collect_lead_documents(lead_id, docs_root)
    docs = extract_documents(paths, max_chars=max_doc_chars)

    return CaseBundle(lead=leads[lead_id], questionnaire=q, document_texts=docs)


def pick_sample_o1_lead(
    *,
    prefer_completed: bool = True,
    require_docs: bool = True,
) -> Optional[str]:
    """Choose a good O-1A lead for local testing."""
    questionnaires = load_questionnaires()
    for lead in list_o1_leads():
        lead_id = lead["id"]
        if prefer_completed and (lead.get("questionnaire_status") or "").lower() != "completed":
            continue
        if lead_id not in questionnaires:
            continue
        if require_docs and not collect_lead_documents(lead_id):
            continue
        return lead_id
    # Fallback: any O-1A lead with questionnaire
    for lead in list_o1_leads():
        if lead["id"] in questionnaires:
            if require_docs and not collect_lead_documents(lead["id"]):
                continue
            return lead["id"]
    return None
