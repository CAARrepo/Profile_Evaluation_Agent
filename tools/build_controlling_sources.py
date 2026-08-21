"""Build 01_Controlling_Sources/ for the EB-1A and EB-2 NIW knowledge bases.

Mirrors the layout produced for O-1A by tools/aao_build_kb.py: each category
gets a CFR folder holding the binding regulatory elements and a
USCIS_Policy_Manual folder holding adjudicative guidance, so the two authority
levels are never mixed.

Sources are the curated evaluation knowledge bases:
  knowledge_base/EB1A_Knowledge_Base/EB1A_evaluation_knowledge_base.json
  knowledge_base/EB2NIW_Knowledge_Base/EB2_NIW_evaluation_knowledge_base.json

The *_original folders are read-only archives and are never touched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge_base"

EB1A_HOME = KB_DIR / "EB1A_Knowledge_Base"
NIW_HOME = KB_DIR / "EB2NIW_Knowledge_Base"

EB1A_SRC = EB1A_HOME / "EB1A_evaluation_knowledge_base.json"
NIW_SRC = NIW_HOME / "EB2_NIW_evaluation_knowledge_base.json"

ROMAN = {1: "i", 2: "ii", 3: "iii", 4: "iv", 5: "v", 6: "vi", 7: "vii", 8: "viii",
         9: "ix", 10: "x"}
LETTER = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}

REGULATION_AUTHORITY = "Federal regulation — binding"
POLICY_AUTHORITY = (
    "USCIS policy guidance — binding on USCIS officers, not a regulation"
)
CONTENT_NOTE_CFR = (
    "Structured restatement of the regulatory elements, not verbatim regulatory "
    "text. Quote the eCFR directly when exact wording matters."
)
CONTENT_NOTE_PM = (
    "Structured restatement of adjudicative guidance and evidence expectations, "
    "not verbatim Policy Manual text."
)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def pick_sources(kb: dict[str, Any], needles: list[str]) -> list[dict[str, Any]]:
    """Select the primary_sources entries relevant to one classification."""
    sources = (kb.get("knowledge_base_metadata") or {}).get("primary_sources", [])
    return [
        s
        for s in sources
        if any(n.lower() in str(s.get("name", "")).lower() for n in needles)
    ]


def build_eb1a() -> None:
    kb = json.loads(EB1A_SRC.read_text(encoding="utf-8"))
    meta = kb.get("knowledge_base_metadata", {})
    eb = kb.get("EB1A", {})
    criteria = eb.get("criteria", [])
    generated = date.today().isoformat()
    derived_from = "knowledge_base/EB1A_Knowledge_Base/EB1A_evaluation_knowledge_base.json"

    cfr = {
        "source_metadata": {
            "title": "8 CFR 204.5(h) — EB-1A extraordinary ability regulatory framework",
            "authority": REGULATION_AUTHORITY,
            "citations": [
                "INA 203(b)(1)(A), 8 USC 1153(b)(1)(A) (extraordinary ability classification)",
                "8 CFR 204.5(h)(2) (definition of extraordinary ability)",
                "8 CFR 204.5(h)(3) (initial evidence: one-time achievement or three of ten criteria)",
                "8 CFR 204.5(h)(3)(i)-(x) (the ten evidentiary criteria)",
                "8 CFR 204.5(h)(4) (comparable evidence)",
                "8 CFR 204.5(h)(5) (intent to continue work in the area of expertise)",
            ],
            "official_url": (
                "https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-204/"
                "subpart-A/section-204.5"
            ),
            "derived_from": derived_from,
            "content_note": CONTENT_NOTE_CFR,
            "generated_date": generated,
        },
        "definition_of_extraordinary_ability": eb.get("core_legal_standard"),
        "field_scope": eb.get("field_scope"),
        "statutory_and_regulatory_features": eb.get("key_features"),
        "threshold_structure": {
            "path_A": (eb.get("major_one_time_achievement") or {}).get(
                "concept",
                "Evidence of a one-time achievement (major, internationally recognized award).",
            ),
            "path_B": (eb.get("two_step_evaluation") or {}).get(
                "step_1_regulatory_criteria"
            ),
            "comparable_evidence": (eb.get("comparable_evidence") or {}).get("rule"),
            "continue_work_requirement": (eb.get("continue_work_in_us") or {}).get(
                "requirement"
            ),
            "threshold_warning": (eb.get("two_step_evaluation") or {}).get(
                "critical_warning"
            ),
        },
        "one_time_achievement_path": {
            "name": (eb.get("major_one_time_achievement") or {}).get("name"),
            "concept": (eb.get("major_one_time_achievement") or {}).get("concept"),
        },
        "evidentiary_criteria": [
            {
                "criterion_id": c.get("criterion_id"),
                "number": c.get("number"),
                "citation": f"8 CFR 204.5(h)(3)({ROMAN.get(c.get('number'), '?')})",
                "name": c.get("name"),
                "required_elements": c.get("required_elements"),
            }
            for c in criteria
        ],
        "comparable_evidence": eb.get("comparable_evidence"),
        "continue_work_in_us": eb.get("continue_work_in_us"),
        "regulatory_sources": pick_sources(kb, ["204.5(h)"]),
    }

    pm = {
        "source_metadata": {
            "title": (
                "USCIS Policy Manual, Volume 6, Part F, Chapter 2 — "
                "EB-1A adjudicative guidance"
            ),
            "authority": POLICY_AUTHORITY,
            "citations": [
                "USCIS Policy Manual, Volume 6, Part F, Chapter 2 (extraordinary ability)",
                "USCIS Policy Manual, Volume 6, Part F, Appendix (evidence examples, "
                "including STEM considerations)",
            ],
            "official_url": "https://www.uscis.gov/policy-manual/volume-6-part-f-chapter-2",
            "derived_from": derived_from,
            "content_note": CONTENT_NOTE_PM,
            "generated_date": generated,
        },
        "two_step_evaluation": eb.get("two_step_evaluation"),
        "one_time_achievement_guidance": {
            "evaluation_factors": (eb.get("major_one_time_achievement") or {}).get(
                "evaluation_factors"
            )
        },
        "evidence_guidance_by_criterion": [
            {
                "criterion_id": c.get("criterion_id"),
                "number": c.get("number"),
                "name": c.get("name"),
                "evaluation_focus": c.get("evaluation_focus"),
                "recommended_evidence": c.get("recommended_evidence"),
                "common_weaknesses": c.get("common_weaknesses"),
            }
            for c in criteria
        ],
        "final_merits_analysis": eb.get("final_merits_analysis"),
        "comparable_evidence_guidance": (eb.get("comparable_evidence") or {}).get(
            "agent_instruction"
        ),
        "continue_work_evidence": (eb.get("continue_work_in_us") or {}).get(
            "possible_evidence"
        ),
        "global_evaluation_principles": meta.get("global_evaluation_principles"),
        "policy_sources": pick_sources(kb, ["Volume 6, Part F, Chapter 2"]),
    }

    write_json(
        EB1A_HOME / "01_Controlling_Sources" / "CFR"
        / "8_CFR_204-5(h)_EB1A_regulatory_criteria.json",
        cfr,
    )
    write_json(
        EB1A_HOME / "01_Controlling_Sources" / "USCIS_Policy_Manual"
        / "USCIS_PM_Vol6_PartF_Ch2_EB1A_adjudicative_guidance.json",
        pm,
    )
    write_readme(
        EB1A_HOME,
        title="EB-1A Knowledge Base",
        category="EB-1A (extraordinary ability, employment-based first preference)",
        cfr_line="`CFR/` — 8 CFR 204.5(h): definition, one-time achievement, the ten "
        "criteria with citations, comparable evidence, continue-work requirement.",
        pm_line="`USCIS_Policy_Manual/` — Volume 6, Part F, Chapter 2: two-step "
        "analysis, per-criterion evaluation focus, recommended evidence, common "
        "weaknesses, final merits factors.",
        source_json="EB1A_evaluation_knowledge_base.json",
        original_dir="EB1A_Knowledge_Base_original/",
        extra_notes=[
            "EB-1A has ten regulatory criteria at 8 CFR 204.5(h)(3)(i)-(x), three of "
            "which must be satisfied absent a one-time major achievement. Do not "
            "reuse the O-1A eight-criterion list here.",
        ],
    )


def build_eb2niw() -> None:
    kb = json.loads(NIW_SRC.read_text(encoding="utf-8"))
    meta = kb.get("knowledge_base_metadata", {})
    niw = kb.get("EB2_NIW", {})
    part1 = niw.get("part_1_underlying_EB2", {})
    advanced = part1.get("advanced_degree_path", {})
    exceptional = part1.get("exceptional_ability_path", {})
    prongs_block = niw.get("part_2_NIW_three_prongs", {})
    generated = date.today().isoformat()
    derived_from = (
        "knowledge_base/EB2NIW_Knowledge_Base/EB2_NIW_evaluation_knowledge_base.json"
    )

    cfr = {
        "source_metadata": {
            "title": (
                "INA 203(b)(2) and 8 CFR 204.5(k) — EB-2 and national interest "
                "waiver regulatory basis"
            ),
            "authority": REGULATION_AUTHORITY,
            "citations": [
                "INA 203(b)(2)(A), 8 USC 1153(b)(2)(A) (advanced degree or exceptional ability)",
                "INA 203(b)(2)(B)(i) (authority to waive the job offer and labor "
                "certification in the national interest)",
                "8 CFR 204.5(k)(2) (definitions of advanced degree and exceptional ability)",
                "8 CFR 204.5(k)(3)(i) (advanced degree initial evidence)",
                "8 CFR 204.5(k)(3)(ii)(A)-(F) (six exceptional ability criteria)",
                "8 CFR 204.5(k)(3)(iii) (comparable evidence)",
                "8 CFR 204.5(k)(4)(ii) (national interest waiver request)",
            ],
            "official_url": (
                "https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-204/"
                "subpart-A/section-204.5"
            ),
            "derived_from": derived_from,
            "content_note": CONTENT_NOTE_CFR,
            "generated_date": generated,
        },
        "classification_structure": niw.get("core_structure"),
        "self_petition_permitted": niw.get("self_petition"),
        "labor_certification_waiver": niw.get("labor_certification_waiver"),
        "national_interest_waiver_authority": {
            "citation": "INA 203(b)(2)(B)(i)",
            "note": (
                "The statute permits a waiver when it is deemed in the national "
                "interest but does not define the term; the operative test is the "
                "Matter of Dhanasar framework adopted in the USCIS Policy Manual. "
                "See the USCIS_Policy_Manual folder."
            ),
        },
        "underlying_eb2_paths": {
            "advanced_degree_path": {
                "path_id": advanced.get("path_id"),
                "citation": "8 CFR 204.5(k)(2), (k)(3)(i)",
                "legal_standard": advanced.get("legal_standard"),
                "qualifying_routes": advanced.get("qualifying_routes"),
            },
            "exceptional_ability_path": {
                "path_id": exceptional.get("path_id"),
                "citation": "8 CFR 204.5(k)(2), (k)(3)(ii)",
                "legal_standard": exceptional.get("legal_standard"),
                "minimum_regulatory_threshold": exceptional.get(
                    "minimum_regulatory_threshold"
                ),
                "criteria": [
                    {
                        "criterion_id": c.get("criterion_id"),
                        "number": c.get("number"),
                        "citation": (
                            f"8 CFR 204.5(k)(3)(ii)({LETTER.get(c.get('number'), '?')})"
                        ),
                        "name": c.get("name"),
                        "concept": c.get("concept"),
                    }
                    for c in exceptional.get("criteria", [])
                ],
                "comparable_evidence": exceptional.get("comparable_evidence"),
                "important_note": exceptional.get("important_note"),
            },
        },
        "regulatory_sources": pick_sources(kb, ["204.5(k)"]),
    }

    pm = {
        "source_metadata": {
            "title": (
                "USCIS Policy Manual, Volume 6, Part F, Chapter 5 — "
                "national interest waiver adjudicative guidance"
            ),
            "authority": POLICY_AUTHORITY,
            "citations": [
                "USCIS Policy Manual, Volume 6, Part F, Chapter 5 (national interest waivers)",
                "USCIS Policy Alert, Employment-Based National Interest Waivers "
                "(January 15, 2025)",
            ],
            "official_url": "https://www.uscis.gov/policy-manual/volume-6-part-f-chapter-5",
            "derived_from": derived_from,
            "content_note": CONTENT_NOTE_PM,
            "generated_date": generated,
        },
        "precedent_framework": {
            "name": prongs_block.get("framework_name", "Matter of Dhanasar"),
            "citation": "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016)",
            "authority": (
                "Binding AAO precedent decision, adopted in the USCIS Policy Manual. "
                "Unlike the non-precedent AAO decisions catalogued for O-1A, this "
                "decision binds USCIS adjudicators."
            ),
            "all_prongs_required": prongs_block.get("all_prongs_required"),
        },
        "three_prong_analysis": prongs_block.get("prongs"),
        "underlying_eb2_evaluation_guidance": {
            "advanced_degree_path": {
                "evaluation_questions": advanced.get("evaluation_questions"),
                "common_weaknesses": advanced.get("common_weaknesses"),
                "recommended_evidence_by_route": [
                    {
                        "route": r.get("route"),
                        "recommended_evidence": r.get("recommended_evidence"),
                    }
                    for r in advanced.get("qualifying_routes", [])
                ],
            },
            "exceptional_ability_path": {
                "criteria_evidence": [
                    {
                        "criterion_id": c.get("criterion_id"),
                        "number": c.get("number"),
                        "name": c.get("name"),
                        "evidence": c.get("evidence"),
                        "gap_flags": c.get("gap_flags"),
                    }
                    for c in exceptional.get("criteria", [])
                ],
                "important_note": exceptional.get("important_note"),
            },
        },
        "special_evaluation_topics": niw.get("niw_special_evaluation_topics"),
        "report_output_guidance": niw.get("report_output_guidance"),
        "global_evaluation_principles": meta.get("global_evaluation_principles"),
        "policy_sources": pick_sources(
            kb, ["Volume 6, Part F, Chapter 5", "NIW Policy Update"]
        ),
    }

    write_json(
        NIW_HOME / "01_Controlling_Sources" / "CFR"
        / "8_CFR_204-5(k)_INA_203(b)(2)_EB2_NIW_regulatory_basis.json",
        cfr,
    )
    write_json(
        NIW_HOME / "01_Controlling_Sources" / "USCIS_Policy_Manual"
        / "USCIS_PM_Vol6_PartF_Ch5_NIW_adjudicative_guidance.json",
        pm,
    )
    write_readme(
        NIW_HOME,
        title="EB-2 NIW Knowledge Base",
        category="EB-2 with a national interest waiver",
        cfr_line="`CFR/` — INA 203(b)(2) and 8 CFR 204.5(k): advanced degree and "
        "exceptional ability paths, the six exceptional ability criteria with "
        "citations, comparable evidence, waiver authority.",
        pm_line="`USCIS_Policy_Manual/` — Volume 6, Part F, Chapter 5: the "
        "Matter of Dhanasar three-prong analysis, evidence expectations, and "
        "special topics for entrepreneurs, STEM researchers, and physicians.",
        source_json="EB2_NIW_evaluation_knowledge_base.json",
        original_dir="EB2NIW_Knowledge_Base_original/",
        extra_notes=[
            "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016) is a *precedent* AAO "
            "decision and binds USCIS. Do not label it with the non-precedent, "
            "non-binding caveat used for the O-1A AAO decisions.",
            "Eligibility requires the underlying EB-2 classification first and then "
            "all three Dhanasar prongs; the prongs are not an alternative to EB-2.",
        ],
    )


def write_readme(
    home: Path,
    *,
    title: str,
    category: str,
    cfr_line: str,
    pm_line: str,
    source_json: str,
    original_dir: str,
    extra_notes: list[str],
) -> None:
    lines = [
        f"# {title}",
        "",
        f"Controlling sources for {category}, generated "
        f"{date.today().isoformat()} by `tools/build_controlling_sources.py`. "
        "The layout matches `O1A_Knowledge_Base/` so the same retrieval code works "
        "across categories.",
        "",
        "## Structure",
        "",
        "```",
        f"{home.name}/",
        f"├── {source_json}",
        "└── 01_Controlling_Sources/",
        "    ├── CFR/",
        "    └── USCIS_Policy_Manual/",
        "```",
        "",
        f"- {cfr_line}",
        f"- {pm_line}",
        "",
        "## Authority levels (keep these separate)",
        "",
        "| Location | Authority |",
        "| --- | --- |",
        f"| `01_Controlling_Sources/CFR/` | {REGULATION_AUTHORITY} |",
        f"| `01_Controlling_Sources/USCIS_Policy_Manual/` | {POLICY_AUTHORITY} |",
        "",
        "Both files are structured restatements of the source rules, not verbatim "
        "legal text; each records its `official_url`, so quote the eCFR or the "
        "Policy Manual directly when exact wording matters.",
        "",
        "## Notes",
        "",
    ]
    for note in extra_notes:
        lines.append(f"- {note}")
    lines += [
        f"- The untouched archive copy stays in `knowledge_base/{original_dir}` and is "
        "never modified.",
        f"- No AAO decision PDFs have been collected for this category, so there is no "
        "`00_Catalog/` or `02_AAO_Non_Precedent_Decisions/` yet; both would follow the "
        "O-1A pattern when decisions are added.",
        "",
        "## Regenerating",
        "",
        "```bash",
        "python tools/build_controlling_sources.py",
        "```",
        "",
        f"Runtime evaluation loads `{source_json}` itself; this folder is reference "
        "material and does not change agent behaviour by itself.",
        "",
    ]
    (home / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    build_eb1a()
    build_eb2niw()
    for home in (EB1A_HOME, NIW_HOME):
        created = sorted(
            p.relative_to(home).as_posix()
            for p in (home / "01_Controlling_Sources").rglob("*.json")
        )
        print(f"{home.name}:")
        for rel in created:
            print(f"  {rel}")


if __name__ == "__main__":
    main()
