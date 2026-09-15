"""Base evaluator utilities and intake→criterion mappings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..aao_examples import select_aao_examples
from ..config import DEFAULT_DISCLAIMER, OLLAMA_HOST, OLLAMA_MODEL
from ..kb_loader import category_section, kb_version, load_knowledge_base
from ..llm_judge import LLMJudge
from ..schema import CriterionEvaluation, EvaluationResult, VisaCategory
from ..scoring import (
    collect_mapped_facts,
    compact_education_facts,
    compact_employment_facts,
    compact_identity_facts,
    compact_salary_facts,
    merge_gap_lists,
    unique_facts,
)

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
    "eb1a_artistic_display": ["artistic_display"],
    "eb1a_leading_critical_role": ["critical_role"],
    "eb1a_high_salary": ["high_salary"],
    "eb1a_commercial_success_performing_arts": ["commercial_success"],
}


PROFILE_CONTEXT_LIMIT = 8

_ROLE_CRITERION_IDS = {"eb2_ea_ten_years_experience"}
_EDU_CRITERION_IDS = {"eb2_ea_academic_record"}
_SALARY_CRITERION_IDS = {"eb2_ea_salary"}


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
        """Short identity header shared by every call — not the evidence record."""
        return compact_identity_facts(intake)[:PROFILE_CONTEXT_LIMIT]

    def _criterion_facts(
        self,
        intake: dict[str, Any],
        intake_keys: list[str],
        criterion_id: str,
    ) -> tuple[list[str], list[str], str]:
        facts, gaps, answer = collect_mapped_facts(intake, intake_keys)
        extras: list[str] = []
        if "critical_role" in intake_keys or criterion_id in _ROLE_CRITERION_IDS:
            extras.extend(compact_employment_facts(intake))
        if criterion_id in _EDU_CRITERION_IDS:
            extras.extend(compact_education_facts(intake))
        if "high_salary" in intake_keys or criterion_id in _SALARY_CRITERION_IDS:
            extras.extend(compact_salary_facts(intake))
        return unique_facts(facts, extras), gaps, answer

    def llm_evaluate_criterion(
        self,
        *,
        intake: dict[str, Any],
        criterion_def: dict[str, Any],
        intake_keys: list[str],
        occupation_note: str = "",
        profile_classification: dict[str, Any] | None = None,
        observed_aao_pattern: dict[str, Any] | None = None,
        similar_sustained_cases: list[dict[str, Any]] | None = None,
        similar_denied_cases: list[dict[str, Any]] | None = None,
    ) -> CriterionEvaluation:
        facts, gaps, answer = self._criterion_facts(
            intake, intake_keys, str(criterion_def.get("criterion_id") or "")
        )
        examples = select_aao_examples(
            self.visa_category,
            str(criterion_def.get("criterion_id") or ""),
            intake,
        )
        if similar_sustained_cases or similar_denied_cases:
            examples = (similar_sustained_cases or [])[:2] + (similar_denied_cases or [])[:2]
        legal = list(criterion_def.get("required_elements") or [])
        judgment = self.judge.judge_criterion(
            visa_category=self.visa_category,
            criterion=criterion_def,
            applicant_facts=facts,
            information_gaps=gaps,
            dominant_answer=answer,
            profile_context=self.profile_context_facts(intake)[:PROFILE_CONTEXT_LIMIT],
            occupation_note=occupation_note or None,
            kb_principles={
                "applicant_statement_handling": self.principles.get("applicant_statement_handling"),
                "missing_documents": self.principles.get("missing_documents"),
                "missing_information": self.principles.get("missing_information"),
            },
            aao_illustrative_examples=examples or None,
            legal_requirement=legal or None,
            observed_aao_pattern=observed_aao_pattern,
            similar_sustained_cases=similar_sustained_cases,
            similar_denied_cases=similar_denied_cases,
            profile_classification=profile_classification,
        )
        recommended = judgment["recommended_evidence"] or list(
            criterion_def.get("recommended_evidence") or []
        )[:6]
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
            recommended_evidence=recommended,
            aao_illustrative_examples=examples,
            satisfied_elements=judgment.get("satisfied_elements") or [],
            missing_elements=judgment.get("missing_elements") or [],
            current_evidence_strengths=judgment["strengths"],
            current_evidence_weaknesses=judgment["weaknesses"],
            recommended_existing_evidence=recommended,
            legal_requirement=legal,
        )
