"""LLM criterion/prong judging helpers (straightforward Ollama calls, no ReAct)."""

from __future__ import annotations

from typing import Any, Optional

from .config import OLLAMA_HOST, OLLAMA_MODEL
from .llm import chat_json, ensure_model_available
from .prompts import (
    CRITERION_SYSTEM_PROMPT,
    build_criterion_user_prompt,
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
