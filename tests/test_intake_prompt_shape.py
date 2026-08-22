"""Intake prompt should be category-aware for O-1A, EB-1A, and EB-2 NIW."""

from __future__ import annotations

import json

from intake_agent.agent import IntakeAgent
from intake_agent.category import detect_intake_category
from intake_agent.prompts import (
    COMPACT_OUTPUT_SHAPE,
    build_user_prompt,
    compact_output_shape,
    criteria_keys_for,
    system_prompt,
)
from intake_agent.schema import CaseBundle, StandardizedProfile


def test_compact_shape_is_much_smaller_than_pydantic_schema():
    full = json.dumps(StandardizedProfile.model_json_schema(), ensure_ascii=False, indent=2)
    compact = json.dumps(COMPACT_OUTPUT_SHAPE, ensure_ascii=False, indent=2)
    assert len(compact) < len(full) * 0.25
    assert "identity" not in COMPACT_OUTPUT_SHAPE
    assert "missing_information" not in COMPACT_OUTPUT_SHAPE


def test_intake_prompt_uses_compact_shape_not_json_schema():
    bundle = CaseBundle(
        lead={
            "id": "abc",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "immigration_category": "O1_VISA",
        },
        questionnaire={"answers": {"awards": {"answer": "no"}}},
        document_texts=[],
    )
    prompt = build_user_prompt(bundle)
    assert "output_shape" in prompt
    assert "output_json_schema" not in prompt
    assert "$defs" not in prompt
    assert "ApplicantIdentity" not in prompt


def test_detect_intake_category_all_three():
    assert detect_intake_category({"immigration_category": "O1_VISA"}) == "O-1A"
    assert detect_intake_category({"immigration_category": "EB1A"}) == "EB-1A"
    assert detect_intake_category({"immigration_category": "EB2_NIW"}) == "EB-2 NIW"
    assert detect_intake_category({"immigration_category": "H1B"}) == ""


def _bundle(category: str) -> CaseBundle:
    return CaseBundle(
        lead={"id": "x", "first_name": "Test", "last_name": "User", "immigration_category": category},
        questionnaire={"answers": {}},
        document_texts=[],
    )


def test_o1a_prompt_is_o1a_not_generic_only():
    prompt = build_user_prompt(_bundle("O1_VISA"))
    sys = system_prompt("O-1A")
    assert '"visa_category": "O-1A"' in prompt
    assert "eight O-1A regulatory criteria" in sys
    assert "Dhanasar" not in sys
    assert "artistic_display" not in json.loads(prompt)["criteria_keys"]


def test_eb1a_prompt_includes_ten_criteria_and_arts_keys():
    prompt = build_user_prompt(_bundle("EB1A"))
    sys = system_prompt("EB-1A")
    data = json.loads(prompt)
    assert data["visa_category"] == "EB-1A"
    assert "artistic_display" in data["criteria_keys"]
    assert "commercial_success" in data["criteria_keys"]
    assert "This lead is EB-1A (not O-1A)" in sys
    assert "ten EB-1A regulatory criteria" in sys
    assert "Produce a StandardizedProfile JSON for this O-1A MVP case" not in prompt


def test_niw_prompt_includes_dhanasar_and_endeavor_fields():
    prompt = build_user_prompt(_bundle("EB2_NIW"))
    sys = system_prompt("EB-2 NIW")
    data = json.loads(prompt)
    assert data["visa_category"] == "EB-2 NIW"
    assert "proposed_endeavor" in data["output_shape"]
    assert "national_importance_summary" in data["output_shape"]
    assert "Dhanasar" in sys
    assert "This lead is EB-2 NIW (not O-1A)" in sys
    assert "artistic_display" not in data["criteria_keys"]
    assert "proposed_endeavor" not in compact_output_shape("O-1A")


def test_seed_profile_uses_detected_category_and_eb1a_extra_keys():
    o1 = IntakeAgent(use_llm=False).build_seed_profile(_bundle("O1_VISA"))
    assert o1.visa_category == "O-1A"
    assert o1.summary.startswith("O-1A intake")
    assert {c.key.value for c in o1.criteria} == set(criteria_keys_for("O-1A"))

    eb1 = IntakeAgent(use_llm=False).build_seed_profile(_bundle("EB1A"))
    assert eb1.visa_category == "EB-1A"
    assert eb1.summary.startswith("EB-1A intake")
    keys = {c.key.value for c in eb1.criteria}
    assert "artistic_display" in keys
    assert "commercial_success" in keys

    niw = IntakeAgent(use_llm=False).build_seed_profile(_bundle("EB2_NIW"))
    assert niw.visa_category == "EB-2 NIW"
    assert niw.summary.startswith("EB-2 NIW intake")
    assert "artistic_display" not in {c.key.value for c in niw.criteria}
