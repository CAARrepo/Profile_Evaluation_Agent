"""Intake Agent: assemble case → structure with local LLM → validate profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

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
    MissingInfoRequest,
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
        if answer == "yes":
            status = EvidenceStatus.CLAIM_ONLY
            if details:
                evidence_items.append(
                    EvidenceItem(
                        source="questionnaire",
                        reference=f"sectionB.criteria.{key}",
                        excerpt=details[:800],
                    )
                )
                # URLs in details are still claims until Evidence Agents verify them
                if details.lower().startswith("http"):
                    gaps.append("Verify linked source belongs to applicant and substantively covers them/their work")
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
            gaps.append("Applicant unsure — needs clarification")
        elif answer == "no":
            status = EvidenceStatus.MISSING

        seeded[criterion_key] = CriterionIntake(
            key=criterion_key,
            applicant_answer=answer,  # type: ignore[arg-type]
            claim_summary=details[:500] if details else "",
            evidence_status=status,
            evidence_items=evidence_items,
            gaps=gaps,
        )

    # Ensure all criteria appear in the profile
    for key in O1CriterionKey:
        if key not in seeded:
            seeded[key] = CriterionIntake(key=key, applicant_answer="unknown", evidence_status=EvidenceStatus.MISSING)

    return [seeded[k] for k in O1CriterionKey]


def deterministic_missing(bundle: CaseBundle, identity: ApplicantIdentity) -> list[MissingInfoRequest]:
    requests: list[MissingInfoRequest] = []
    if not bundle.questionnaire:
        requests.append(
            MissingInfoRequest(
                priority="high",
                topic="questionnaire",
                question="Please complete the O-1 detailed questionnaire.",
                reason="No questionnaire answers found for this lead.",
            )
        )
    if not bundle.document_texts:
        requests.append(
            MissingInfoRequest(
                priority="high",
                topic="resume",
                question="Please upload a current résumé / CV (PDF or DOCX).",
                reason="No documents found under lead-documents for this lead.",
            )
        )
    if not identity.linkedin_url:
        requests.append(
            MissingInfoRequest(
                priority="medium",
                topic="linkedin",
                question="Please provide your LinkedIn profile URL.",
                reason="LinkedIn helps verify employment history and public recognition.",
            )
        )
    if identity.us_job_offer in {"", "unknown"} and not identity.self_employment_planned:
        requests.append(
            MissingInfoRequest(
                priority="high",
                topic="sponsorship",
                question="Do you have a U.S. job offer or plan to pursue O-1 via a U.S. agent / self-employment?",
                reason="O-1 requires a U.S. petitioner (employer or agent).",
            )
        )
    return requests


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

    # Merge missing-info lists (dedupe by question)
    seen = {m.question for m in llm_profile.missing_information}
    for m in seeded.missing_information:
        if m.question not in seen:
            llm_profile.missing_information.append(m)

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
    if llm_profile.readiness == "needs_more_info" and seeded.readiness == "incomplete":
        llm_profile.readiness = "incomplete"
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
        missing = deterministic_missing(bundle, identity)
        docs = [d.get("filename") or d.get("path") or "" for d in bundle.document_texts]

        claims: list[str] = []
        for c in criteria:
            if c.applicant_answer in {"yes", "not_sure"} and c.claim_summary:
                claims.append(f"{c.key.value}: {c.claim_summary}")

        readiness = "ready_for_evidence_agents"
        if not bundle.questionnaire or not bundle.document_texts:
            readiness = "incomplete"
        elif len(missing) >= 3:
            readiness = "needs_more_info"

        name = f"{identity.first_name} {identity.last_name}".strip()
        summary = (
            f"O-1 intake for {name or identity.lead_id}. "
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
            missing_information=missing,
            documents_processed=docs,
            readiness=readiness,  # type: ignore[arg-type]
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
