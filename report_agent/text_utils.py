"""Text helpers for client-facing reports (encoding + sentence-safe shortening)."""

from __future__ import annotations

import re

# Common mojibake from UTF-8 bytes misread as Windows-1252 / Latin-1
_MOJIBAKE_MAP = (
    ("â€”", "—"),
    ("â€“", "–"),
    ("â€™", "’"),
    ("â€˜", "‘"),
    ("â€œ", "“"),
    ("â€", "”"),
    ("â€¢", "•"),
    ("â€¦", "…"),
    ("Â", ""),
)


def fix_mojibake(text: str) -> str:
    if not text:
        return ""
    out = str(text)
    for bad, good in _MOJIBAKE_MAP:
        out = out.replace(bad, good)
    return out.strip()


def complete_sentences(text: str, max_sentences: int = 3) -> str:
    """
    Return up to max_sentences complete sentences.
    Never cuts mid-word or mid-sentence. Empty if no complete sentence exists
    and the text has no sentence terminator — then returns the full cleaned text
    only when it already reads as a complete short phrase without trailing cut.
    """
    cleaned = fix_mojibake(text)
    if not cleaned:
        return ""

    # Prefer client_summary-style already-short text
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences: list[str] = []
    for part in parts:
        s = part.strip()
        if not s:
            continue
        sentences.append(s)
        if len(sentences) >= max_sentences:
            break

    if not sentences:
        return cleaned

    selected = sentences[:max_sentences]
    # Drop a trailing incomplete fragment (no terminal punctuation).
    while selected and selected[-1][-1] not in ".!?":
        if len(selected) == 1:
            # Only incomplete text available — return full cleaned text rather than cutting.
            return cleaned
        selected = selected[:-1]
    return " ".join(selected) if selected else cleaned


def client_criterion_explanation(criterion: dict) -> str:
    """Prefer client_summary; else complete reasoning_summary (no char truncation)."""
    client = fix_mojibake(str(criterion.get("client_summary") or "").strip())
    if client:
        return complete_sentences(client, max_sentences=3)
    reasoning = fix_mojibake(str(criterion.get("reasoning_summary") or "").strip())
    if reasoning:
        return complete_sentences(reasoning, max_sentences=2)
    return ""


