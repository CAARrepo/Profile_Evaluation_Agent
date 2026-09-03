"""Per-source LLM extraction so every PDF and fetched URL is used."""

from __future__ import annotations

from typing import Any

from .config import OLLAMA_HOST, OLLAMA_MODEL, SOURCE_EXTRACT_CHARS
from .documents import criterion_keys_for_document, usable_document_text
from .llm import chat_json
from .schema import (
    CaseBundle,
    EducationRecord,
    EmploymentRecord,
    EvidenceItem,
    EvidenceStatus,
    InformationGap,
    IntakeCriterionKey,
    StandardizedProfile,
)

SOURCE_EXTRACT_SYSTEM = """You extract visa-profile facts from ONE document or webpage.

Return JSON only:
{
  "document_type": "resume|award|peer_review|publication|tax|compensation|other",
  "criteria_keys": ["awards"],
  "facts": ["short factual sentence"],
  "employment": [{"organization":"","title":"","start_date":"","end_date":"","responsibilities":[]}],
  "education": [{"institution":"","degree":"","field":"","dates":""}],
  "excerpts": ["short supporting quote"]
}

Rules:
- Extract only facts present in the text. Do not invent names, employers, awards, amounts, or dates.
- facts: up to 8 short sentences.
- excerpts: up to 3 quotes, each under 400 characters.
- criteria_keys must be from: awards, memberships, media, peer_review, judging, patents, publications, critical_role, high_salary, conferences, google_scholar.
- The named lead is the applicant. Do not treat nominators or other people as the applicant.
"""


def window_source_text(text: str, limit: int = SOURCE_EXTRACT_CHARS) -> str:
    blob = usable_document_text(text)
    if not blob:
        return ""
    if limit <= 0 or len(blob) <= limit:
        return blob
    head = (limit * 2) // 3
    tail = limit - head
    return blob[:head] + "\n...[middle omitted]...\n" + blob[-tail:]


def extract_one_source(
    *,
    label: str,
    text: str,
    extra: dict[str, Any] | None = None,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
) -> dict[str, Any]:
    windowed = window_source_text(text)
    if not windowed:
        return {}
    payload = {
        "source_label": label,
        "text": windowed,
        **(extra or {}),
    }
    try:
        data = chat_json(
            system=SOURCE_EXTRACT_SYSTEM,
            user=str(payload),
            model=model,
            host=host,
        )
    except Exception:  # noqa: BLE001 - one failed file must not stop intake
        return {}
    return data if isinstance(data, dict) else {}


def extract_bundle_sources(
    bundle: CaseBundle,
    *,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
) -> None:
    """Run one LLM extraction per PDF and fetched URL. Mutates the bundle."""
    for doc in bundle.document_texts:
        label = doc.get("filename") or doc.get("path") or "document"
        data = extract_one_source(
            label=str(label),
            text=str(doc.get("text") or ""),
            extra={"relative_path": doc.get("relative_path") or ""},
            model=model,
            host=host,
        )
        facts = [str(f).strip() for f in (data.get("facts") or []) if str(f).strip()]
        excerpts = [str(x).strip() for x in (data.get("excerpts") or []) if str(x).strip()]
        doc["extracted"] = data
        doc["extracted_facts"] = facts
        if excerpts and not usable_document_text(str(doc.get("excerpt") or "")):
            doc["llm_excerpt"] = excerpts[0][:800]

    for page in bundle.url_texts:
        label = page.get("title") or page.get("url") or "url"
        data = extract_one_source(
            label=str(label),
            text=str(page.get("text") or ""),
            extra={"url": page.get("url") or ""},
            model=model,
            host=host,
        )
        facts = [str(f).strip() for f in (data.get("facts") or []) if str(f).strip()]
        page["extracted"] = data
        page["extracted_facts"] = facts


def _valid_keys(raw: Any, fallback: list[str]) -> list[str]:
    allowed = {k.value for k in IntakeCriterionKey}
    keys: list[str] = []
    for item in list(raw or []) + fallback:
        name = str(item or "").strip()
        if name in allowed and name not in keys:
            keys.append(name)
    return keys


