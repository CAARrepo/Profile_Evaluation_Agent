"""Intake Agent: assemble case → structure with local LLM → validate profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .category import detect_intake_category
from .config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OUTPUT_DIR,
)
from .documents import attach_document_evidence, evidence_index_from_documents
from .loaders import load_case
from .llm import chat_json, ensure_model_available
from .source_extract import attach_extracted_sources, extract_bundle_sources
from .o1_form import (
    is_detailed_o1_form,
    seed_criteria_from_detailed_o1,
    seed_employment_from_detailed_o1,
    seed_field_of_endeavor,
)
from .prompts import build_user_prompt, criteria_keys_for, system_prompt
from .schema import (
    ApplicantIdentity,
    CaseBundle,
    CriterionIntake,
    EvidenceItem,
    EvidenceStatus,
    IntakeCriterionKey,
    InformationGap,
    StandardizedProfile,
)
from .url_fetch import collect_applicant_urls, fetch_applicant_urls


CRITERION_FIELD_MAP = {
    "awards": IntakeCriterionKey.AWARDS,
    "memberships": IntakeCriterionKey.MEMBERSHIPS,
    "media": IntakeCriterionKey.MEDIA,
    "peerReview": IntakeCriterionKey.PEER_REVIEW,
    "peer_review": IntakeCriterionKey.PEER_REVIEW,
    "judging": IntakeCriterionKey.JUDGING,
    "patents": IntakeCriterionKey.PATENTS,
    "publications": IntakeCriterionKey.PUBLICATIONS,
    "criticalRole": IntakeCriterionKey.CRITICAL_ROLE,
    "critical_role": IntakeCriterionKey.CRITICAL_ROLE,
    "highSalary": IntakeCriterionKey.HIGH_SALARY,
    "high_salary": IntakeCriterionKey.HIGH_SALARY,
    "conferences": IntakeCriterionKey.CONFERENCES,
    "googleScholar": IntakeCriterionKey.GOOGLE_SCHOLAR,
    "google_scholar": IntakeCriterionKey.GOOGLE_SCHOLAR,
    "artistic_display": IntakeCriterionKey.ARTISTIC_DISPLAY,
    "artisticDisplay": IntakeCriterionKey.ARTISTIC_DISPLAY,
    "commercial_success": IntakeCriterionKey.COMMERCIAL_SUCCESS,
    "commercialSuccess": IntakeCriterionKey.COMMERCIAL_SUCCESS,
}

_URL_SOURCE_TO_CRITERION = {
    "google_scholar": IntakeCriterionKey.GOOGLE_SCHOLAR,
    "media": IntakeCriterionKey.MEDIA,
}


def enrich_bundle_with_urls(bundle: CaseBundle) -> CaseBundle:
    """Fetch applicant-provided URLs best-effort; never raise."""
    try:
        identity = seed_identity(bundle)
        urls = collect_applicant_urls(
            questionnaire=bundle.questionnaire,
            identity_urls=[identity.linkedin_url, identity.google_scholar_url],
        )
        pages, failed = fetch_applicant_urls(urls)
        bundle.url_texts = pages
        bundle.url_fetch_failures = failed
    except Exception:  # noqa: BLE001 - URL enrichment must never block intake
        bundle.url_texts = []
        bundle.url_fetch_failures = []
    return bundle


def _attach_url_evidence(criteria: list[CriterionIntake], pages: list[dict[str, str]]) -> None:
    by_key = {c.key: c for c in criteria}
    for page in pages:
        source = page.get("source") or "url"
        url = page.get("url") or ""
        excerpt = (page.get("text") or "")[:800]
        title = (page.get("title") or "").strip()
        item = EvidenceItem(
            source=source,
            reference=url,
            excerpt=(f"{title}: {excerpt}" if title else excerpt)[:800],
        )
        criterion_key = _URL_SOURCE_TO_CRITERION.get(source)
        if criterion_key and criterion_key in by_key:
            c = by_key[criterion_key]
            c.evidence_items.append(item)
            if c.evidence_status == EvidenceStatus.MISSING:
                c.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED
            if not c.claim_summary and title:
                c.claim_summary = f"Fetched page: {title}"[:500]
            if not c.notes:
                c.notes = "Content retrieved from applicant-provided URL (best-effort)"


def _answers(bundle: CaseBundle) -> dict[str, Any]:
    if not bundle.questionnaire:
        return {}
    return bundle.questionnaire.get("answers") or {}


def _normalize_answer(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip().lower()
    if text in {"yes", "y", "true"}:
        return "yes"
    if text in {"no", "n", "false"}:
        return "no"
    if text in {"not_sure", "not sure", "unsure", "maybe"}:
        return "not_sure"
    return "unknown"


def seed_identity(bundle: CaseBundle) -> ApplicantIdentity:
    lead = bundle.lead
    section_a = _answers(bundle).get("sectionA") or {}
    section_b = _answers(bundle).get("sectionB") or {}
    criteria = section_b.get("criteria") or {}
    scholar = criteria.get("googleScholar") or {}

    return ApplicantIdentity(
        lead_id=lead.get("id") or "",
        first_name=lead.get("first_name") or "",
        last_name=lead.get("last_name") or "",
        email=lead.get("email") or "",
        phone=lead.get("phone_e164") or "",
        immigration_category=lead.get("immigration_category") or "",
        current_status=section_a.get("currentStatus") or section_a.get("currentStatusOther") or "",
        status_expiration_date=section_a.get("statusExpirationDate") or "",
        country_of_birth=section_a.get("countryOfBirth") or "",
        country_of_citizenship=section_a.get("countryOfCitizenship") or "",
        married=section_a.get("married") or "",
        linkedin_url=section_a.get("linkedInUrl") or "",
        google_scholar_url=(scholar.get("details") or "") if isinstance(scholar, dict) else "",
        us_job_offer=section_b.get("usJobOffer") or "",
        company_name=section_b.get("companyName") or "",
        position=section_b.get("position") or "",
        salary=section_b.get("salary") or "",
        sponsor_willingness=section_b.get("sponsorWillingness") or "",
        self_employment_planned=section_b.get("selfEmploymentPlanned") or "",
        explore_agent_option=section_b.get("exploreAgentOption") or "",
    )


def seed_criteria_from_questionnaire(
    bundle: CaseBundle,
    visa_category: str = "",
) -> list[CriterionIntake]:
    answers = _answers(bundle)
    if is_detailed_o1_form(answers):
        return seed_criteria_from_detailed_o1(answers, visa_category)

    section_b = answers.get("sectionB") or {}
    raw = section_b.get("criteria") or {}
    seeded: dict[IntakeCriterionKey, CriterionIntake] = {}

    for key, criterion_key in CRITERION_FIELD_MAP.items():
        if key not in raw:
            continue
        item = raw[key]
        if not isinstance(item, dict):
            continue
        answer = _normalize_answer(item.get("answer"))
        details = (item.get("details") or "").strip()
        status = EvidenceStatus.MISSING
        evidence_items: list[EvidenceItem] = []
        gaps: list[str] = []
        notes = ""
        if answer == "yes":
            # MVP: Yes + details = applicant-stated claim assumed true for initial evaluation
            status = EvidenceStatus.CLAIM_ONLY
            notes = "MVP: applicant-stated claim assumed true for initial evaluation; evidence not required"
            if details:
                evidence_items.append(
                    EvidenceItem(
                        source="questionnaire",
                        reference=f"sectionB.criteria.{key}",
                        excerpt=details[:800],
                    )
                )
            else:
                gaps.append("Applicant answered yes but provided no details")
        elif answer == "not_sure":
            status = EvidenceStatus.CLAIM_ONLY if details else EvidenceStatus.MISSING
            if details:
                evidence_items.append(
                    EvidenceItem(
                        source="questionnaire",
                        reference=f"sectionB.criteria.{key}",
                        excerpt=details[:800],
                    )
                )
                notes = "MVP: applicant-stated claim (not_sure) passed through for initial evaluation"
            gaps.append("Applicant marked not_sure for this criterion")
        elif answer == "no":
            status = EvidenceStatus.MISSING

        seeded[criterion_key] = CriterionIntake(
            key=criterion_key,
            applicant_answer=answer,  # type: ignore[arg-type]
            claim_summary=details[:500] if details else "",
            evidence_status=status,
            evidence_items=evidence_items,
            gaps=gaps,
            notes=notes,
        )

    required = []
    for key_name in criteria_keys_for(visa_category):
        required.append(IntakeCriterionKey(key_name))
    for key in required:
        if key not in seeded:
            seeded[key] = CriterionIntake(
                key=key, applicant_answer="unknown", evidence_status=EvidenceStatus.MISSING
            )

    return [seeded[k] for k in required]


def deterministic_information_gaps(
    bundle: CaseBundle,
    identity: ApplicantIdentity,
    criteria: list[CriterionIntake],
) -> list[InformationGap]:
    """Record gaps for the Evaluation Agent; never block MVP processing."""
    gaps: list[InformationGap] = []
    if not bundle.questionnaire:
        gaps.append(
            InformationGap(
                priority="high",
                topic="questionnaire",
                detail="No questionnaire answers found for this lead.",
            )
        )
    if not bundle.document_texts:
        gaps.append(
            InformationGap(
                priority="medium",
                topic="documents",
                detail="No documents found under datasets/lead-documents for this lead (optional for MVP).",
            )
        )
    else:
        from .documents import usable_document_text

        for doc in bundle.document_texts:
            filename = doc.get("filename") or doc.get("path") or "document"
            if not usable_document_text(str(doc.get("text") or "")):
                gaps.append(
                    InformationGap(
                        priority="medium",
                        topic="documents",
                        detail=f"No extractable text from {filename} (likely a scanned image).",
                    )
                )
    if not identity.linkedin_url:
        gaps.append(
            InformationGap(
                priority="low",
                topic="linkedin",
                detail="LinkedIn URL not provided.",
            )
        )
    for failed_url in bundle.url_fetch_failures:
        gaps.append(
            InformationGap(
                priority="low",
                topic="url_fetch",
                detail=f"Could not retrieve applicant-provided URL (blocked, empty, or error): {failed_url}",
            )
        )
    if identity.us_job_offer in {"", "unknown"} and not identity.self_employment_planned:
        gaps.append(
            InformationGap(
                priority="medium",
                topic="sponsorship",
                detail="U.S. job offer / self-employment / agent path not clearly stated.",
            )
        )
    for c in criteria:
        for g in c.gaps:
            gaps.append(
                InformationGap(
                    priority="medium" if c.applicant_answer == "yes" else "low",
                    topic=f"criterion.{c.key.value}",
                    detail=g,
                )
            )
    return gaps


def _applicant_tokens(seeded: StandardizedProfile) -> set[str]:
    tokens = {
        (seeded.identity.first_name or "").strip().lower(),
        (seeded.identity.last_name or "").strip().lower(),
        (seeded.identity.company_name or "").strip().lower(),
        (seeded.field_of_endeavor or "").strip().lower(),
    }
    for job in seeded.employment:
        tokens.add((job.organization or "").strip().lower())
    return {t for t in tokens if len(t) >= 3}


def _text_matches_applicant(
    text: str,
    seeded: StandardizedProfile,
    extra: tuple[str, ...] = (),
) -> bool:
    blob = (text or "").lower()
    if not blob.strip():
        return False
    tokens = _applicant_tokens(seeded)
    tokens.update(t.strip().lower() for t in extra if t and len(t.strip()) >= 3)
    return any(token in blob for token in tokens)


def _employment_matches_applicant(jobs: list, seeded: StandardizedProfile) -> bool:
    blob = " ".join(f"{j.organization} {j.title}" for j in jobs)
    return _text_matches_applicant(blob, seeded)


def _union_evidence_items(target: CriterionIntake, source: CriterionIntake) -> None:
    seen = {(e.source, e.reference): e for e in target.evidence_items}
    for item in source.evidence_items:
        key = (item.source, item.reference)
        existing = seen.get(key)
        if existing is None:
            target.evidence_items.append(item)
            seen[key] = item
        elif not (existing.excerpt or "").strip() and (item.excerpt or "").strip():
            existing.excerpt = item.excerpt
    if any(e.source == "document" and e.excerpt for e in target.evidence_items):
        if target.evidence_status in {EvidenceStatus.MISSING, EvidenceStatus.CLAIM_ONLY}:
            target.evidence_status = EvidenceStatus.PARTIALLY_SUPPORTED


def _merge_evidence_index(
    primary: list[EvidenceItem],
    secondary: list[EvidenceItem],
) -> list[EvidenceItem]:
    by_key: dict[tuple[str, str], EvidenceItem] = {}
    for item in primary + secondary:
        key = (item.source, item.reference)
        existing = by_key.get(key)
        if existing is None or len(item.excerpt or "") > len(existing.excerpt or ""):
            by_key[key] = item
    return list(by_key.values())


def merge_profiles(
    seeded: StandardizedProfile,
    llm_data: dict[str, Any],
) -> StandardizedProfile:
    """Prefer LLM enrichment but keep deterministic identity / document inventory."""
    try:
        llm_profile = StandardizedProfile.model_validate(llm_data)
    except Exception:
        # salvage partial fields
        llm_profile = StandardizedProfile(
            case_id=seeded.case_id,
            identity=seeded.identity,
            raw_model_notes=json.dumps(llm_data)[:4000],
        )

    # Keep authoritative identity / category from CSV
    llm_profile.case_id = seeded.case_id
    llm_profile.identity = seeded.identity
    llm_profile.visa_category = seeded.visa_category
    llm_profile.documents_processed = seeded.documents_processed or llm_profile.documents_processed
    if not llm_profile.proposed_endeavor:
        llm_profile.proposed_endeavor = seeded.proposed_endeavor
    if not llm_profile.national_importance_summary:
        llm_profile.national_importance_summary = seeded.national_importance_summary
    if seeded.visa_category == "EB-2 NIW" and not llm_profile.proposed_endeavor:
        llm_profile.proposed_endeavor = llm_profile.field_of_endeavor or seeded.field_of_endeavor

    # Keep PDF excerpts even when the LLM lists files with empty excerpts
    llm_profile.evidence_index = _merge_evidence_index(
        llm_profile.evidence_index, seeded.evidence_index
    )

    # If LLM omitted criteria, keep seeded criteria. If both exist, keep the
    # richer applicant-stated Yes claims from the detailed questionnaire seed
    # and always retain seeded PDF evidence_items.
    if not llm_profile.criteria:
        llm_profile.criteria = seeded.criteria
    elif seeded.criteria:
        llm_by_key = {c.key: c for c in llm_profile.criteria}
        merged = []
        for seeded_c in seeded.criteria:
            llm_c = llm_by_key.get(seeded_c.key)
            if llm_c is None:
                merged.append(seeded_c)
                continue
            seeded_rich = seeded_c.applicant_answer == "yes" and bool(seeded_c.claim_summary)
            llm_thin = llm_c.applicant_answer in {"unknown", "no"} or not llm_c.claim_summary
            if seeded_rich and (llm_thin or len(seeded_c.claim_summary) > len(llm_c.claim_summary)):
                _union_evidence_items(seeded_c, llm_c)
                merged.append(seeded_c)
            else:
                _union_evidence_items(llm_c, seeded_c)
                merged.append(llm_c)
        extra = [c for c in llm_profile.criteria if c.key not in {s.key for s in seeded.criteria}]
        llm_profile.criteria = merged + extra

    # MVP: fold any legacy missing_information into information_gaps; never ask follow-ups
    for m in list(llm_profile.missing_information) + list(seeded.missing_information):
        detail = getattr(m, "reason", None) or getattr(m, "question", None) or str(m)
        llm_profile.information_gaps.append(
            InformationGap(priority=getattr(m, "priority", "medium"), topic=getattr(m, "topic", "other"), detail=detail)
        )
    llm_profile.missing_information = []

    seen = {(g.topic, g.detail) for g in llm_profile.information_gaps}
    for g in seeded.information_gaps:
        key = (g.topic, g.detail)
        if key not in seen:
            llm_profile.information_gaps.append(g)
            seen.add(key)

    # Ensure claims from seeded Yes answers are present
    if not llm_profile.claims:
        llm_profile.claims = seeded.claims
    else:
        claim_set = set(llm_profile.claims)
        for c in seeded.claims:
            if c not in claim_set:
                llm_profile.claims.append(c)

    # Drop bogus "no conflict" rows some small models emit
    llm_profile.conflicts = [
        c
        for c in llm_profile.conflicts
        if c.details
        and "no conflict" not in c.details.lower()
        and "not a conflict" not in c.details.lower()
    ]

    llm_contaminated = bool(llm_profile.summary) and not _text_matches_applicant(
        llm_profile.summary, seeded
    )
    if not llm_profile.summary or llm_contaminated:
        llm_profile.summary = seeded.summary
    if seeded.field_of_endeavor and (
        not llm_profile.field_of_endeavor or llm_contaminated
    ):
        llm_profile.field_of_endeavor = seeded.field_of_endeavor
    if seeded.employment and (
        not llm_profile.employment
        or llm_contaminated
        or not _employment_matches_applicant(llm_profile.employment, seeded)
    ):
        llm_profile.employment = seeded.employment
    if llm_contaminated:
        llm_profile.education = []

    # MVP: gaps never block evaluation
    llm_profile.readiness = "ready_for_evaluation"
    return llm_profile


class IntakeAgent:
    def __init__(
        self,
        *,
        model: str = OLLAMA_MODEL,
        host: str = OLLAMA_HOST,
        use_llm: bool = True,
    ) -> None:
        self.model = model
        self.host = host
        self.use_llm = use_llm

    def build_seed_profile(self, bundle: CaseBundle) -> StandardizedProfile:
        identity = seed_identity(bundle)
        visa_category = detect_intake_category(bundle.lead)
        criteria = seed_criteria_from_questionnaire(bundle, visa_category)
        attach_document_evidence(criteria, bundle.document_texts)
        _attach_url_evidence(criteria, bundle.url_texts)
        field_of_endeavor = seed_field_of_endeavor(_answers(bundle))
        employment = seed_employment_from_detailed_o1(_answers(bundle))
        info_gaps = deterministic_information_gaps(bundle, identity, criteria)
        docs = [d.get("filename") or d.get("path") or "" for d in bundle.document_texts]
        url_refs = [f"url:{(p.get('url') or '')}" for p in bundle.url_texts if p.get("url")]

        claims: list[str] = []
        for c in criteria:
            if c.applicant_answer in {"yes", "not_sure"} and c.claim_summary:
                claims.append(f"{c.key.value}: {c.claim_summary}")
            elif c.applicant_answer == "yes":
                claims.append(f"{c.key.value}: (yes — no details provided)")
        for page in bundle.url_texts:
            url = page.get("url") or ""
            title = (page.get("title") or "").strip()
            excerpt = (page.get("text") or "")[:400]
            label = title or url
            if excerpt:
                claims.append(f"Fetched URL ({label}): {excerpt}")

        name = f"{identity.first_name} {identity.last_name}".strip()
        label = visa_category or (identity.immigration_category or "visa")
        summary = (
            f"{label} intake for {name or identity.lead_id}. "
            f"Status={identity.current_status or 'unknown'}; "
            f"docs={len(docs)}; "
            f"fetched_urls={len(bundle.url_texts)}; "
            f"positive/unsure criteria="
            f"{sum(1 for c in criteria if c.applicant_answer in {'yes', 'not_sure'})}."
        )

        evidence_index = evidence_index_from_documents(bundle.document_texts)
        for page in bundle.url_texts:
            evidence_index.append(
                EvidenceItem(
                    source=page.get("source") or "url",
                    reference=page.get("url") or "",
                    excerpt=(page.get("text") or "")[:800],
                )
            )

        return StandardizedProfile(
            case_id=identity.lead_id,
            identity=identity,
            visa_category=visa_category,
            field_of_endeavor=field_of_endeavor,
            summary=summary,
            employment=employment,
            criteria=criteria,
            claims=claims,
            evidence_index=evidence_index,
            information_gaps=info_gaps,
            missing_information=[],  # MVP: no applicant follow-ups
            documents_processed=docs + url_refs,
            readiness="ready_for_evaluation",
        )

    def run(self, lead_id: str) -> StandardizedProfile:
        bundle = load_case(lead_id)
        enrich_bundle_with_urls(bundle)
        seeded = self.build_seed_profile(bundle)

        if not self.use_llm:
            return seeded

        # One LLM pass per PDF/URL (GPU + CPU), then a merge pass.
        ensure_model_available(self.model, self.host)
        extract_bundle_sources(bundle, model=self.model, host=self.host)
        attach_extracted_sources(seeded, bundle)
        category = detect_intake_category(bundle.lead)
        llm_data = chat_json(
            system=system_prompt(category),
            user=build_user_prompt(bundle, visa_category=category),
            model=self.model,
            host=self.host,
        )
        # Force case/identity consistency
        llm_data["case_id"] = seeded.case_id
        llm_data["visa_category"] = category
        if "identity" not in llm_data or not isinstance(llm_data["identity"], dict):
            llm_data["identity"] = seeded.identity.model_dump()
        else:
            llm_data["identity"]["lead_id"] = seeded.identity.lead_id
        return merge_profiles(seeded, llm_data)

    def run_and_save(self, lead_id: str, output_dir: Path = OUTPUT_DIR) -> Path:
        profile = self.run(lead_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{lead_id}_intake.json"
        out_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        return out_path
