"""Map uploaded PDFs onto intake criteria and keep extractable excerpts."""

from __future__ import annotations

from typing import Any

from .schema import CriterionIntake, EvidenceItem, EvidenceStatus, IntakeCriterionKey

EXCERPT_LIMIT = 800

# Folder names used in the lead-documents export (checked before filename hints).
_FOLDER_TO_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("o1-award", ("awards",)),
    ("o1-internal-award", ("awards",)),
    ("o1-employer-award", ("awards",)),
    ("o1-peer-invite", ("peer_review", "judging")),
    ("o1-peer-paper", ("publications", "peer_review")),
    ("o1-peer-proof", ("peer_review", "judging")),
    ("o1-article", ("publications",)),
    ("o1-w2", ("high_salary",)),
    ("o1-tax", ("high_salary",)),
)

_FILENAME_TO_KEYS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("1099", "w-2", "w2", "tax transcript", "tax_transcript"), ("high_salary",)),
    (("award", "darpa", "tuition", "katsh"), ("awards",)),
    (("neurips",), ("peer_review", "judging", "publications")),
    (("ieee",), ("publications",)),
)


def usable_document_text(text: str) -> str:
    blob = (text or "").strip()
    if not blob:
        return ""
    lowered = blob.lower()
    if lowered.startswith("[omitted:") or lowered.startswith("[extraction_failed"):
        return ""
    return blob


def document_excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    cleaned = " ".join(usable_document_text(text).split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "...[truncated]..."


def criterion_keys_for_document(*, filename: str, relative_path: str = "") -> list[str]:
    hay = f"{relative_path} {filename}".lower().replace("\\", "/")
    keys: list[str] = []
    for folder, mapped in _FOLDER_TO_KEYS:
        if folder in hay:
            keys.extend(mapped)
    if keys:
        return list(dict.fromkeys(keys))
    for tokens, mapped in _FILENAME_TO_KEYS:
        if any(token in hay for token in tokens):
            keys.extend(mapped)
    return list(dict.fromkeys(keys))


def evidence_index_from_documents(documents: list[dict[str, Any]]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for doc in documents:
        filename = (doc.get("filename") or doc.get("path") or "").strip()
        if not filename:
            continue
        items.append(
            EvidenceItem(
                source="document",
                reference=filename,
                excerpt=document_excerpt(doc.get("text") or ""),
            )
        )
    return items


def attach_document_evidence(
    criteria: list[CriterionIntake],
    documents: list[dict[str, Any]],
) -> None:
    """Attach PDF excerpts to matching criteria so evaluation can read them."""
    by_key = {c.key: c for c in criteria}
    for doc in documents:
        filename = (doc.get("filename") or doc.get("path") or "").strip()
        relative = doc.get("relative_path") or ""
        excerpt = document_excerpt(doc.get("text") or "")
        if not filename or not excerpt:
            continue
        for key_name in criterion_keys_for_document(
            filename=filename, relative_path=relative
        ):
            try:
                key = IntakeCriterionKey(key_name)
            except ValueError:
                continue
            criterion = by_key.get(key)
            if criterion is None:
                continue
            seen = {(e.source, e.reference) for e in criterion.evidence_items}
            if ("document", filename) in seen:
                continue
            criterion.evidence_items.append(
                EvidenceItem(source="document", reference=filename, excerpt=excerpt)
            )
            if criterion.evidence_status in {
                EvidenceStatus.MISSING,
                EvidenceStatus.CLAIM_ONLY,
            }:
                criterion.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED
