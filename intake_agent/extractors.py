"""Extract plain text from uploaded PDF / DOCX resumes and evidence."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path


def extract_pdf_bytes(data: bytes) -> str:
    """Extract text from raw PDF bytes (downloaded URL or in-memory file)."""
    from pypdf import PdfReader

    if not data or not data.lstrip().startswith(b"%PDF"):
        return ""
    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n".join(parts).strip()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in {".docx", ".doc"}:
        return _extract_docx(path)
    if suffix == ".pptx":
        return _extract_pptx(path)
    if suffix in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    # Some resumes are stored as `.docx.pdf` style names; try PDF first.
    if ".pdf" in path.name.lower():
        try:
            return _extract_pdf(path)
        except Exception:
            pass
    raise ValueError(f"Unsupported document type: {path.name}")


def _extract_pdf(path: Path) -> str:
    return extract_pdf_bytes(path.read_bytes())


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    # Also pull simple table text
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def _extract_pptx(path: Path) -> str:
    """Read slide text from a .pptx without extra dependencies (OOXML zip)."""
    import zipfile
    from xml.etree import ElementTree as ET

    ns_t = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    parts: list[str] = []
    with zipfile.ZipFile(path) as zf:
        slides = sorted(
            name
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        for name in slides:
            root = ET.fromstring(zf.read(name))
            texts = [node.text.strip() for node in root.iter(ns_t) if node.text and node.text.strip()]
            if texts:
                parts.append(" ".join(texts))
    return "\n".join(parts).strip()
