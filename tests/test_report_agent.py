"""Tests for the Report Agent (initial user report)."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation_agent import EvaluationAgent
from report_agent import ReportAgent
from tests.fakes import FakeJudge

FIXTURES = Path(__file__).parent / "fixtures"


def test_initial_report_from_o1a_fixture(tmp_path: Path):
    evaluation = EvaluationAgent(judge=FakeJudge()).evaluate_intake(  # type: ignore[arg-type]
        json.loads((FIXTURES / "intake_o1a.json").read_text(encoding="utf-8"))
    )
    eval_dict = json.loads(evaluation.model_dump_json())
    intake = json.loads((FIXTURES / "intake_o1a.json").read_text(encoding="utf-8"))

    agent = ReportAgent()
    report, markdown = agent.generate_from_evaluation(
        eval_dict,
        intake=intake,
        evaluation_path="fixture",
    )

    assert report.attorney_reviewed is False
    assert report.attorney_review_required_later is True
    assert report.visa_category == "O-1A"
    assert report.applicant_name == "Alex Rivera"
    assert report.overall_profile_rating
    assert "not legal advice" in report.disclaimer.lower() or "preliminary" in report.disclaimer.lower()
    assert "Attorney reviewed:** No" in markdown
    assert "Initial O-1A Profile Assessment" in markdown
    assert "Recommended next evidence" in markdown

    md = tmp_path / "r.md"
    js = tmp_path / "r.json"
    md.write_text(markdown, encoding="utf-8")
    js.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    assert md.exists() and js.exists()


def test_initial_report_niw_includes_prongs():
    evaluation = EvaluationAgent(judge=FakeJudge()).evaluate_intake(  # type: ignore[arg-type]
        json.loads((FIXTURES / "intake_niw.json").read_text(encoding="utf-8"))
    )
    report, markdown = ReportAgent().generate_from_evaluation(
        json.loads(evaluation.model_dump_json()),
        intake=json.loads((FIXTURES / "intake_niw.json").read_text(encoding="utf-8")),
    )
    assert report.visa_category == "EB-2 NIW"
    assert report.niw_overview is not None
    assert "niw_prong_1" in markdown or "Substantial Merit" in markdown
    assert report.attorney_reviewed is False
