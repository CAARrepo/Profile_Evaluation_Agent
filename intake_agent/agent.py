"""Intake Agent: assemble case → structure with local LLM → validate profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import (
    MAX_DOCUMENT_CHARS,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OUTPUT_DIR,
)
from .loaders import load_case
from .llm import chat_json, ensure_model_available
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schema import (
    ApplicantIdentity,
    CaseBundle,
    CriterionIntake,
    EvidenceItem,
    EvidenceStatus,
    InformationGap,
    O1CriterionKey,
    StandardizedProfile,
)


CRITERION_FIELD_MAP = {
    "awards": O1CriterionKey.AWARDS,
    "memberships": O1CriterionKey.MEMBERSHIPS,
    "media": O1CriterionKey.MEDIA,
    "peerReview": O1CriterionKey.PEER_REVIEW,
    "peer_review": O1CriterionKey.PEER_REVIEW,
    "judging": O1CriterionKey.JUDGING,
    "patents": O1CriterionKey.PATENTS,
    "publications": O1CriterionKey.PUBLICATIONS,
    "criticalRole": O1CriterionKey.CRITICAL_ROLE,
    "critical_role": O1CriterionKey.CRITICAL_ROLE,
    "highSalary": O1CriterionKey.HIGH_SALARY,
    "high_salary": O1CriterionKey.HIGH_SALARY,
    "conferences": O1CriterionKey.CONFERENCES,
    "googleScholar": O1CriterionKey.GOOGLE_SCHOLAR,
    "google_scholar": O1CriterionKey.GOOGLE_SCHOLAR,
}


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


def seed_criteria_from_questionnaire(bundle: CaseBundle) -> list[CriterionIntake]:
    section_b = _answers(bundle).get("sectionB") or {}
    raw = section_b.get("criteria") or {}
    seeded: dict[O1CriterionKey, CriterionIntake] = {}

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

    # Ensure all criteria appear in the profile
    for key in O1CriterionKey:
        if key not in seeded:
            seeded[key] = CriterionIntake(key=key, applicant_answer="unknown", evidence_status=EvidenceStatus.MISSING)

    return [seeded[k] for k in O1CriterionKey]


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
    if not identity.linkedin_url:
        gaps.append(
            InformationGap(
                priority="low",
                topic="linkedin",
                detail="LinkedIn URL not provided.",
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

    # Keep authoritative identity from CSV/questionnaire
    llm_profile.case_id = seeded.case_id
    llm_profile.identity = seeded.identity
    llm_profile.documents_processed = seeded.documents_processed

    # If LLM omitted criteria, keep seeded criteria
    if not llm_profile.criteria:
        llm_profile.criteria = seeded.criteria

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

    if not llm_profile.summary:
        llm_profile.summary = seeded.summary

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
        criteria = seed_criteria_from_questionnaire(bundle)
        info_gaps = deterministic_information_gaps(bundle, identity, criteria)
        docs = [d.get("filename") or d.get("path") or "" for d in bundle.document_texts]

        claims: list[str] = []
        for c in criteria:
            if c.applicant_answer in {"yes", "not_sure"} and c.claim_summary:
                claims.append(f"{c.key.value}: {c.claim_summary}")
            elif c.applicant_answer == "yes":
                claims.append(f"{c.key.value}: (yes — no details provided)")

        name = f"{identity.first_name} {identity.last_name}".strip()
        summary = (
            f"O-1A intake for {name or identity.lead_id}. "
            f"Status={identity.current_status or 'unknown'}; "
            f"docs={len(docs)}; "
            f"positive/unsure criteria="
            f"{sum(1 for c in criteria if c.applicant_answer in {'yes', 'not_sure'})}."
        )

        return StandardizedProfile(
            case_id=identity.lead_id,
            identity=identity,
            summary=summary,
            criteria=criteria,
            claims=claims,
            evidence_index=[
                EvidenceItem(source="document", reference=d, excerpt="")
                for d in docs
                if d
            ],
            information_gaps=info_gaps,
            missing_information=[],  # MVP: no applicant follow-ups
            documents_processed=docs,
            readiness="ready_for_evaluation",
        )

    def run(self, lead_id: str) -> StandardizedProfile:
        bundle = load_case(lead_id, max_doc_chars=MAX_DOCUMENT_CHARS)
        seeded = self.build_seed_profile(bundle)

        if not self.use_llm:
            return seeded

        ensure_model_available(self.model, self.host)
        llm_data = chat_json(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(bundle),
            model=self.model,
            host=self.host,
        )
        # Force case/identity consistency
        llm_data["case_id"] = seeded.case_id
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
