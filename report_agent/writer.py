"""LLM writer for client-facing Existing documents labels."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .config import OLLAMA_MODEL
from .llm import OllamaError, chat_json, ensure_model_available
from .text_utils import (
    _SOURCE_FACT,
    _UUID_FILE_PREFIX,
    _uploaded_file_type,
    consolidate_evidence,
    fix_mojibake,
)

WriterFn = Callable[..., dict[str, Any]]

SYSTEM_PROMPT = """You write the Existing documents column for a client immigration profile report.

Do not rescore, reclassify, or change criterion status. Do not invent documents that are not in the input.

For uploaded files (kind=document):
- Name the DOCUMENT TYPE, using the intake-form upload slot and the file itself.
- Use labels like: Research paper, PowerPoint presentation, Offer letter, Award certificate,
  Internal award, Employer award, W-2, 1099, Tax transcript, Peer-review invitation,
  Proof of completed review, Resume.
- Never output a filename, UUID, URL, or file extension.
- suggested_type is the intake-form heading hint; prefer it unless the file itself is clearly a more specific type (for example an offer letter in the W-2 slot, or a .pptx).

For questionnaire claims (kind=questionnaire): one short factual phrase of what the applicant stated.
For URLs (kind=url): omit them unless they clearly identify a document type already listed; do not paste webpage sentences.

Deduplicate identical types. Maximum 6 items per criterion.
Return JSON only:
{"criteria":[{"criterion_id":"o1a_awards","existing_documents":["Award certificate","Internal award"]}]}
"""


def _form_slot(relative_path: str) -> str:
    parts = [p for p in relative_path.replace("\\", "/").split("/") if p]
    if len(parts) >= 2:
        return "/".join(parts[1:3] if len(parts) >= 3 else parts[1:])
    return relative_path


def _excerpt(text: str, limit: int = 180) -> str:
    cleaned = " ".join(fix_mojibake(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0]


def fact_items_for_llm(
    facts: list[str],
    *,
    path_index: Optional[dict[str, str]] = None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in facts:
        cleaned = " ".join(fix_mojibake(str(raw or "")).split())
        if not cleaned:
            continue
        match = _SOURCE_FACT.match(cleaned)
        if match:
            source = (match.group("source") or "").strip().lower()
            ref = (match.group("ref") or "").strip()
            body = _excerpt(match.group("body") or "")
            if source == "document":
                relative = ref.replace("\\", "/")
                name = relative.split("/")[-1]
                if path_index:
                    relative = (
                        path_index.get(name)
                        or path_index.get(_UUID_FILE_PREFIX.sub("", name))
                        or relative
                    )
                suggested = _uploaded_file_type(ref, path_index)
                key = ("document", suggested)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "kind": "document",
                        "form_slot": _form_slot(relative),
                        "suggested_type": suggested,
                        "excerpt": body,
                    }
                )
            elif source == "url":
                continue
            else:
                key = ("text", body[:80].lower())
                if not body or key in seen:
                    continue
                seen.add(key)
                items.append({"kind": "questionnaire", "suggested_type": "", "excerpt": body})
            continue
        body = _excerpt(cleaned)
        key = ("text", body[:80].lower())
        if body and key not in seen:
            seen.add(key)
            items.append({"kind": "questionnaire", "suggested_type": "", "excerpt": body})
    return items


def criteria_payload(
    evaluation: dict[str, Any],
    *,
    path_index: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for criterion in evaluation.get("criteria") or []:
        if not isinstance(criterion, dict):
            continue
        if str(criterion.get("status") or "") == "not_applicable":
            continue
        cid = str(criterion.get("criterion_id") or "").strip()
        if not cid:
            continue
        items = fact_items_for_llm(
            [str(x) for x in (criterion.get("applicant_facts") or [])],
            path_index=path_index,
        )
        if not items:
            continue
        rows.append(
            {
                "criterion_id": cid,
                "criterion_name": str(criterion.get("criterion_name") or cid),
                "items": items,
            }
        )
    return rows


def _looks_like_filename(text: str) -> bool:
    lowered = text.lower()
    return lowered.endswith((".pdf", ".pptx", ".ppt", ".doc", ".docx")) or bool(
        _UUID_FILE_PREFIX.search(text)
    )


def _clean_labels(raw: Any, *, limit: int = 6) -> list[str]:
    values: list[str] = []
    if isinstance(raw, list):
        values = [fix_mojibake(str(x)) for x in raw]
    return consolidate_evidence(
        [item for item in values if item and not _looks_like_filename(item)],
        limit=limit,
    )


def parse_existing_document_labels(data: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in data.get("criteria") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("criterion_id") or "").strip()
        labels = _clean_labels(row.get("existing_documents"))
        if cid and labels:
            out[cid] = labels
    return out


def write_existing_documents(
    evaluation: dict[str, Any],
    *,
    path_index: Optional[dict[str, str]] = None,
    model: str = OLLAMA_MODEL,
    writer: Optional[WriterFn] = None,
) -> dict[str, list[str]]:
    payload = criteria_payload(evaluation, path_index=path_index)
    if not payload:
        return {}
    user = json.dumps({"criteria": payload}, ensure_ascii=False)
    try:
        if writer is not None:
            data = writer(system=SYSTEM_PROMPT, user=user)
        else:
            ensure_model_available(model)
            data = chat_json(
                system=SYSTEM_PROMPT,
                user=user,
                model=model,
                label="report_existing_documents",
            )
    except (OllamaError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"[report] LLM existing-documents fallback to form-slot labels ({exc})", flush=True)
        return {}
    if not isinstance(data, dict):
        return {}
    return parse_existing_document_labels(data)
