"""Tests for the Report Agent (Markdown/JSON + polished client PDF)."""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader

from evaluation_agent import EvaluationAgent
from report_agent import ReportAgent
from report_agent.pdf_report import write_client_pdf
from report_agent.text_utils import complete_sentences, fix_mojibake
from tests.fakes import FakeJudge

FIXTURES = Path(__file__).parent / "fixtures"


def _eval_o1a() -> tuple[dict, dict]:
    intake = json.loads((FIXTURES / "intake_o1a.json").read_text(encoding="utf-8"))
    evaluation = EvaluationAgent(judge=FakeJudge()).evaluate_intake(intake)  # type: ignore[arg-type]
    return json.loads(evaluation.model_dump_json()), intake


def test_fix_mojibake_and_complete_sentences():
    assert "—" in fix_mojibake("A â€” B")
    assert "’" in fix_mojibake("applicantâ€™s")
    long = (
        "First complete sentence about the criterion. "
        "Second complete sentence adds context. "
        "Third complete sentence is optional. "
        "Fourth should be dropped."
    )
    shortened = complete_sentences(long, max_sentences=2)
    assert shortened.endswith(".")
    assert "Fourth" not in shortened
    assert "..." not in shortened
    # Never mid-word cut
    messy = "This is a complete sentence. This fragment is incomplete and cut off mid"
    out = complete_sentences(messy, max_sentences=2)
    assert out.endswith(".")
    assert not out.endswith("mid")


def test_initial_report_markdown_json_and_pdf(tmp_path: Path):
    eval_dict, intake = _eval_o1a()
    agent = ReportAgent()
    report, markdown, client = agent.generate_from_evaluation(
        eval_dict,
        intake=intake,
        evaluation_path="fixture",
    )

    assert report.attorney_reviewed is False
    assert report.visa_category == "O-1A"
    assert report.applicant_name == "Alex Rivera"
    assert "Initial O-1A Profile Evaluation" in markdown
    assert "Initial O-1A Profile Evaluation" == client.document_title
    assert "Attorney reviewed:** No" in markdown

    # Internal statuses preserved
    for row in report.criteria_overview:
        assert row["status"] in {
            "strong",
            "potential",
            "weak",
            "not_indicated",
            "not_applicable",
        }
        assert "client_status_label" in row

    # Client-friendly labels in presentation content
    labels = " ".join(r.client_status_label for r in client.criterion_rows)
    assert "Potentially supportable" in labels or "Strong evidence" in labels

    pdf_path = tmp_path / f"{report.case_id}_initial_profile_evaluation.pdf"
    write_client_pdf(client, pdf_path)
    assert pdf_path.is_file() and pdf_path.stat().st_size > 1000

    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Initial O-1A Profile Evaluation" in text
    assert "â€”" not in text
    assert "â€™" not in text
    assert "Preliminary AI-assisted profile evaluation" not in text
    assert "End of initial profile evaluation" not in text
    assert "attorney review not completed" not in text.lower()
    assert "<b>" not in text
    assert "</b>" not in text
    # Concise-ish: normal fixture should stay within a reasonable page budget
    assert 1 <= len(reader.pages) <= 6

    md = tmp_path / "r.md"
    js = tmp_path / "r.json"
    md.write_text(markdown, encoding="utf-8")
    js.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    assert md.exists() and js.exists()


def test_zero_strong_multiple_potential_clarification(tmp_path: Path):
    eval_dict, intake = _eval_o1a()
    # Force snapshot: 0 strong, 6 potential
    for c in eval_dict["criteria"]:
        c["status"] = "potential"
    eval_dict["criteria_summary"] = {
        "strong": 0,
        "potential": 6,
        "weak": 0,
        "not_indicated": 2,
        "not_applicable": 0,
    }
    eval_dict["overall_profile_rating"] = "promising"

    _, _, client = ReportAgent().generate_from_evaluation(eval_dict, intake=intake)
    joined = " ".join(client.overall_assessment_paragraphs)
    assert "Six criteria were identified for possible evidence development" in joined
    assert "None is currently assessed as strongly supported" in joined
    assert "does not mean that the O-1A criterion has been satisfied" in joined

    pdf_path = tmp_path / "promising_clarification.pdf"
    write_client_pdf(client, pdf_path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    assert "Six criteria were identified for possible evidence development" in text
    assert "does not mean that the O-1A criterion has been satisfied" in text


def test_evidence_consolidated_and_no_mid_sentence_cut():
    eval_dict, intake = _eval_o1a()
    # Inject duplicate evidence + long reasoning with mojibake
    for c in eval_dict["criteria"]:
        if c.get("status") in {"strong", "potential", "weak"}:
            c["recommended_evidence"] = [
                "Award certificate",
                "award certificate",
                "Official award webpage",
                "Award certificate.",
            ]
            c["reasoning_summary"] = (
                "Applicantâ€™s stated facts may map to this criterion. "
                "Additional independent documentation would strengthen the record. "
                "This third sentence remains complete."
            )
            break
    _, markdown, client = ReportAgent().generate_from_evaluation(eval_dict, intake=intake)
    assert "â€”" not in markdown and "â€™" not in markdown
    for row in client.criterion_rows:
        assert not row.explanation.endswith("...")
        assert "â€™" not in row.explanation
        # duplicates collapsed
        lowered = [e.lower().rstrip(".") for e in row.top_evidence]
        assert len(lowered) == len(set(lowered))


def test_generate_and_save_writes_pdf(tmp_path: Path):
    eval_dict, intake = _eval_o1a()
    eval_dir = tmp_path / "eval"
    intake_dir = tmp_path / "intake"
    out_dir = tmp_path / "out"
    eval_dir.mkdir()
    intake_dir.mkdir()
    case_id = eval_dict["case_id"]
    (eval_dir / f"{case_id}_evaluation.json").write_text(
        json.dumps(eval_dict), encoding="utf-8"
    )
    (intake_dir / f"{case_id}_intake.json").write_text(json.dumps(intake), encoding="utf-8")

    md, js, pdf = ReportAgent().generate_and_save(
        case_id,
        eval_dir=eval_dir,
        intake_dir=intake_dir,
        output_dir=out_dir,
    )
    assert md.exists() and js.exists() and pdf.exists()
    assert pdf.name == f"{case_id}_initial_profile_evaluation.pdf"
    data = json.loads(js.read_text(encoding="utf-8"))
    # Internal rating preserved; statuses not rewritten by report agent
    assert data["overall_profile_rating"] == eval_dict["overall_profile_rating"]
    assert data["attorney_reviewed"] is False


def test_initial_report_niw_includes_prongs():
    evaluation = EvaluationAgent(judge=FakeJudge()).evaluate_intake(  # type: ignore[arg-type]
        json.loads((FIXTURES / "intake_niw.json").read_text(encoding="utf-8"))
    )
    report, markdown, client = ReportAgent().generate_from_evaluation(
        json.loads(evaluation.model_dump_json()),
        intake=json.loads((FIXTURES / "intake_niw.json").read_text(encoding="utf-8")),
    )
    assert report.visa_category == "EB-2 NIW"
    assert client.document_title == "Initial EB-2 NIW Profile Evaluation"
    assert "Substantial Merit" in markdown or any(
        "Substantial" in r.criterion_name for r in client.criterion_rows
    )
    assert report.attorney_reviewed is False
