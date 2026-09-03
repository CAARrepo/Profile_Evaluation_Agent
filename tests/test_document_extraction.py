"""PDF excerpts are mapped onto intake criteria and passed to evaluation."""

from __future__ import annotations

from evaluation_agent import EvaluationAgent
from evaluation_agent.evaluators.base import PROFILE_CONTEXT_LIMIT
from evaluation_agent.evaluators.o1a import O1AEvaluator
from evaluation_agent.scoring import collect_mapped_facts
from intake_agent.agent import IntakeAgent, merge_profiles
from intake_agent.documents import criterion_keys_for_document
from intake_agent.loaders import extract_documents
from intake_agent.prompts import build_user_prompt, system_prompt
from intake_agent.source_extract import attach_extracted_sources, window_source_text
from intake_agent.schema import (
    ApplicantIdentity,
    CaseBundle,
    CriterionIntake,
    EvidenceItem,
    EvidenceStatus,
    IntakeCriterionKey,
    StandardizedProfile,
)
from tests.fakes import FakeJudge


def test_folder_and_filename_map_onto_criteria():
    assert criterion_keys_for_document(
        filename="1099-NEC_2025.pdf",
        relative_path="lead/o1-w2/1099-NEC_2025.pdf",
    ) == ["high_salary"]
    assert "awards" in criterion_keys_for_document(
        filename="DARPA_awardable.pdf",
        relative_path="lead/o1-employer-award/DARPA_awardable.pdf",
    )
    keys = criterion_keys_for_document(
        filename="NeurIPS_invite.pdf",
        relative_path="lead/o1-peer-invite/NeurIPS_invite.pdf",
    )
    assert "peer_review" in keys and "judging" in keys
    assert criterion_keys_for_document(
        filename="resume.pdf",
        relative_path="lead/resume/resume.pdf",
    ) == []


def test_seed_profile_attaches_pdf_excerpts():
    bundle = CaseBundle(
        lead={
            "id": "lead-pdf",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "immigration_category": "O1_VISA",
        },
        questionnaire={"answers": {}},
        document_texts=[
            {
                "filename": "1099-NEC_2025.pdf",
                "relative_path": "lead-pdf/o1-w2/1099-NEC_2025.pdf",
                "text": "Form 1099-NEC 2025 payer Example Co nonemployee compensation 85000",
            },
            {
                "filename": "resume.pdf",
                "relative_path": "lead-pdf/resume/resume.pdf",
                "text": "Ada Lovelace, research scientist in biometrics.",
            },
        ],
    )
    profile = IntakeAgent(use_llm=False).build_seed_profile(bundle)
    salary = next(c for c in profile.criteria if c.key == IntakeCriterionKey.HIGH_SALARY)
    assert any("1099-NEC" in e.reference and "85000" in e.excerpt for e in salary.evidence_items)
    assert salary.evidence_status == EvidenceStatus.PARTIALLY_SUPPORTED
    resume_item = next(e for e in profile.evidence_index if "resume.pdf" in e.reference)
    assert "biometrics" in resume_item.excerpt


def test_merge_keeps_seeded_pdf_excerpts_when_llm_omits_them():
    seeded = StandardizedProfile(
        case_id="lead-pdf",
        identity=ApplicantIdentity(lead_id="lead-pdf", first_name="Ada", last_name="Lovelace"),
        visa_category="O-1A",
        summary="O-1A intake for Ada Lovelace.",
        criteria=[
            CriterionIntake(
                key=IntakeCriterionKey.HIGH_SALARY,
                applicant_answer="yes",
                claim_summary="Compensation claimed at 200000",
                evidence_status=EvidenceStatus.PARTIALLY_SUPPORTED,
                evidence_items=[
                    EvidenceItem(
                        source="document",
                        reference="1099-NEC_2025.pdf",
                        excerpt="Form 1099-NEC compensation 85000",
                    )
                ],
            )
        ],
        evidence_index=[
            EvidenceItem(
                source="document",
                reference="1099-NEC_2025.pdf",
                excerpt="Form 1099-NEC compensation 85000",
            )
        ],
    )
    merged = merge_profiles(
        seeded,
        {
            "case_id": "lead-pdf",
            "identity": {"lead_id": "lead-pdf", "first_name": "Ada", "last_name": "Lovelace"},
            "visa_category": "O-1A",
            "summary": "O-1A intake for Ada Lovelace.",
            "criteria": [
                {
                    "key": "high_salary",
                    "applicant_answer": "yes",
                    "claim_summary": "Compensation claimed at 200000",
                    "evidence_status": "claim_only",
                    "evidence_items": [],
                }
            ],
            "evidence_index": [
                {"source": "document", "reference": "1099-NEC_2025.pdf", "excerpt": ""}
            ],
        },
    )
    salary = next(c for c in merged.criteria if c.key == IntakeCriterionKey.HIGH_SALARY)
    assert any("85000" in e.excerpt for e in salary.evidence_items)
    assert any(e.excerpt and "85000" in e.excerpt for e in merged.evidence_index)