def consolidate_evidence(items: list[str], limit: int = 12) -> list[str]:
    """Deduplicate evidence requests (case-insensitive) and cap at sentence/bullet boundaries."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        text = fix_mojibake(str(raw or "").strip())
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower()).rstrip(".")
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


_UUID_FILE_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-",
    re.I,
)
_SOURCE_FACT = re.compile(
    r"^Source\s+(?P<source>[\w /|-]+)\s*\((?P<ref>[^)]+)\)\s*:\s*(?P<body>.*)$",
    re.I | re.S,
)
_APPLICANT_FACT = re.compile(
    r"^Applicant (?:states|is unsure but states)\s*\((?P<key>[^)]+)\)\s*:\s*(?P<body>.*)$",
    re.I | re.S,
)


def human_document_name(reference: str) -> str:
    """Turn a stored PDF path into a short client-facing label."""
    name = str(reference or "").replace("\\", "/").split("/")[-1].strip()
    name = _UUID_FILE_PREFIX.sub("", name)
    name = re.sub(r"\.(pdf|docx?|png|jpe?g|txt)$", "", name, flags=re.I)
    name = name.replace("_", " ").replace("-", " ")
    return " ".join(name.split())


def _one_client_line(text: str, max_chars: int = 180) -> str:
    cleaned = " ".join(fix_mojibake(text or "").replace("…", "...").split())
    if "..." in cleaned:
        cleaned = cleaned.split("...")[0].strip()
    if not cleaned:
        return ""
    line = complete_sentences(cleaned, max_sentences=1) or cleaned
    if len(line) <= max_chars:
        return line
    cut = line[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    return cut


def client_existing_document_line(text: str) -> str:
    """PDF table cells need short labels, not dumped PDF body text."""
    cleaned = " ".join(fix_mojibake(text or "").split())
    if not cleaned:
        return ""
    source_match = _SOURCE_FACT.match(cleaned)
    if source_match:
        source = (source_match.group("source") or "").strip().lower()
        ref = (source_match.group("ref") or "").strip()
        if source == "document" or ref.lower().endswith((".pdf", ".docx", ".doc")):
            return human_document_name(ref)
        return _one_client_line(source_match.group("body") or "")
    applicant_match = _APPLICANT_FACT.match(cleaned)
    if applicant_match:
        body = applicant_match.group("body") or ""
        stripped = body.replace("…", "...").split("...")[0].strip()
        two = complete_sentences(stripped, max_sentences=2) if stripped else ""
        if two and len(two) <= 280:
            return two
        return _one_client_line(body)
    return _one_client_line(cleaned)


def consolidate_existing_documents(items: list[str], limit: int = 6) -> list[str]:
    labeled = [client_existing_document_line(item) for item in items]
    return consolidate_evidence([item for item in labeled if item], limit=limit)


STATUS_CLIENT_LABELS = {
    "strong": "Strong evidence currently indicated",
    "potential": "Potentially supportable — more evidence needed",
    "weak": "Currently difficult to support",
    "not_indicated": "Not enough relevant information provided",
    "not_applicable": "Does not appear applicable",
}


def client_status_label(status: str) -> str:
    return STATUS_CLIENT_LABELS.get(str(status or "").strip().lower(), str(status or ""))


def explain_overall_rating(
    *,
    visa_category: str,
    overall_rating: str,
    criteria_summary: dict,
) -> list[str]:
    """Accurate narrative for overall rating; never bare 'Promising' alone."""
    strong = int(criteria_summary.get("strong") or 0)
    potential = int(criteria_summary.get("potential") or 0)
    weak = int(criteria_summary.get("weak") or 0)
    not_indicated = int(criteria_summary.get("not_indicated") or 0)
    category = visa_category or "this category"

    if visa_category == "O-1A":
        shown = strong + potential
        if shown <= 0:
            shown = 6
        word = "criterion was" if shown == 1 else "criteria were"
        return [
            fix_mojibake(
                "This preliminary O-1A profile assessment is summarized as “Promising” "
                "based solely on the information provided to date. "
                f"{_number_word(shown).capitalize()} potential {word} identified for "
                "possible evidence development."
            )
        ]

    paragraphs: list[str] = []
    rating = (overall_rating or "").strip()
    rating_words = {
        "very_strong": "very strong",
        "strong": "strong",
        "promising": "promising",
        "developing": "developing",
        "insufficient_information": "insufficient information",
    }
    label = rating_words.get(rating, rating.replace("_", " ") or "preliminary")

    paragraphs.append(
        f"This preliminary {category} profile assessment is summarized as “{label.title()}” "
        f"based solely on the information provided to date. It is not a determination of eligibility "
        f"and is not an attorney opinion."
    )

    if strong == 0 and potential > 0:
        word = "criterion was" if potential == 1 else "criteria were"
        paragraphs.append(
            f"{_number_word(potential).capitalize()} {word} identified for possible evidence development. "
            f"None is currently assessed as strongly supported."
        )
        paragraphs.append(
            f"A “potential” classification does not mean that the {category} criterion has been satisfied."
        )
    elif strong > 0 and potential > 0:
        paragraphs.append(
            f"The snapshot currently shows {strong} criterion(ia) with strong evidence indicated and "
            f"{potential} with potentially supportable facts that still need stronger documentation."
        )
        paragraphs.append(
            f"A “potential” classification does not mean that the {category} criterion has been satisfied."
        )
    elif strong > 0:
        paragraphs.append(
            f"The snapshot currently shows {strong} criterion(ia) with strong evidence indicated on the stated facts."
        )
    else:
        paragraphs.append(
            "Based on the current record, few or no criteria show clear strong or potentially supportable facts yet."
        )

    if weak or not_indicated:
        paragraphs.append(
            f"Additional notes from the assessment snapshot: weak={weak}, not indicated={not_indicated}."
        )

    return [fix_mojibake(p) for p in paragraphs]


def _number_word(n: int) -> str:
    words = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
    }
    return words.get(n, str(n))
