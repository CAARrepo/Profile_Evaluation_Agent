"""Build knowledge_base/O1A_Knowledge_Base/ from the existing O-1A material.

Inputs (the *_original folder is a read-only archive)
  knowledge_base/O1A_Knowledge_Base_original/O1A_evaluation_knowledge_base.json
  knowledge_base/O1A_Knowledge_Base_original/O-1A AAO Non-Precedent Decisions/*.pdf
  tools/_aao_text/_draft_catalog.json                       (automated extraction)
  tools/aao_overrides.json                                  (human-verified fixes)

Outputs
  knowledge_base/O1A_Knowledge_Base/
    01_Controlling_Sources/CFR/                  regulatory criteria + citations
    01_Controlling_Sources/USCIS_Policy_Manual/  adjudicative guidance
    02_AAO_Non_Precedent_Decisions/<Field>/      renamed copies of every PDF
    00_Catalog/                                  catalog, indexes, README

Originals are never moved or modified: the PDFs are copied and the original
filename is preserved in the catalog.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge_base"
SRC_O1A = KB_DIR / "O1A_Knowledge_Base_original"
SRC_PDFS = SRC_O1A / "O-1A AAO Non-Precedent Decisions"
SRC_KB_JSON = SRC_O1A / "O1A_evaluation_knowledge_base.json"

TEXT_DIR = Path(__file__).resolve().parent / "_aao_text"
DRAFT = TEXT_DIR / "_draft_catalog.json"
OVERRIDES = Path(__file__).resolve().parent / "aao_overrides.json"

OUT = KB_DIR / "O1A_Knowledge_Base"
CATALOG_DIR = OUT / "00_Catalog"
CFR_DIR = OUT / "01_Controlling_Sources" / "CFR"
PM_DIR = OUT / "01_Controlling_Sources" / "USCIS_Policy_Manual"
AAO_DIR = OUT / "02_AAO_Non_Precedent_Decisions"

FIELD_FOLDERS = ["Athletics", "Science", "Business", "Education"]
REVIEW_FOLDER = "_Review_Needed"

AUTHORITY_LABEL = "AAO non-precedent—non-binding"

STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "for", "in", "at", "on", "period",
    "three", "years", "redacted", "decision", "sport", "discipline",
    "not", "stated", "master", "test",
}

# Cross-cutting issues worth tagging beyond the eight criteria.
ISSUE_PATTERNS: list[tuple[str, str]] = [
    (r"\bconsultation\b|\badvisory opinion\b|\bpeer group\b", "Consultation requirement"),
    (r"\bagent\b.{0,60}(?:file|petition|eligib)|\bU\.?S\.? agent\b", "U.S. agent petitioning eligibility"),
    (r"\brevoke\b|\brevocation\b|\bgross error\b", "Revocation / gross error"),
    (r"\btotality of the record\b|\bfinal merits\b", "Totality-of-the-record determination"),
    (r"\bmisrepresentation\b|\bfraud\b|\bnot credible\b", "Fraud or misrepresentation"),
    (r"\bcomparable evidence\b", "Comparable evidence"),
    (r"\bmotion to reopen\b|\bmotion to reconsider\b", "Motion to reopen or reconsider"),
    (r"\bextend\b.{0,40}\bclassification\b|\bextension of stay\b", "Extension of O-1 status"),
    (r"\bitinerary\b|\bwork schedule\b", "Itinerary requirement"),
    (r"\bsame (?:or a closely related )?area of extraordinary ability\b|\barea of expertise\b",
     "Work in the area of extraordinary ability"),
    (r"\babandon(?:ed|s)?\b|\bwaived\b", "Criteria abandoned or waived on appeal"),
]


def slugify_occupation(text: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    text = re.sub(r"\(.*?\)", " ", text)
    words = [w for w in re.split(r"[^A-Za-z0-9]+", text) if w]
    words = [w for w in words if w.lower() not in STOPWORDS]
    words = words[:4] or ["Unspecified-Occupation"]
    return "-".join(w.capitalize() if w.islower() else w for w in words)


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    return re.sub(r"\s+", " ", name).strip()


def detect_issues(text: str) -> list[str]:
    found: list[str] = []
    for pattern, label in ISSUE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in found:
            found.append(label)
    return found


def build_criterion_findings(record: dict[str, Any]) -> dict[str, Any]:
    determinations: dict[str, str] = {}
    for name in record.get("criteria_accepted", []):
        determinations[name] = "accepted"
    for name in record.get("criteria_rejected", []):
        determinations[name] = "rejected"
    for name in record.get("criteria_not_pursued", []):
        determinations[name] = "not_pursued_or_abandoned"
    for name in record.get("criteria_unclear", []):
        determinations.setdefault(name, "discussed_determination_unclear")

    findings: dict[str, Any] = {}
    for name, passages in (record.get("criterion_evidence") or {}).items():
        findings[name] = {
            "determination": determinations.get(name, "discussed_determination_unclear"),
            "supporting_passages": [
                {
                    "pdf_page": p["page"],
                    "attributed_to": p.get("attributed_to", "aao"),
                    "quote": p["passage"],
                }
                for p in passages
            ],
        }
    return findings


def load_records() -> list[dict[str, Any]]:
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    out = []
    for rec in draft:
        merged = dict(rec)
        override = overrides.get(rec["original_filename"], {})
        merged.update({k: v for k, v in override.items() if not k.startswith("_")})
        out.append(merged)
    return out


def field_folder(field: str | None) -> str:
    if field in FIELD_FOLDERS:
        return field
    return REVIEW_FOLDER


def make_tree() -> None:
    for path in [CATALOG_DIR, CFR_DIR, PM_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    for name in FIELD_FOLDERS + [REVIEW_FOLDER]:
        (AAO_DIR / name).mkdir(parents=True, exist_ok=True)


def split_controlling_sources(kb: dict[str, Any]) -> None:
    """Separate the structured O-1A rules into regulation vs. policy guidance."""
    meta = kb.get("knowledge_base_metadata", {})
    o1a = kb.get("O1A", {})
    criteria = o1a.get("criteria", [])
    generated = date.today().isoformat()

    cfr_payload = {
        "source_metadata": {
            "title": "8 CFR 214.2(o) — O-1 regulatory framework for O-1A criteria",
            "authority": "Federal regulation — binding",
            "citations": [
                "8 CFR 214.2(o)(3)(ii) (definition of extraordinary ability)",
                "8 CFR 214.2(o)(3)(iii)(A) (major internationally recognized award)",
                "8 CFR 214.2(o)(3)(iii)(B)(1)-(8) (eight evidentiary criteria)",
                "8 CFR 214.2(o)(2) (petition and U.S. agent requirements)",
                "8 CFR 214.2(o)(5) (consultation requirement)",
            ],
            "official_url": "https://www.ecfr.gov/current/title-8/section-214.2",
            "derived_from": (
                "knowledge_base/O1A_Knowledge_Base_original/"
                "O1A_evaluation_knowledge_base.json"
            ),
            "content_note": (
                "Structured restatement of the regulatory elements, not verbatim "
                "regulatory text. Quote the eCFR directly when exact wording matters."
            ),
            "generated_date": generated,
        },
        "definition_of_extraordinary_ability": o1a.get("core_legal_standard"),
        "statutory_field_scope": o1a.get("statutory_field_scope"),
        "threshold_structure": o1a.get("threshold_structure"),
        "major_award_path": {
            "criterion_id": (o1a.get("major_international_award_path") or {}).get(
                "criterion_id"
            ),
            "name": (o1a.get("major_international_award_path") or {}).get("name"),
            "legal_concept": (o1a.get("major_international_award_path") or {}).get(
                "legal_concept"
            ),
        },
        "evidentiary_criteria": [
            {
                "criterion_id": c.get("criterion_id"),
                "number": c.get("number"),
                "citation": f"8 CFR 214.2(o)(3)(iii)(B)({c.get('number')})",
                "name": c.get("name"),
                "regulatory_concept": c.get("regulatory_concept"),
                "required_elements": c.get("required_elements"),
            }
            for c in criteria
        ],
        "regulatory_sources": [
            s for s in meta.get("primary_sources", []) if s.get("type") == "regulation"
        ],
    }

    pm_payload = {
        "source_metadata": {
            "title": (
                "USCIS Policy Manual, Volume 2, Part M — O-1A adjudicative guidance"
            ),
            "authority": (
                "USCIS policy guidance — binding on USCIS officers, not a regulation"
            ),
            "citations": [
                "USCIS Policy Manual, Volume 2, Part M, Chapter 4 (O-1 beneficiaries)",
                "USCIS Policy Manual, Volume 2, Part M, Appendices (evidence examples)",
            ],
            "official_url": "https://www.uscis.gov/policy-manual/volume-2-part-m-chapter-4",
            "derived_from": (
                "knowledge_base/O1A_Knowledge_Base_original/"
                "O1A_evaluation_knowledge_base.json"
            ),
            "content_note": (
                "Structured restatement of adjudicative guidance and evidence "
                "expectations, not verbatim Policy Manual text."
            ),
            "generated_date": generated,
        },
        "evaluation_method": o1a.get("evaluation_method"),
        "final_merits_factors": o1a.get("final_merits_factors"),
        "evidence_guidance_by_criterion": [
            {
                "criterion_id": c.get("criterion_id"),
                "number": c.get("number"),
                "name": c.get("name"),
                "evaluation_questions": c.get("evaluation_questions"),
                "strong_examples": c.get("strong_examples"),
                "weak_or_risky_examples": c.get("weak_or_risky_examples"),
                "recommended_evidence": c.get("recommended_evidence"),
                "common_information_gaps": c.get("common_information_gaps"),
            }
            for c in criteria
        ],
        "major_award_guidance": {
            k: v
            for k, v in (o1a.get("major_international_award_path") or {}).items()
            if k
            in {
                "evaluation_questions",
                "strong_indicators",
                "weak_indicators",
                "recommended_evidence",
            }
        },
        "global_evaluation_principles": meta.get("global_evaluation_principles"),
        "policy_sources": [
            s
            for s in meta.get("primary_sources", [])
            if s.get("type") in {"USCIS policy", "USCIS policy alert"}
        ],
    }

    (CFR_DIR / "8_CFR_214-2(o)_O1A_regulatory_criteria.json").write_text(
        json.dumps(cfr_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (PM_DIR / "USCIS_PM_Vol2_PartM_O1A_adjudicative_guidance.json").write_text(
        json.dumps(pm_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_readme(catalog: list[dict[str, Any]], counts: dict[str, int]) -> None:
    review = [r for r in catalog if r["field_folder"] == REVIEW_FOLDER]
    lines = [
        "# O-1A Knowledge Base",
        "",
        f"Generated {date.today().isoformat()} by `tools/aao_build_kb.py`. "
        f"Contains {len(catalog)} AAO non-precedent decisions plus structured "
        "controlling-source extracts.",
        "",
        "## Structure",
        "",
        "```",
        "O1A_Knowledge_Base/",
        "├── 00_Catalog/",
        "│   ├── aao_decisions_catalog.json   one metadata record per PDF",
        "│   ├── aao_decisions_index.csv      flat index for quick scanning",
        "│   └── criterion_index.json         criterion / field / outcome / issue lookups",
        "├── 01_Controlling_Sources/",
        "│   ├── CFR/                         8 CFR 214.2(o) regulatory elements",
        "│   └── USCIS_Policy_Manual/         adjudicative guidance and evidence expectations",
        "└── 02_AAO_Non_Precedent_Decisions/",
        "    ├── Athletics/",
        "    ├── Science/",
        "    ├── Business/",
        "    ├── Education/",
        "    └── _Review_Needed/              no field of endeavor decided, or non-O-1A",
        "```",
        "",
        "## Counts by field",
        "",
    ]
    for name, count in sorted(counts.items()):
        lines.append(f"- {name}: {count}")
    lines += [
        "",
        "## Authority levels (keep these separate)",
        "",
        "| Location | Authority |",
        "| --- | --- |",
        "| `01_Controlling_Sources/CFR/` | Federal regulation — binding |",
        "| `01_Controlling_Sources/USCIS_Policy_Manual/` | USCIS policy guidance — binds USCIS officers, not a regulation |",
        f"| `02_AAO_Non_Precedent_Decisions/` | {AUTHORITY_LABEL} |",
        "",
        "Every AAO decision must be labelled non-precedent and non-binding wherever it is "
        "quoted or summarised. Never present an AAO holding as controlling law.",
        "",
        "## File naming",
        "",
        "`YYYY-MM-DD_Occupation_DecisionNumber.pdf`, for example "
        "`2023-11-16_Automotive-Technician_28840908.pdf`.",
        "",
        "The decision date and number come from the decision header (`Date:` and `In Re:`). "
        "One legacy 2005 decision has no `In Re` number, so its receipt number is used "
        "(`WAC-0320954393`).",
        "",
        "## Originals",
        "",
        "The untouched originals stay in "
        "`knowledge_base/O1A_Knowledge_Base_original/O-1A AAO Non-Precedent Decisions/` "
        "under their original names. Files here are renamed copies, and every catalog "
        "record carries both `original_filename` and `original_copy_path`.",
        "",
        "## Catalog record fields",
        "",
        "`decision_number`, `date`, `occupation`, `field`, `field_basis`, "
        "`petitioner_description`, `criteria_discussed`, `criteria_accepted`, "
        "`criteria_rejected`, `criteria_not_pursued`, `criteria_determination_unclear`, "
        "`criterion_findings` (determination plus quoted passages with `pdf_page`), "
        "`other_issues`, `outcome`, `authority`, `precedential_value`, `filename`, "
        "`original_filename`, `page_count`, `search_tags`, `extraction`.",
        "",
        "## How to search",
        "",
        "Filter the catalog on metadata instead of copying a PDF into a folder per "
        "criterion, because one decision usually addresses several criteria. Examples:",
        "",
        "- Soccer coach + awards + critical role: `field_folder == \"Athletics\"`, "
        "occupation contains `soccer`, `\"Awards\"` and "
        "`\"Critical or essential capacity\"` in `criteria_discussed`.",
        "- Researcher + original contributions + rejected: occupation contains "
        "`research`, `\"Original contributions\"` in `criteria_rejected`.",
        "- Use `criterion_index.json` for the reverse lookup from a criterion, field, "
        "outcome, or issue to filenames.",
        "",
        "## Retrieval rules for the agent",
        "",
        "1. Store the PDF page number with every retrieved passage; "
        "`criterion_findings[*].supporting_passages[*].pdf_page` already does this.",
        "2. Cite CFR or the Policy Manual for the legal standard; cite AAO decisions only "
        "as illustrations of how evidence was weighed.",
        "3. Note whether a passage reflects the AAO's own holding, the Director's finding, "
        "or the petitioner's assertion (`attributed_to`).",
        "4. Treat `criterion_findings` as machine-extracted "
        "(`extraction.criterion_findings_verified: false`) and confirm against the cited "
        "page before relying on it.",
        "",
        "## Items needing human review",
        "",
    ]
    for rec in review:
        lines.append(
            f"- `{rec['filename']}` — {rec['occupation']}: "
            f"{rec.get('field_basis') or 'no field determined'}"
        )
    lines += [
        "",
        "## Regenerating",
        "",
        "```bash",
        "python tools/aao_extract.py     # PDFs -> text",
        "python tools/aao_parse.py       # text -> draft catalog + review report",
        "python tools/aao_build_kb.py    # draft + tools/aao_overrides.json -> this tree",
        "```",
        "",
        "Runtime evaluation loads "
        "`knowledge_base/O1A_Knowledge_Base/O1A_evaluation_knowledge_base.json`. The "
        "controlling sources and this AAO catalog are reachable through "
        "`evaluation_agent.kb_loader` but are not injected into evaluation prompts.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    make_tree()
    kb = json.loads(SRC_KB_JSON.read_text(encoding="utf-8"))
    split_controlling_sources(kb)

    records = load_records()
    catalog: list[dict[str, Any]] = []
    used_names: set[str] = set()

    for rec in sorted(records, key=lambda r: (r.get("date") or "", r["original_filename"])):
        original = rec["original_filename"]
        src_pdf = SRC_PDFS / original
        if not src_pdf.is_file():
            raise FileNotFoundError(src_pdf)

        occupation = rec.get("occupation") or rec.get("beneficiary_occupation") or "Occupation not stated"
        slug = slugify_occupation(occupation, rec.get("occupation_slug"))
        number = rec.get("decision_number") or "Unknown"
        new_name = safe_filename(f"{rec.get('date') or '0000-00-00'}_{slug}_{number}.pdf")
        if new_name in used_names:
            stem = new_name[:-4]
            suffix = 2
            while f"{stem}-{suffix}.pdf" in used_names:
                suffix += 1
            new_name = f"{stem}-{suffix}.pdf"
        used_names.add(new_name)

        folder = field_folder(rec.get("field"))
        dest = AAO_DIR / folder / new_name
        shutil.copy2(src_pdf, dest)

        text_path = TEXT_DIR / (Path(original).stem + ".txt")
        text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""

        findings = build_criterion_findings(rec)
        # Tags cover the job title and the petitioner's business, so a query like
        # "soccer" also finds a program director employed by a soccer club.
        tag_text = f"{occupation} {rec.get('petitioner_description') or ''}"
        tags = sorted(
            {
                *(
                    w.lower()
                    for w in re.split(r"[^A-Za-z0-9]+", tag_text)
                    if len(w) > 2 and w.lower() not in STOPWORDS
                ),
                *(c.lower() for c in rec.get("criteria_discussed", [])),
                *(i.lower() for i in detect_issues(text)),
                (rec.get("field") or "").lower(),
                (rec.get("outcome") or "").lower(),
            }
            - {""}
        )

        catalog.append(
            {
                "decision_number": number,
                "decision_number_format": rec.get("decision_number_format"),
                "date": rec.get("date"),
                "occupation": occupation,
                "field": rec.get("field") if folder != REVIEW_FOLDER else rec.get("field"),
                "field_folder": folder,
                "field_basis": rec.get("field_basis"),
                "petitioner_description": rec.get("petitioner_description"),
                "criteria_discussed": rec.get("criteria_discussed", []),
                "criteria_accepted": rec.get("criteria_accepted", []),
                "criteria_rejected": rec.get("criteria_rejected", []),
                "criteria_not_pursued": rec.get("criteria_not_pursued", []),
                "criteria_determination_unclear": rec.get("criteria_unclear", []),
                "criterion_findings": findings,
                "other_issues": detect_issues(text),
                "outcome": rec.get("outcome"),
                "authority": AUTHORITY_LABEL,
                "precedential_value": (
                    "Non-precedent AAO decision. Persuasive/illustrative only; it does "
                    "not bind USCIS, the AAO, or any court."
                ),
                "filename": new_name,
                "original_filename": original,
                "relative_path": f"02_AAO_Non_Precedent_Decisions/{folder}/{new_name}",
                "original_copy_path": (
                    "knowledge_base/O1A_Knowledge_Base_original/"
                    f"O-1A AAO Non-Precedent Decisions/{original}"
                ),
                "page_count": rec.get("page_count"),
                "search_tags": tags,
                "notes": rec.get("notes"),
                "extraction": {
                    "method": "pypdf text extraction + rule-based analysis (tools/aao_parse.py)",
                    "human_verified_fields": sorted(
                        k
                        for k in ("occupation", "field", "field_basis", "notes")
                        if k in (rec.keys() & {"occupation", "field", "field_basis", "notes"})
                    ),
                    "criterion_findings_verified": False,
                    "caution": (
                        "Criterion determinations are machine-extracted. Confirm against "
                        "the cited PDF page before relying on them."
                    ),
                },
            }
        )

    (CATALOG_DIR / "aao_decisions_catalog.json").write_text(
        json.dumps(
            {
                "catalog_metadata": {
                    "title": "O-1A AAO non-precedent decision catalog",
                    "generated_date": date.today().isoformat(),
                    "record_count": len(catalog),
                    "authority_of_all_records": AUTHORITY_LABEL,
                    "filename_convention": "YYYY-MM-DD_Occupation_DecisionNumber.pdf",
                    "retrieval_rules": [
                        "Store the PDF page number with every retrieved passage.",
                        "Label every AAO document as non-precedent and non-binding in output.",
                        "Keep AAO material separate from CFR and USCIS Policy Manual sources.",
                        "Filter by criterion, occupation, field, date, outcome, or issue tags "
                        "instead of duplicating PDFs per criterion.",
                    ],
                },
                "decisions": catalog,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Flat CSV index for quick scanning and spreadsheet review.
    csv_path = CATALOG_DIR / "aao_decisions_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "date", "decision_number", "field", "occupation", "outcome",
                "criteria_discussed", "criteria_accepted", "criteria_rejected",
                "pages", "filename", "original_filename",
            ]
        )
        for rec in catalog:
            writer.writerow(
                [
                    rec["date"], rec["decision_number"], rec["field_folder"],
                    rec["occupation"], rec["outcome"],
                    "; ".join(rec["criteria_discussed"]),
                    "; ".join(rec["criteria_accepted"]),
                    "; ".join(rec["criteria_rejected"]),
                    rec["page_count"], rec["filename"], rec["original_filename"],
                ]
            )

    # Criterion-, field-, outcome-, and issue-keyed indexes for tag search.
    def group(key: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rec in catalog:
            values = rec.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                out.setdefault(value, []).append(rec["filename"])
        return {k: sorted(v) for k, v in sorted(out.items())}

    (CATALOG_DIR / "criterion_index.json").write_text(
        json.dumps(
            {
                "note": (
                    "Filenames may appear under several criteria; one decision often "
                    "addresses multiple criteria. Do not duplicate the PDFs."
                ),
                "by_criterion_discussed": group("criteria_discussed"),
                "by_criterion_accepted": group("criteria_accepted"),
                "by_criterion_rejected": group("criteria_rejected"),
                "by_field": group("field_folder"),
                "by_outcome": group("outcome"),
                "by_issue": group("other_issues"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for rec in catalog:
        counts[rec["field_folder"]] = counts.get(rec["field_folder"], 0) + 1
    write_readme(catalog, counts)
    print(f"catalogued {len(catalog)} decisions -> {OUT}")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