def test_intake_prompt_includes_pdf_text_for_llm_extraction():
    bundle = CaseBundle(
        lead={"id": "x", "first_name": "Ada", "last_name": "Lovelace", "immigration_category": "O1_VISA"},
        questionnaire={"answers": {}},
        document_texts=[
            {
                "filename": "1099-NEC_2025.pdf",
                "relative_path": "x/o1-w2/1099-NEC_2025.pdf",
                "text": "Form 1099-NEC nonemployee compensation 85000",
            }
        ],
    )
    prompt = build_user_prompt(bundle)
    assert "Form 1099-NEC nonemployee compensation 85000" in prompt
    assert "extract_from_uploaded_pdfs" in prompt
    sys = system_prompt("O-1A")
    assert "documents[] contains extracted PDF text" in sys


def test_evaluation_receives_pdf_excerpts_as_facts():
    intake = {
        "case_id": "lead-pdf",
        "visa_category": "O-1A",
        "identity": {"first_name": "Ada", "last_name": "Lovelace", "lead_id": "lead-pdf"},
        "field_of_endeavor": "AI",
        "claims": ["high_salary: compensation claimed"],
        "criteria": [
            {
                "key": "high_salary",
                "applicant_answer": "yes",
                "claim_summary": "compensation claimed",
                "evidence_items": [
                    {
                        "source": "document",
                        "reference": "1099-NEC_2025.pdf",
                        "excerpt": "Form 1099-NEC nonemployee compensation 85000",
                    }
                ],
            }
        ],
        "evidence_index": [
            {
                "source": "document",
                "reference": "resume.pdf",
                "excerpt": "Ada Lovelace research scientist in biometrics",
            }
        ],
    }
    facts, _, _ = collect_mapped_facts(intake, ["high_salary"])
    assert any("1099-NEC" in f and "85000" in f for f in facts)

    context = O1AEvaluator(judge=FakeJudge()).profile_context_facts(intake)  # type: ignore[arg-type]
    assert any("Uploaded PDF (resume.pdf)" in line for line in context)
    assert context.index(next(line for line in context if "Uploaded PDF" in line)) < PROFILE_CONTEXT_LIMIT

    agent = EvaluationAgent(judge=FakeJudge())  # type: ignore[arg-type]
    result = agent.evaluate_intake(intake)
    salary = next(c for c in result.criteria if c.criterion_id == "o1a_high_salary")
    assert any("85000" in f for f in salary.applicant_facts)


def test_extract_documents_keeps_every_file(tmp_path):
    files = []
    for name, body in (
        ("resume.txt", "Applicant resume text " * 20),
        ("1099-NEC_2025.txt", "Form 1099-NEC compensation 85000"),
        ("Review_Submitted.txt", "Review submitted to NeurIPS 2026"),
    ):
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        files.append(path)
    docs = extract_documents(files)
    assert len(docs) == 3
    assert all(d["text"] and not str(d["text"]).startswith("[omitted:") for d in docs)
    assert any("1099-NEC" in d["filename"] and "85000" in d["text"] for d in docs)


def test_window_source_text_keeps_head_and_tail():
    blob = "A" * 8000 + "MIDDLE" + "B" * 8000
    windowed = window_source_text(blob, limit=100)
    assert windowed.startswith("A")
    assert windowed.endswith("B")
    assert "middle omitted" in windowed


def test_attach_extracted_sources_maps_1099_facts():
    profile = StandardizedProfile(
        case_id="lead-pdf",
        identity=ApplicantIdentity(lead_id="lead-pdf", first_name="Ada", last_name="Lovelace"),
        visa_category="O-1A",
        criteria=[
            CriterionIntake(key=IntakeCriterionKey.HIGH_SALARY, applicant_answer="yes")
        ],
        evidence_index=[
            EvidenceItem(source="document", reference="1099-NEC_2025.pdf", excerpt="")
        ],
    )
    bundle = CaseBundle(
        lead={"id": "lead-pdf"},
        document_texts=[
            {
                "filename": "1099-NEC_2025.pdf",
                "relative_path": "lead/o1-w2/1099-NEC_2025.pdf",
                "text": "Form 1099-NEC nonemployee compensation 85000",
                "extracted_facts": ["1099-NEC shows nonemployee compensation of 85000."],
                "extracted": {
                    "criteria_keys": ["high_salary"],
                    "facts": ["1099-NEC shows nonemployee compensation of 85000."],
                    "excerpts": ["nonemployee compensation 85000"],
                },
            }
        ],
    )
    attach_extracted_sources(profile, bundle)
    salary = next(c for c in profile.criteria if c.key == IntakeCriterionKey.HIGH_SALARY)
    assert any("85000" in e.excerpt for e in salary.evidence_items)
    assert profile.evidence_index[0].excerpt
