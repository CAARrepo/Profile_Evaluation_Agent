"""Map uploaded PDFs onto intake criteria and keep extractable excerpts."""

from __future__ import annotations

import re
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
    ("employer-award", ("awards",)),
    ("internal-award", ("awards",)),
    ("/03-awards/", ("awards",)),
    ("peer-invite", ("peer_review", "judging")),
    ("peer-paper", ("publications", "peer_review")),
    ("peer-proof", ("peer_review", "judging")),
    ("/06-judging/", ("peer_review", "judging")),
    ("/07-publications/", ("publications",)),
    ("article-", ("publications",)),
    ("w2-0", ("high_salary",)),
    ("/tax-0", ("high_salary",)),
    ("/08-compensation/", ("high_salary",)),
    ("presentation-", ("conferences", "publications")),
    ("/09-contributions/", ("patents", "conferences")),
)

_FILENAME_TO_KEYS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("1099", "w-2", "w2", "tax transcript", "tax_transcript"), ("high_salary",)),
    (("award", "darpa", "tuition", "katsh"), ("awards",)),
    (("neurips",), ("peer_review", "judging", "publications")),
    (("ieee", "aircraft", "satellite"), ("publications",)),
    (("pptx", "powerpoint", "iccpct"), ("conferences", "publications")),
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


# Intake-form upload slots → client-facing document type (not the original filename).
# Longer / more specific folder tokens first so employer-award beats award-.
_FOLDER_TYPE_LABELS: tuple[tuple[str, str], ...] = (
    ("internal-award", "Internal award"),
    ("employer-award", "Employer award"),
    ("peer-invite", "Peer-review invitation"),
    ("peer-paper", "Research paper"),
    ("peer-proof", "Proof of completed review"),
    ("presentation-", "PowerPoint presentation"),
    ("article-", "Research paper"),
    ("o1-article", "Research paper"),
    ("tax-0", "Tax transcript"),
    ("o1-tax", "Tax transcript"),
    ("w2-0", "W-2"),
    ("o1-w2", "W-2"),
    ("o1-award", "Award certificate"),
    ("award-0", "Award certificate"),
    ("/03-awards/", "Award certificate"),
    ("/07-publications/", "Research paper"),
    ("/06-judging/", "Judging documentation"),
    ("/08-compensation/", "Compensation documentation"),
    ("/09-contributions/", "Contribution documentation"),
    ("/resume/", "Resume"),
    ("01-background", "Resume"),
)

_OFFER_LETTER = re.compile(r"offer[\s_-]*letter|job[\s_-]*offer", re.I)
_TAX_TRANSCRIPT = re.compile(r"tax[\s_-]*transcript", re.I)
_RESUME_NAME = re.compile(r"(^|[^a-z])resume([^a-z]|$)", re.I)
_W2_NAME = re.compile(r"(^|[^a-z])w-?2([^a-z]|$)", re.I)
_AWARD_NAME = re.compile(r"award|certificate", re.I)


def document_type_label(*, filename: str, relative_path: str = "") -> str:
    """Client-facing type from the intake-form upload slot, refined by file kind."""
    path = (relative_path or "").replace("\\", "/")
    name = (filename or path).replace("\\", "/").split("/")[-1]
    hay = f"{path} {name}".lower()

    if name.lower().endswith((".pptx", ".ppt", ".pptm")) or "powerpoint" in hay:
        return "PowerPoint presentation"
    if _OFFER_LETTER.search(hay):
        return "Offer letter"
    if "1099" in name.lower():
        return "1099"
    if _TAX_TRANSCRIPT.search(hay):
        return "Tax transcript"

    for token, label in _FOLDER_TYPE_LABELS:
        if token in hay:
            return label

    if _RESUME_NAME.search(name):
        return "Resume"
    if _W2_NAME.search(name):
        return "W-2"
    if _AWARD_NAME.search(name):
        return "Award certificate"
    if name.lower().endswith(".pdf") and re.search(r"article|paper|publication", hay):
        return "Research paper"
    return "Uploaded document"


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
        relative = str(doc.get("relative_path") or "").replace("\\", "/")
        items.append(
            EvidenceItem(
                source="document",
                reference=relative or filename,
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
        relative = str(doc.get("relative_path") or "").replace("\\", "/")
        excerpt = document_excerpt(doc.get("text") or "")
        if not filename or not excerpt:
            continue
        reference = relative or filename
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
            if ("document", reference) in seen or ("document", filename) in seen:
                continue
            criterion.evidence_items.append(
                EvidenceItem(source="document", reference=reference, excerpt=excerpt)
            )
            if criterion.evidence_status in {
                EvidenceStatus.MISSING,
                EvidenceStatus.CLAIM_ONLY,
            }:
                criterion.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED
