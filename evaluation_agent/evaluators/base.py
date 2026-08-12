"""Base evaluator utilities and intake→criterion mappings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..config import DEFAULT_DISCLAIMER, OLLAMA_HOST, OLLAMA_MODEL
from ..kb_loader import category_section, kb_version, load_knowledge_base
from ..llm_judge import LLMJudge
from ..schema import CriterionEvaluation, EvaluationResult, VisaCategory
from ..scoring import collect_mapped_facts, merge_gap_lists

# Intake questionnaire keys → knowledge-base criterion_ids
O1A_INTAKE_MAP: dict[str, list[str]] = {
    "o1a_awards": ["awards"],
    "o1a_membership": ["memberships"],
    "o1a_published_material": ["media"],
    "o1a_judging": ["judging", "peer_review"],
    "o1a_original_contributions": ["patents", "conferences"],
    "o1a_scholarly_authorship": ["publications", "google_scholar", "conferences"],
    "o1a_critical_essential_role": ["critical_role"],
    "o1a_high_salary": ["high_salary"],
}

EB1A_INTAKE_MAP: dict[str, list[str]] = {
    "eb1a_awards": ["awards"],
    "eb1a_membership": ["memberships"],
    "eb1a_published_material": ["media"],
    "eb1a_judging": ["judging", "peer_review"],
    "eb1a_original_contributions": ["patents", "conferences"],
    "eb1a_scholarly_articles": ["publications", "google_scholar", "conferences"],
    "eb1a_artistic_display": [],
    "eb1a_leading_critical_role": ["critical_role"],
    "eb1a_high_salary": ["high_salary"],
    "eb1a_commercial_success_performing_arts": [],
}


class BaseEvaluator(ABC):
    visa_category: VisaCategory

    def __init__(
        self,
        *,
        model: str = OLLAMA_MODEL,
        host: str = OLLAMA_HOST,
        judge: Optional[LLMJudge] = None,
    ) -> None:
        self.model = model
        self.host = host
        self.kb = load_knowledge_base(self.visa_category)
        self.section = category_section(self.kb, self.visa_category)
        self.instructions = self.kb.get("evaluation_agent_instructions") or {}
        self.principles = (self.kb.get("knowledge_base_metadata") or {}).get(
            "global_evaluation_principles"
        ) or {}
        self.judge = judge or LLMJudge(model=model, host=host, ensure_available=True)

    @abstractmethod
    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        raise NotImplementedError

    def _base_result(self, intake: dict[str, Any]) -> EvaluationResult:
        return EvaluationResult(
            case_id=str(intake.get("case_id") or (intake.get("identity") or {}).get("lead_id") or ""),
            visa_category=self.visa_category,
            knowledge_base_version=kb_version(self.kb),
            attorney_review_required=True,
            disclaimer=DEFAULT_DISCLAIMER,
        )

    def profile_context_facts(self, intake: dict[str, Any]) -> list[str]:
        facts: list[str] = []
        identity = intake.get("identity") or {}
        name = f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
        if name:
            facts.append(f"Applicant: {name}")
        if intake.get("field_of_endeavor"):
            facts.append(f"Field of endeavor: {intake['field_of_endeavor']}")
        if intake.get("summary"):
            facts.append(f"Intake summary: {intake['summary']}")
        for job in intake.get("employment") or []:
            org = job.get("organization") or ""
            title = job.get("title") or ""
            if org or title:
                facts.append(f"Employment: {title} at {org}".strip())
        for edu in intake.get("education") or []:
            deg = edu.get("degree") or ""
            inst = edu.get("institution") or ""
            if deg or inst:
                facts.append(f"Education: {deg} — {inst}".strip(" —"))
        for claim in intake.get("claims") or []:
            if claim:
                facts.append(f"Claim: {claim}")
        for ev in intake.get("evidence_index") or []:
            if not isinstance(ev, dict):
                continue
            source = str(ev.get("source") or "")
            if source not in {"url", "linkedin", "google_scholar", "media"}:
                continue
            excerpt = (ev.get("excerpt") or "").strip()
            ref = (ev.get("reference") or "").strip()
            if excerpt:
                facts.append(f"Fetched {source} ({ref}): {excerpt[:350]}")
        return facts

    def llm_evaluate_criterion(
        self,
        *,
        intake: dict[str, Any],
        criterion_def: dict[str, Any],
        intake_keys: list[str],
        occupation_note: str = "",
    ) -> CriterionEvaluation:
        facts, gaps, answer = collect_mapped_facts(intake, intake_keys)
        judgment = self.judge.judge_criterion(
            visa_category=self.visa_category,
            criterion=criterion_def,
            applicant_facts=facts,
            information_gaps=gaps,
            dominant_answer=answer,
            profile_context=self.profile_context_facts(intake)[:8],
            occupation_note=occupation_note or None,
            kb_principles={
                "applicant_statement_handling": self.principles.get("applicant_statement_handling"),
                "missing_documents": self.principles.get("missing_documents"),
                "missing_information": self.principles.get("missing_information"),
            },
        )
        return CriterionEvaluation(
            criterion_id=str(criterion_def.get("criterion_id") or ""),
            criterion_name=str(criterion_def.get("name") or criterion_def.get("criterion_id") or ""),
            status=judgment["status"],
            confidence=judgment["confidence"],
            applicant_facts=facts,  # never replace with LLM-invented facts
            reasoning_summary=judgment["reasoning_summary"],
            strengths=judgment["strengths"],
            weaknesses=judgment["weaknesses"],
            information_gaps=merge_gap_lists(gaps, judgment["information_gaps"], limit=8),
            recommended_evidence=judgment["recommended_evidence"]
            or list(criterion_def.get("recommended_evidence") or [])[:6],
        )
