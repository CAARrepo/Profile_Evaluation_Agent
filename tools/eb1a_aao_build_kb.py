"""Build EB-1A AAO catalog, criterion intelligence, and retrieval indexes.

Reads parsed case JSON from tools/_eb1a_aao_text/cases/ and copies PDFs from
knowledge_base/EB1A_Knowledge_Base_original/ (read-only). Writes only into
knowledge_base/EB1A_Knowledge_Base/.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation_agent.eb1a_aao_ingest import (  # noqa: E402
    CRITERIA,
    EVIDENCE_EXPLICITLY_ACCEPTED,
    EVIDENCE_EXPLICITLY_REJECTED,
    KEY_TO_ID,
    KEY_TO_NAME,
    PUBLISHED_MATERIAL_ELEMENTS,
)
from evaluation_agent.eb1a_taxonomy import primary_field_folder  # noqa: E402

SRC_PDFS = (
    ROOT
    / "knowledge_base"
    / "EB1A_Knowledge_Base_original"
    / "EB-1A AAO Non-Precedent Decisions"
)
TEXT_CASES = ROOT / "tools" / "_eb1a_aao_text" / "cases"
OUT = ROOT / "knowledge_base" / "EB1A_Knowledge_Base"
CATALOG_DIR = OUT / "00_Catalog"
CASES_DIR = CATALOG_DIR / "cases"
INTEL_DIR = CATALOG_DIR / "criterion_intelligence"
AAO_DIR = OUT / "02_AAO_Non_Precedent_Decisions"
AUTHORITY = "AAO non-precedent—non-binding"
STOP = {
    "the", "and", "of", "in", "for", "a", "an", "or", "to", "at", "with",
    "on", "as", "by", "from", "this", "that", "petitioner", "beneficiary",
    "criterion", "evidence", "record", "director",
}
_BOILERPLATE = re.compile(
    r"at least three of the|ten categor|ten criteria|plain language requirements of three",
    re.IGNORECASE,
)
_CRITERION_NAME_NEEDLES = (
    "awards", "membership", "published material", "judging",
    "original contribution", "scholarly", "leading or critical", "high salary",
    "artistic", "commercial success",
)

FIELD_FOLDERS = ["Sciences", "Business", "Arts", "Education", "Athletics", "_Review_Needed"]


def _slug(text: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", text or "") if w]
    words = words[:4] or ["Occupation"]
    return "-".join(w.capitalize() if w.islower() else w for w in words)


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    return re.sub(r"\s+", " ", name).strip()


def _is_boilerplate(text: str) -> bool:
    low = (text or "").lower()
    if _BOILERPLATE.search(low):
        return True
    return sum(1 for n in _CRITERION_NAME_NEEDLES if n in low) >= 3


def _tokens(text: str) -> list[str]:
    return [
        t for t in re.findall(r"[a-z]{3,}", (text or "").lower())
        if t not in STOP
    ]


def _doc_text(rec: dict[str, Any]) -> str:
    parts = [
        " ".join(rec.get("occupation") or []),
        " ".join(rec.get("specialty") or []),
        " ".join(rec.get("industry") or []),
        " ".join(rec.get("field") or []),
        " ".join(rec.get("criteria_claimed") or []),
        " ".join(rec.get("lessons") or []),
        " ".join(rec.get("occupation_search_tags") or []),
    ]
    return " ".join(parts)


def _year(rec: dict[str, Any]) -> int:
    raw = str(rec.get("decision_date") or "")[:4]
    return int(raw) if raw.isdigit() else 0


def load_cases() -> list[dict[str, Any]]:
    files = sorted(TEXT_CASES.glob("*.json"))
    if not files:
        raise FileNotFoundError(
            f"No parsed cases in {TEXT_CASES}. Run tools/eb1a_aao_extract.py "
            "then tools/eb1a_aao_parse.py first."
        )
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def build_tfidf(records: list[dict[str, Any]]) -> dict[str, Any]:
    docs: list[list[str]] = [_tokens(_doc_text(r)) for r in records]
    df: Counter[str] = Counter()
    for toks in docs:
        df.update(set(toks))
    n = max(len(docs), 1)
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vectors: list[dict[str, Any]] = []
    for rec, toks in zip(records, docs):
        tf = Counter(toks)
        length = sum(tf.values()) or 1
        weights = {
            t: (cnt / length) * idf.get(t, 1.0) for t, cnt in tf.items()
        }
        vectors.append(
            {
                "case_id": rec.get("case_id"),
                "filename": (rec.get("source") or {}).get("filename"),
                "weights": weights,
            }
        )
    return {
        "generated_date": date.today().isoformat(),
        "method": "tfidf_cosine_over_occupation_specialty_field_tags",
        "idf": idf,
        "vectors": vectors,
    }


def _cite(rec: dict[str, Any], page: int | None = None) -> dict[str, Any]:
    src = rec.get("source") or {}
    return {
        "case_id": rec.get("case_id") or "",
        "decision_date": rec.get("decision_date") or "",
        "filename": src.get("filename") or "",
        "pdf_page": page,
        "outcome": rec.get("outcome") or "",
        "authority": AUTHORITY,
    }


def build_intelligence(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for n, meta in CRITERIA.items():
        key = meta["key"]
        accepted_patterns: list[str] = []
        rejected_patterns: list[str] = []
        denial_reasons: list[str] = []
        field_obs: dict[str, Counter[str]] = defaultdict(Counter)
        occ_obs: dict[str, Counter[str]] = defaultdict(Counter)
        supporting: list[dict[str, Any]] = []
        claimed = 0
        accepted_n = 0
        rejected_n = 0
        recent_rejected = 0
        for rec in records:
            analysis = (rec.get("criterion_analysis") or {}).get(key) or {}
            if not analysis:
                continue
            claimed += 1
            det = analysis.get("determination")
            if det == "accepted":
                accepted_n += 1
            elif det == "rejected":
                rejected_n += 1
                if _year(rec) >= 2025:
                    recent_rejected += 1
            for item in analysis.get("accepted_evidence") or []:
                text = item.get("text") or ""
                if _is_boilerplate(text):
                    continue
                accepted_patterns.append(text)
                supporting.append(
                    {
                        **_cite(rec, item.get("pdf_page")),
                        "evidence_status": item.get("evidence_status"),
                        "determination": det,
                    }
                )
            for item in analysis.get("rejected_evidence") or []:
                text = item.get("text") or ""
                if _is_boilerplate(text):
                    continue
                rejected_patterns.append(text)
                denial_reasons.append(text)
                supporting.append(
                    {
                        **_cite(rec, item.get("pdf_page")),
                        "evidence_status": item.get("evidence_status"),
                        "determination": det,
                    }
                )
            label = det or "discussed"
            for field in rec.get("field") or []:
                field_obs[field][label] += 1
            for occ in rec.get("occupation") or []:
                occ_obs[occ][label] += 1

        def _top(items: list[str], n: int = 8) -> list[str]:
            cleaned = [re.sub(r"\s+", " ", x).strip() for x in items if x]
            cleaned = [x for x in cleaned if len(x) > 40]
            return cleaned[:n]

        field_specific = [
            {
                "field": field,
                "accepted": counts.get("accepted", 0),
                "rejected": counts.get("rejected", 0),
                "discussed": counts.get("discussed", 0) + counts.get("not_reached", 0),
                "note": (
                    f"Observed AAO pattern in {field}: "
                    f"{counts.get('accepted', 0)} accepted / "
                    f"{counts.get('rejected', 0)} rejected holdings "
                    "(non-precedent; not a legal rule)."
                ),
            }
            for field, counts in sorted(field_obs.items())
            if sum(counts.values()) >= 2
        ]
        occ_specific = [
            {
                "occupation": occ,
                "accepted": counts.get("accepted", 0),
                "rejected": counts.get("rejected", 0),
                "note": (
                    f"Observed AAO pattern for {occ}: "
                    f"{counts.get('accepted', 0)} accepted / "
                    f"{counts.get('rejected', 0)} rejected holdings "
                    "(non-precedent; not a legal rule)."
                ),
            }
            for occ, counts in sorted(
                occ_obs.items(), key=lambda kv: -sum(kv[1].values())
            )[:12]
            if sum(counts.values()) >= 2
        ]
        payload: dict[str, Any] = {
            "criterion": key,
            "criterion_id": KEY_TO_ID[key],
            "criterion_name": KEY_TO_NAME[key],
            "authority": AUTHORITY,
            "legal_requirement_source": "8 CFR 204.5(h)(3) / USCIS Policy Manual — not AAO",
            "required_elements": [],
            "accepted_evidence_patterns": _top(accepted_patterns),
            "rejected_evidence_patterns": _top(rejected_patterns),
            "common_denial_reasons": _top(denial_reasons),
            "field_specific_observations": field_specific,
            "occupation_specific_observations": occ_specific,
            "supporting_cases": supporting[:40],
            "counts": {
                "cases_discussing": claimed,
                "accepted_holdings": accepted_n,
                "rejected_holdings": rejected_n,
                "recent_2025_plus_rejected": recent_rejected,
            },
            "observed_summary": (
                f"Observed in {claimed} AAO non-precedent decisions discussing this "
                f"criterion ({accepted_n} accepted holdings, {rejected_n} rejected). "
                "These counts are patterns only and do not amend the regulation."
            ),
        }
        if key == "published_material":
            payload["professional_publication_elements"] = PUBLISHED_MATERIAL_ELEMENTS[:]
            payload["major_media_elements"] = [
                "Major-media status",
                "Website traffic/readership",
                "Comparative traffic/readership",
                "Intended audience",
                "Publication significance",
            ]
        by_key[key] = payload
    return by_key


def write_readme(catalog: list[dict[str, Any]], counts: dict[str, int]) -> None:
    lines = [
        "# EB-1A Knowledge Base",
        "",
        f"Generated {date.today().isoformat()} by `tools/eb1a_aao_build_kb.py`.",
        "",
        "The original AAO PDFs stay untouched in "
        "`knowledge_base/EB1A_Knowledge_Base_original/`. This folder holds the "
        "runtime copies and structured indexes the evaluation agent reads.",
        "",
        "## Structure",
        "",
        "```",
        "EB1A_Knowledge_Base/",
        "├── 00_Catalog/",
        "│   ├── cases/                      one structured JSON per decision",
        "│   ├── criterion_intelligence/     aggregated AAO patterns per criterion",
        "│   ├── aao_decisions_catalog.json",
        "│   ├── aao_decisions_index.csv",
        "│   ├── criterion_index.json",
        "│   ├── metadata_index.json",
        "│   └── tfidf_index.json",
        "├── 01_Controlling_Sources/         CFR + USCIS Policy Manual (legal test)",
        "└── 02_AAO_Non_Precedent_Decisions/ copied PDFs by primary field",
        "```",
        "",
        "## Authority hierarchy (keep these separate)",
        "",
        "1. Statute / CFR — binding",
        "2. USCIS Policy Manual — binds USCIS officers",
        "3. Binding precedent or controlling authority",
        "4. AAO nonprecedent decisions — illustrative only",
        "5. Patterns derived from multiple AAO decisions — not legal rules",
        "",
        f"Catalogued decisions: {len(catalog)}.",
        "",
        "## Counts by primary field folder",
        "",
    ]
    for name, count in sorted(counts.items()):
        lines.append(f"- {name}: {count}")
    lines += [
        "",
        "## Regenerating",
        "",
        "```bash",
        "python tools/eb1a_aao_extract.py",
        "python tools/eb1a_aao_parse.py",
        "python tools/eb1a_aao_build_kb.py",
        "```",
        "",
        "Never modify `EB1A_Knowledge_Base_original/`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    records = load_cases()
    for path in [CATALOG_DIR, CASES_DIR, INTEL_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    for name in FIELD_FOLDERS:
        (AAO_DIR / name).mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    catalog: list[dict[str, Any]] = []

    for rec in sorted(records, key=lambda r: (r.get("decision_date") or "", r["source"]["filename"])):
        original = rec["source"]["filename"]
        src_pdf = SRC_PDFS / original
        if not src_pdf.is_file():
            raise FileNotFoundError(src_pdf)

        occ = (rec.get("occupation") or ["Occupation not stated"])[0]
        slug = _slug(occ)
        number = rec.get("case_id") or "Unknown"
        new_name = _safe(f"{rec.get('decision_date') or '0000-00-00'}_{slug}_{number}.pdf")
        if new_name in used_names:
            stem = new_name[:-4]
            suffix = 2
            while f"{stem}-{suffix}.pdf" in used_names:
                suffix += 1
            new_name = f"{stem}-{suffix}.pdf"
        used_names.add(new_name)

        folder = rec.get("field_folder") or primary_field_folder(rec.get("field") or [])
        dest = AAO_DIR / folder / new_name
        shutil.copy2(src_pdf, dest)

        rec = dict(rec)
        rec["filename"] = new_name
        rec["original_filename"] = original
        rec["relative_path"] = f"02_AAO_Non_Precedent_Decisions/{folder}/{new_name}"
        rec["original_copy_path"] = (
            "knowledge_base/EB1A_Knowledge_Base_original/"
            f"EB-1A AAO Non-Precedent Decisions/{original}"
        )
        rec["source"] = {
            **(rec.get("source") or {}),
            "filename": new_name,
            "original_filename": original,
            "relative_path": rec["relative_path"],
        }
        rec["field_folder"] = folder
        rec["occupation_label"] = occ
        rec["criteria_discussed"] = rec.get("criteria_claimed") or []
        rec["date"] = rec.get("decision_date") or ""
        rec["page_count"] = (rec.get("source") or {}).get("page_count")
        rec["search_tags"] = rec.get("occupation_search_tags") or []
        rec["authority"] = AUTHORITY

        case_path = CASES_DIR / f"{_safe(str(number))}.json"
        if case_path.exists():
            case_path = CASES_DIR / f"{_safe(str(number))}_{_safe(slug)}.json"
        case_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        rec["case_json"] = str(case_path.relative_to(OUT)).replace("\\", "/")
        catalog.append(rec)

    intelligence = build_intelligence(catalog)
    cfr_path = (
        OUT / "01_Controlling_Sources" / "CFR" / "8_CFR_204-5(h)_EB1A_regulatory_criteria.json"
    )
    if cfr_path.is_file():
        cfr = json.loads(cfr_path.read_text(encoding="utf-8"))
        by_id = {
            str(c.get("criterion_id")): c.get("required_elements") or []
            for c in (cfr.get("evidentiary_criteria") or [])
        }
        for payload in intelligence.values():
            payload["required_elements"] = list(by_id.get(payload["criterion_id"]) or [])
    for key, payload in intelligence.items():
        (INTEL_DIR / f"{key}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    tfidf = build_tfidf(catalog)
    (CATALOG_DIR / "tfidf_index.json").write_text(
        json.dumps(tfidf, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    metadata = [
        {
            "case_id": r.get("case_id"),
            "decision_date": r.get("decision_date"),
            "outcome": r.get("outcome"),
            "field": r.get("field"),
            "industry": r.get("industry"),
            "occupation": r.get("occupation"),
            "specialty": r.get("specialty"),
            "criteria_claimed": r.get("criteria_claimed"),
            "criteria_accepted": r.get("criteria_accepted"),
            "criteria_rejected": r.get("criteria_rejected"),
            "filename": r.get("filename"),
            "original_filename": r.get("original_filename"),
            "relative_path": r.get("relative_path"),
            "page_numbers": (r.get("source") or {}).get("pages") or [],
            "case_json": r.get("case_json"),
            "occupation_search_tags": r.get("occupation_search_tags"),
        }
        for r in catalog
    ]
    (CATALOG_DIR / "metadata_index.json").write_text(
        json.dumps(
            {
                "generated_date": date.today().isoformat(),
                "record_count": len(metadata),
                "authority": AUTHORITY,
                "records": metadata,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    catalog_lite = []
    for r in catalog:
        catalog_lite.append(
            {
                "decision_number": r.get("case_id"),
                "date": r.get("decision_date"),
                "occupation": r.get("occupation_label"),
                "occupation_tags": r.get("occupation"),
                "field": (r.get("field") or [None])[0],
                "field_folder": r.get("field_folder"),
                "industry": r.get("industry"),
                "specialty": r.get("specialty"),
                "criteria_discussed": r.get("criteria_claimed") or [],
                "criteria_accepted": r.get("criteria_accepted") or [],
                "criteria_rejected": r.get("criteria_rejected") or [],
                "outcome": {
                    "sustained": "Appeal sustained",
                    "dismissed": "Appeal dismissed",
                }.get(str(r.get("outcome")), str(r.get("outcome") or "")),
                "outcome_normalized": r.get("outcome"),
                "authority": AUTHORITY,
                "precedential_value": r.get("precedential_value"),
                "filename": r.get("filename"),
                "original_filename": r.get("original_filename"),
                "relative_path": r.get("relative_path"),
                "original_copy_path": r.get("original_copy_path"),
                "page_count": r.get("page_count"),
                "search_tags": r.get("search_tags"),
                "case_json": r.get("case_json"),
                "criterion_analysis": r.get("criterion_analysis"),
                "final_merits": r.get("final_merits"),
            }
        )

    (CATALOG_DIR / "aao_decisions_catalog.json").write_text(
        json.dumps(
            {
                "catalog_metadata": {
                    "title": "EB-1A AAO non-precedent decision catalog",
                    "generated_date": date.today().isoformat(),
                    "record_count": len(catalog_lite),
                    "authority_of_all_records": AUTHORITY,
                    "source_hierarchy": [
                        "Statute / CFR",
                        "USCIS Policy Manual",
                        "Binding precedent or controlling authority",
                        "AAO nonprecedent decisions",
                        "Patterns derived from multiple AAO decisions",
                    ],
                    "retrieval_rules": [
                        "Filter by visa type, field, industry, occupation, specialty, criterion, date, outcome.",
                        "Prefer 2026, then 2025, then older.",
                        "Retrieve both sustained and dismissed cases; do not let denials dominate.",
                        "Never send all PDFs to the LLM; use metadata + TF-IDF over structured records.",
                        "Label every AAO document as non-precedent and non-binding.",
                        "Do not treat EXPLICITLY unstated evidence in a sustained case as approved.",
                    ],
                },
                "decisions": catalog_lite,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    csv_path = CATALOG_DIR / "aao_decisions_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "date", "case_id", "field", "occupation", "outcome",
                "criteria_claimed", "criteria_accepted", "criteria_rejected",
                "pages", "filename", "original_filename",
            ]
        )
        for rec in catalog:
            writer.writerow(
                [
                    rec.get("decision_date"), rec.get("case_id"),
                    rec.get("field_folder"), rec.get("occupation_label"),
                    rec.get("outcome"),
                    "; ".join(rec.get("criteria_claimed") or []),
                    "; ".join(rec.get("criteria_accepted") or []),
                    "; ".join(rec.get("criteria_rejected") or []),
                    rec.get("page_count"), rec.get("filename"),
                    rec.get("original_filename"),
                ]
            )

    def group(key: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rec in catalog_lite:
            values = rec.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                out.setdefault(str(value), []).append(rec["filename"])
        return {k: sorted(v) for k, v in sorted(out.items())}

    (CATALOG_DIR / "criterion_index.json").write_text(
        json.dumps(
            {
                "note": (
                    "Filenames may appear under several criteria. "
                    "AAO non-precedent — non-binding."
                ),
                "by_criterion_discussed": group("criteria_discussed"),
                "by_criterion_accepted": group("criteria_accepted"),
                "by_criterion_rejected": group("criteria_rejected"),
                "by_field": group("field_folder"),
                "by_outcome": group("outcome_normalized"),
                "by_industry": group("industry"),
                "by_specialty": group("specialty"),
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
    print(f"catalogued {len(catalog)} EB-1A decisions -> {OUT}")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
