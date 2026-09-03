"""Load lead, questionnaire, and document inputs for one evaluation case."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

from .category import detect_intake_category
from .config import DATASETS_DIR, LEAD_DOCUMENTS_DIR, QUESTIONNAIRE_CSV, USER_INFO_CSV
from .extractors import extract_text
from .schema import CaseBundle

_SENSITIVE_LEAD_KEYS = {
    "password_hash",
    "password_reset_token",
    "password_reset_token_expires_at",
    "questionnaire_token",
}

_DOC_PRIORITY = (
    ("/resume/", 0),
    ("\\resume\\", 0),
    ("o1-award", 1),
    ("o1-internal-award", 1),
    ("o1-employer-award", 1),
    ("o1-peer-invite", 1),
    ("o1-peer-proof", 2),
    ("o1-w2", 2),
    ("o1-tax", 2),
    ("o1-article", 3),
    ("o1-peer-paper", 4),
)


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _csv_headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return [h.strip() for h in next(reader, [])]


def _sanitize_lead(row: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in row.items() if k not in _SENSITIVE_LEAD_KEYS and k != "answers"}


def discover_leads_csv(datasets_dir: Path = DATASETS_DIR) -> Path:
    if USER_INFO_CSV.exists():
        return USER_INFO_CSV
    for path in sorted(datasets_dir.glob("*.csv")):
        headers = set(_csv_headers(path))
        if "storage_path" in headers or "mime_type" in headers:
            continue
        if {"id", "first_name"} <= headers:
            return path
    return USER_INFO_CSV


def _parse_answers_cell(raw: str) -> dict[str, Any]:
    text = raw or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": True, "raw": text}
    return parsed if isinstance(parsed, dict) else {"_parse_error": True, "raw": text}


def load_leads(path: Path | None = None) -> list[dict[str, str]]:
    csv_path = path if path and path.exists() else discover_leads_csv()
    return [_sanitize_lead(row) for row in _read_csv_dicts(csv_path)]


def load_questionnaires(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Map lead_id -> parsed questionnaire answers JSON."""
    out: dict[str, dict[str, Any]] = {}
    questionnaire_path = path or (QUESTIONNAIRE_CSV if QUESTIONNAIRE_CSV.exists() else None)
    if questionnaire_path and questionnaire_path.exists():
        for row in _read_csv_dicts(questionnaire_path):
            lead_id = row.get("lead_id") or ""
            if not lead_id:
                continue
            out[lead_id] = {
                "id": row.get("id"),
                "lead_id": lead_id,
                "answers": _parse_answers_cell(row.get("answers") or "{}"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }

    leads_csv = discover_leads_csv()
    if leads_csv.exists():
        headers = set(_csv_headers(leads_csv))
        if "answers" in headers:
            for row in _read_csv_dicts(leads_csv):
                lead_id = row.get("id") or row.get("lead_id") or ""
                if not lead_id or lead_id in out:
                    continue
                if not (row.get("answers") or "").strip():
                    continue
                out[lead_id] = {
                    "id": row.get("id"),
                    "lead_id": lead_id,
                    "answers": _parse_answers_cell(row.get("answers") or "{}"),
                    "created_at": row.get("answers_created_at") or row.get("created_at"),
                    "updated_at": row.get("answers_updated_at") or row.get("updated_at"),
                }
    return out


def list_o1_leads(path: Path = USER_INFO_CSV) -> list[dict[str, str]]:
    """Leads tagged O-1A / O1_VISA in export data."""
    return [r for r in load_leads(path) if detect_intake_category(r) == "O-1A"]


def list_supported_leads(path: Path = USER_INFO_CSV) -> list[dict[str, str]]:
    """Leads tagged O-1A, EB-1A, or EB-2 NIW in export data."""
    return [r for r in load_leads(path) if detect_intake_category(r)]


def _hydrate_onedrive_file(path: Path) -> None:
    """Best-effort: touch cloud-only OneDrive placeholders so content downloads."""
    try:
        if path.is_file():
            with path.open("rb") as f:
                f.read(1)
    except OSError:
        pass


def _safe_zip_target(docs_root: Path, member_name: str, max_path: int = 240) -> Path:
    """Keep extracted paths under Windows MAX_PATH by shortening the filename."""
    rel = Path(member_name)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Unsafe zip member path: {member_name}")
    target = docs_root / rel
    if len(str(target)) <= max_path:
        return target
    parent = docs_root / rel.parent
    suffix = rel.suffix
    stem = rel.stem
    reserve = len(str(parent)) + len(suffix) + 2
    keep = max(24, max_path - reserve)
    return parent / f"{stem[:keep]}{suffix}"


def _ensure_lead_zip_extracted(lead_id: str, docs_root: Path = LEAD_DOCUMENTS_DIR) -> None:
    lead_dir = docs_root / lead_id
    if lead_dir.exists() and any(p.is_file() for p in lead_dir.rglob("*")):
        return
    zip_path = DATASETS_DIR / f"{lead_id}.zip"
    if not zip_path.exists():
        return
    docs_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            target = _safe_zip_target(docs_root, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dest:
                dest.write(src.read())


def _document_priority(path: Path) -> tuple[int, int]:
    text = str(path).lower()
    rank = 5
    for token, value in _DOC_PRIORITY:
        if token in text:
            rank = min(rank, value)
    return rank, path.stat().st_size if path.exists() else 0


def collect_lead_documents(lead_id: str, docs_root: Path = LEAD_DOCUMENTS_DIR) -> list[Path]:
    _ensure_lead_zip_extracted(lead_id, docs_root)
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
    seen_names: set[str] = set()
    unique: list[Path] = []
    for path in sorted(files, key=_document_priority):
        key = _logical_filename(path.name)
        if key in seen_names:
            continue
        seen_names.add(key)
        unique.append(path)
    return unique


_UUID_FILE_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-",
    re.I,
)


def _logical_filename(name: str) -> str:
    return _UUID_FILE_PREFIX.sub("", name).lower()


def extract_documents(paths: list[Path], max_chars: Optional[int] = None) -> list[dict[str, Any]]:
    """Extract text from every file. Never drop a PDF because of a total char cap."""
    docs: list[dict[str, Any]] = []
    for path in paths:
        try:
            text = extract_text(path)
        except Exception as exc:  # noqa: BLE001 - keep case moving
            text = f"[extraction_failed: {exc}]"
        stored = text
        if max_chars and max_chars > 0 and len(stored) > max_chars:
            stored = stored[:max_chars] + "\n...[truncated]..."
        rel = str(path.relative_to(LEAD_DOCUMENTS_DIR)) if LEAD_DOCUMENTS_DIR in path.parents else path.name
        docs.append(
            {
                "path": str(path),
                "relative_path": rel,
                "filename": path.name,
                "text": stored,
                "char_count": len(text),
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
        raise KeyError(f"Lead not found in lead export CSV: {lead_id}")

    questionnaires = load_questionnaires(questionnaire_csv if questionnaire_csv.exists() else None)
    q = questionnaires.get(lead_id)

    paths = collect_lead_documents(lead_id, docs_root)
    docs = extract_documents(paths, max_chars=max_doc_chars)

    return CaseBundle(lead=leads[lead_id], questionnaire=q, document_texts=docs)


def pick_sample_lead(
    *,
    prefer_completed: bool = True,
    require_docs: bool = True,
    visa_category: str | None = None,
) -> Optional[str]:
    """Choose a good supported lead for local testing (any of O-1A / EB-1A / EB-2 NIW)."""
    questionnaires = load_questionnaires()
    leads = list_supported_leads()
    if visa_category:
        leads = [r for r in leads if detect_intake_category(r) == visa_category]

    def _ok(lead: dict[str, str], *, require_docs_flag: bool) -> bool:
        lead_id = lead["id"]
        if lead_id not in questionnaires:
            return False
        if require_docs_flag and not collect_lead_documents(lead_id):
            return False
        return True

    if prefer_completed:
        for lead in leads:
            if (lead.get("questionnaire_status") or "").lower() != "completed":
                continue
            if _ok(lead, require_docs_flag=require_docs):
                return lead["id"]
    for lead in leads:
        if _ok(lead, require_docs_flag=require_docs):
            return lead["id"]
    return None


def pick_sample_o1_lead(
    *,
    prefer_completed: bool = True,
    require_docs: bool = True,
) -> Optional[str]:
    """Choose a good O-1A lead for local testing."""
    return pick_sample_lead(
        prefer_completed=prefer_completed,
        require_docs=require_docs,
        visa_category="O-1A",
    )
