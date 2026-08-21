"""Extract raw text from the O-1A AAO non-precedent decision PDFs.

Writes one .txt per PDF into tools/_aao_text/ so header fields (date, decision
number, occupation, criteria, outcome) can be parsed and reviewed.
"""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
SRC = (
    ROOT
    / "knowledge_base"
    / "O1A_Knowledge_Base_original"
    / "O-1A AAO Non-Precedent Decisions"
)
OUT = Path(__file__).resolve().parent / "_aao_text"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []
    for pdf in sorted(SRC.glob("*.pdf")):
        reader = PdfReader(str(pdf))
        pages = [(p.extract_text() or "") for p in reader.pages]
        text = "\n\n===PAGE_BREAK===\n\n".join(pages)
        txt_path = OUT / (pdf.stem + ".txt")
        txt_path.write_text(text, encoding="utf-8")
        index.append(
            {
                "original_filename": pdf.name,
                "text_file": txt_path.name,
                "page_count": len(pages),
                "chars": len(text),
            }
        )
    (OUT / "_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"extracted {len(index)} pdfs -> {OUT}")


if __name__ == "__main__":
    main()
