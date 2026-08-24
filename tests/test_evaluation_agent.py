"""Basic Evaluation Agent tests for O-1A, EB-1A, and EB-2 NIW (LLM mocked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_agent import EvaluationAgent
from evaluation_agent.router import detect_visa_category
from tests.fakes import FakeJudge

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def agent() -> EvaluationAgent:
    return EvaluationAgent(judge=FakeJudge())  # type: ignore[arg-type]


def test_detect_categories():
    assert detect_visa_category(_load("intake_o1a.json")) == "O-1A"
    assert detect_visa_category(_load("intake_eb1a.json")) == "EB-1A"
    assert detect_visa_category(_load("intake_niw.json")) == "EB-2 NIW"


def test_o1a_evaluation_structure(agent: EvaluationAgent):
    result = agent.evaluate_intake(_load("intake_o1a.json"))
    assert result.visa_category == "O-1A"
    assert result.attorney_review_required is True
    assert result.disclaimer
    assert result.final_merits is not None
    assert len(result.criteria) == 8
    ids = {c.criterion_id for c in result.criteria}
    assert "o1a_awards" in ids
    assert "o1a_judging" in ids
    awards = next(c for c in result.criteria if c.criterion_id == "o1a_awards")
    assert awards.status in {"strong", "potential", "weak"}
    assert awards.status != "not_indicated"
    assert result.overall_profile_rating in {
        "very_strong",
        "strong",
        "promising",
        "developing",
        "insufficient_information",
    }
    salary = next(c for c in result.criteria if c.criterion_id == "o1a_high_salary")
    assert salary.status == "weak"
    assert salary.information_gaps or salary.weaknesses
    assert result.raw_notes.get("evaluation_method") == "ollama_llm_per_criterion"


def test_eb1a_evaluation_structure(agent: EvaluationAgent):
    result = agent.evaluate_intake(_load("intake_eb1a.json"))
    assert result.visa_category == "EB-1A"
    assert result.final_merits is not None
    assert result.profile_classification is not None
    assert "STEP 1" in " ".join(result.final_merits.notes) or "final merits" in " ".join(result.final_merits.notes).lower()
    assert len(result.criteria) == 10
    arts = next(c for c in result.criteria if c.criterion_id == "eb1a_commercial_success_performing_arts")
    assert arts.status == "not_applicable"
    pubs = next(c for c in result.criteria if c.criterion_id == "eb1a_scholarly_articles")
    assert pubs.status in {"strong", "potential"}
    assert result.criteria_summary.strong + result.criteria_summary.potential >= 3


def test_niw_evaluation_structure(agent: EvaluationAgent):
    result = agent.evaluate_intake(_load("intake_niw.json"))
    assert result.visa_category == "EB-2 NIW"
    assert result.underlying_eb2 is not None
    assert result.underlying_eb2.status in {"strong", "potential", "weak", "not_indicated"}
    assert len(result.niw_prongs) == 3
    prong_ids = {p.prong_id for p in result.niw_prongs}
    assert prong_ids == {"niw_prong_1", "niw_prong_2", "niw_prong_3"}
    assert result.underlying_eb2.qualifying_path in {
        "eb2_advanced_degree",
        "bachelors_plus_five_or_exceptional_ability",
        "eb2_exceptional_ability",
        "",
    }
    assert result.underlying_eb2.status in {"strong", "potential"}
    assert result.recommended_next_evidence


def test_category_override(agent: EvaluationAgent):
    intake = _load("intake_o1a.json")
    result = agent.evaluate_intake(intake, category_override="EB-1A")
    assert result.visa_category == "EB-1A"
    assert len(result.criteria) == 10
