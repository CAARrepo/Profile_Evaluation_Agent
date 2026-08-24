"""LLM criterion/prong judging helpers (straightforward Ollama calls, no ReAct)."""

from __future__ import annotations

from typing import Any, Optional

from .config import OLLAMA_HOST, OLLAMA_MODEL
from .llm import chat_json, ensure_model_available
from .prompts import (
    CRITERION_SYSTEM_PROMPT,
    FINAL_MERITS_SYSTEM_PROMPT,
    build_criterion_user_prompt,
    build_final_merits_user_prompt,
    build_niw_prong_user_prompt,
    build_niw_underlying_user_prompt,
)
from .schema import Confidence, CriterionStatus

_VALID_STATUS = {"strong", "potential", "weak", "not_indicated", "not_applicable"}
_VALID_CONF = {"high", "medium", "low"}


def _as_str_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _normalize_judgment(data: dict[str, Any]) -> dict[str, Any]:
    status = str(data.get("status") or "not_indicated").strip().lower()
    if status not in _VALID_STATUS:
        status = "not_indicated"
    confidence = str(data.get("confidence") or "low").strip().lower()
    if confidence not in _VALID_CONF:
        confidence = "low"
    reasoning = str(data.get("reasoning_summary") or data.get("reasoning") or "").strip()
    return {
        "status": status,  # type: CriterionStatus
        "confidence": confidence,  # type: Confidence
        "reasoning_summary": reasoning,
        "strengths": _as_str_list(data.get("strengths")),
        "weaknesses": _as_str_list(data.get("weaknesses")),
        "information_gaps": _as_str_list(data.get("information_gaps")),
        "recommended_evidence": _as_str_list(data.get("recommended_evidence")),
        "supporting_facts": _as_str_list(data.get("supporting_facts")),
        "qualifying_path": str(data.get("qualifying_path") or "").strip(),
        "satisfied_elements": _as_str_list(data.get("satisfied_elements")),
        "missing_elements": _as_str_list(data.get("missing_elements")),
    }


class LLMJudge:
    """Thin wrapper around Ollama for per-criterion evaluation."""

    def __init__(
        self,
        *,
        model: str = OLLAMA_MODEL,
        host: str = OLLAMA_HOST,
        ensure_available: bool = True,
    ) -> None:
        self.model = model
        self.host = host
        if ensure_available:
            ensure_model_available(self.model, self.host)

    def judge_criterion(
        self,
        *,
        visa_category: str,
        criterion: dict[str, Any],
        applicant_facts: list[str],
        information_gaps: list[str],
        dominant_answer: str,
        profile_context: Optional[list[str]] = None,
        occupation_note: Optional[str] = None,
        kb_principles: Optional[dict[str, Any]] = None,
        aao_illustrative_examples: Optional[list[dict[str, Any]]] = None,
        legal_requirement: Optional[list[str]] = None,
        observed_aao_pattern: Optional[dict[str, Any]] = None,
        similar_sustained_cases: Optional[list[dict[str, Any]]] = None,
        similar_denied_cases: Optional[list[dict[str, Any]]] = None,
        profile_classification: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        user = build_criterion_user_prompt(
            visa_category=visa_category,
            criterion=criterion,
            applicant_facts=applicant_facts,
            information_gaps=information_gaps,
            dominant_answer=dominant_answer,
            profile_context=profile_context,
            occupation_note=occupation_note,
            kb_principles=kb_principles,
            aao_illustrative_examples=aao_illustrative_examples,
            legal_requirement=legal_requirement,
            observed_aao_pattern=observed_aao_pattern,
            similar_sustained_cases=similar_sustained_cases,
            similar_denied_cases=similar_denied_cases,
            profile_classification=profile_classification,
        )
        raw = chat_json(
            system=CRITERION_SYSTEM_PROMPT,
            user=user,
            model=self.model,
            host=self.host,
        )
        return _normalize_judgment(raw)

    def judge_niw_underlying(
        self,
        *,
        part1: dict[str, Any],
        applicant_facts: list[str],
        information_gaps: list[str],
        profile_context: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        user = build_niw_underlying_user_prompt(
            part1=part1,
            applicant_facts=applicant_facts,
            information_gaps=information_gaps,
            profile_context=profile_context,
        )
        raw = chat_json(
            system=CRITERION_SYSTEM_PROMPT,
            user=user,
            model=self.model,
            host=self.host,
        )
        return _normalize_judgment(raw)

    def judge_niw_prong(
        self,
        *,
        prong: dict[str, Any],
        applicant_facts: list[str],
        information_gaps: list[str],
        profile_context: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        user = build_niw_prong_user_prompt(
            prong=prong,
            applicant_facts=applicant_facts,
            information_gaps=information_gaps,
            profile_context=profile_context,
        )
        raw = chat_json(
            system=CRITERION_SYSTEM_PROMPT,
            user=user,
            model=self.model,
            host=self.host,
        )
        return _normalize_judgment(raw)

    def judge_final_merits(
        self,
        *,
        visa_category: str,
        central_question: str,
        factors: list[str],
        negative_patterns: list[str],
        criterion_results: list[dict[str, Any]],
        applicant_facts: list[str],
        profile_classification: Optional[dict[str, Any]] = None,
        similar_cases: Optional[list[dict[str, Any]]] = None,
        criterion_aao_pattern_summaries: Optional[list[dict[str, Any]]] = None,
        representative_aao_cases: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        user = build_final_merits_user_prompt(
            visa_category=visa_category,
            central_question=central_question,
            factors=factors,
            negative_patterns=negative_patterns,
            criterion_results=criterion_results,
            applicant_facts=applicant_facts,
            profile_classification=profile_classification,
            similar_cases=similar_cases,
            criterion_aao_pattern_summaries=criterion_aao_pattern_summaries,
            representative_aao_cases=representative_aao_cases,
        )
        raw = chat_json(
            system=FINAL_MERITS_SYSTEM_PROMPT,
            user=user,
            model=self.model,
            host=self.host,
        )
        notes = _as_str_list(raw.get("notes"), limit=8)
        return {
            "sustained_acclaim_assessment": str(
                raw.get("sustained_acclaim_assessment") or raw.get("reasoning_summary") or ""
            ).strip(),
            "independent_recognition": str(raw.get("independent_recognition") or "").strip(),
            "recognition_beyond_employer": str(
                raw.get("recognition_beyond_employer") or ""
            ).strip(),
            "impact_significance": str(raw.get("impact_significance") or "").strip(),
            "standing_relative_to_field": str(
                raw.get("standing_relative_to_field") or ""
            ).strip(),
            "career_trajectory": str(raw.get("career_trajectory") or "").strip(),
            "overall_evidence_quality": str(raw.get("overall_evidence_quality") or "").strip(),
            "notes": notes,
        }
