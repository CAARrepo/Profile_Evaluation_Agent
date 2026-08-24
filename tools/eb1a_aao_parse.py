"""Parse extracted EB-1A AAO text into one JSON record per decision.

Reads tools/_eb1a_aao_text/*.txt (from tools/eb1a_aao_extract.py).
Writes tools/_eb1a_aao_text/cases/*.json plus a draft catalog and review file.
Does not write into EB1A_Knowledge_Base_original.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation_agent.eb1a_aao_ingest import parse_decision_text  # noqa: E402

TEXT_DIR = Path(__file__).resolve().parent / "_eb1a_aao_text"
CASES_DIR = TEXT_DIR / "cases"


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    review: list[str] = []
    for txt in sorted(TEXT_DIR.glob("*.txt")):
        if txt.name.startswith("_"):
            continue
        filename = txt.stem + ".pdf"
        rec = parse_decision_text(
            txt.read_text(encoding="utf-8"),
            filename=filename,
        )
        out = CASES_DIR / (txt.stem + ".json")
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        records.append(rec)
        review.append(
            f"{filename}\n"
            f"  id={rec.get('case_id')} date={rec.get('decision_date')} "
            f"outcome={rec.get('outcome')} field={rec.get('field')} "
            f"occ={rec.get('occupation')}\n"
            f"  claimed={rec.get('criteria_claimed')}\n"
            f"  accepted={rec.get('criteria_accepted')}\n"
            f"  rejected={rec.get('criteria_rejected')}\n"
        )

    (TEXT_DIR / "_draft_catalog.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (TEXT_DIR / "_review.txt").write_text("\n".join(review), encoding="utf-8")
    missing_date = [r["source"]["filename"] for r in records if not r.get("decision_date")]
    missing_occ = [r["source"]["filename"] for r in records if not r.get("occupation")]
    print(f"parsed {len(records)} records -> {CASES_DIR}")
    print(f"missing date ({len(missing_date)}): {missing_date[:12]}")
    print(f"missing occupation ({len(missing_occ)}): {missing_occ[:12]}")


if __name__ == "__main__":
    main()