def attach_extracted_sources(profile: StandardizedProfile, bundle: CaseBundle) -> None:
    """Fold per-source LLM facts onto the seeded profile."""
    by_key = {c.key: c for c in profile.criteria}
    index_by_ref = {(e.source, e.reference): e for e in profile.evidence_index}

    for doc in bundle.document_texts:
        filename = str(doc.get("filename") or doc.get("path") or "")
        data = doc.get("extracted") or {}
        facts = list(doc.get("extracted_facts") or [])
        excerpts = [str(x).strip() for x in (data.get("excerpts") or []) if str(x).strip()]
        mapped = criterion_keys_for_document(
            filename=filename,
            relative_path=str(doc.get("relative_path") or ""),
        )
        keys = _valid_keys(data.get("criteria_keys"), mapped)
        quotes = excerpts or facts
        excerpt = " ".join(quotes)[:800] if quotes else ""
        if excerpt:
            stored = index_by_ref.get(("document", filename))
            if stored and not (stored.excerpt or "").strip():
                stored.excerpt = excerpt[:800]
        if not usable_document_text(str(doc.get("text") or "")):
            profile.information_gaps.append(
                InformationGap(
                    priority="medium",
                    topic="documents",
                    detail=f"No extractable text from {filename} (likely a scanned image).",
                )
            )
        for key_name in keys:
            criterion = by_key.get(IntakeCriterionKey(key_name))
            if criterion is None:
                continue
            seen = {(e.source, e.reference, e.excerpt) for e in criterion.evidence_items}
            for quote in quotes[:6]:
                item = EvidenceItem(source="document", reference=filename, excerpt=quote[:800])
                marker = (item.source, item.reference, item.excerpt)
                if marker in seen:
                    continue
                criterion.evidence_items.append(item)
                seen.add(marker)
            if quotes and criterion.evidence_status in {
                EvidenceStatus.MISSING,
                EvidenceStatus.CLAIM_ONLY,
            }:
                criterion.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED
        _merge_history(profile, data)

    for page in bundle.url_texts:
        url = str(page.get("url") or "")
        data = page.get("extracted") or {}
        facts = list(page.get("extracted_facts") or [])
        excerpts = [str(x).strip() for x in (data.get("excerpts") or []) if str(x).strip()]
        quotes = excerpts or facts
        source = str(page.get("source") or "url")
        keys = _valid_keys(data.get("criteria_keys"), [])
        if source == "google_scholar" and "google_scholar" not in keys:
            keys.append("google_scholar")
        if source == "media" and "media" not in keys:
            keys.append("media")
        for key_name in keys:
            try:
                criterion = by_key.get(IntakeCriterionKey(key_name))
            except ValueError:
                continue
            if criterion is None:
                continue
            for quote in quotes[:4]:
                criterion.evidence_items.append(
                    EvidenceItem(source=source, reference=url, excerpt=quote[:800])
                )
            if quotes and criterion.evidence_status in {
                EvidenceStatus.MISSING,
                EvidenceStatus.CLAIM_ONLY,
            }:
                criterion.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED
        _merge_history(profile, data)


def _merge_history(profile: StandardizedProfile, data: dict[str, Any]) -> None:
    for job in data.get("employment") or []:
        if not isinstance(job, dict):
            continue
        org = str(job.get("organization") or "").strip()
        title = str(job.get("title") or "").strip()
        if not org and not title:
            continue
        already = any(
            e.organization.lower() == org.lower() and e.title.lower() == title.lower()
            for e in profile.employment
        )
        if already:
            continue
        profile.employment.append(
            EmploymentRecord(
                organization=org,
                title=title,
                location=str(job.get("location") or ""),
                start_date=str(job.get("start_date") or ""),
                end_date=str(job.get("end_date") or ""),
                responsibilities=[str(r) for r in (job.get("responsibilities") or []) if r][:6],
                source="resume",
            )
        )
    for edu in data.get("education") or []:
        if not isinstance(edu, dict):
            continue
        inst = str(edu.get("institution") or "").strip()
        degree = str(edu.get("degree") or "").strip()
        if not inst and not degree:
            continue
        already = any(
            e.institution.lower() == inst.lower() and e.degree.lower() == degree.lower()
            for e in profile.education
        )
        if already:
            continue
        profile.education.append(
            EducationRecord(
                institution=inst,
                degree=degree,
                field=str(edu.get("field") or ""),
                dates=str(edu.get("dates") or ""),
                source="resume",
            )
        )
