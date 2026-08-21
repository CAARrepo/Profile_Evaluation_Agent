"""Parse extracted AAO decision text into draft catalog records.

Reads tools/_aao_text/*.txt (produced by tools/aao_extract.py) and writes a
draft catalog to tools/_aao_text/_draft_catalog.json plus a human-review
summary at tools/_aao_text/_review.txt.

Every criterion determination keeps the sentence it came from and the PDF page
number so a human can verify it against the original decision.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TEXT_DIR = Path(__file__).resolve().parent / "_aao_text"

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# OCR misreads of month abbreviations seen in these scans.
MONTH_OCR = {
    "WL": 7, "JUL Y": 7, "JAN.": 1, "SEPT": 9, "IUN": 6, "JVN": 6,
    "MAA": 3, "AVG": 8, "OCI": 10, "N0V": 11, "DEC.": 12,
}


def month_number(token: str) -> int | None:
    key = token.upper().strip().rstrip(".").replace(" ", "")
    if key in MONTH_OCR:
        return MONTH_OCR[key]
    if key[:3] in MONTHS:
        return MONTHS[key[:3]]
    return None

CRITERIA = {
    1: "Awards",
    2: "Membership",
    3: "Published material",
    4: "Judging",
    5: "Original contributions",
    6: "Scholarly articles",
    7: "Critical or essential capacity",
    8: "High salary",
}

CRITERION_PHRASES = {
    1: [r"awards? criteri", r"prizes? or awards?", r"recognized prizes"],
    2: [r"membership\w* criteri", r"membership in associations"],
    3: [r"published material"],
    4: [r"judging criteri", r"judge of the work", r"as a judge"],
    5: [r"original contributions?"],
    6: [r"scholarly articles?", r"authorship of scholarly"],
    7: [r"critical or essential", r"essential capacity", r"critical employment",
        r"leading or critical role"],
    8: [r"high salary", r"high remuneration", r"salary or other remuneration",
        r"salary criteri"],
}

ACCEPT_CUES = [
    r"\bwe agree with the director",
    r"\bagree with the director'?s?\s+(?:determination|finding|conclusion)",
    r"\bhas (?:therefore |thus )?(?:established|demonstrated|satisfied|met|shown)\b",
    r"\bsatisfies\b", r"\bsatisfied\b",
    r"\bmeets\b", r"\bfulfills\b", r"\bfulfilled\b",
    r"\bis (?:met|satisfied)\b",
    r"\bhave been (?:met|satisfied)\b",
    r"\bestablishes\b",
    r"\bdemonstrates (?:the beneficiary'?s? )?eligibility\b",
]

REJECT_CUES = [
    r"\bwe do not agree\b",
    r"\bdo(?:es)? not agree\b",
    r"\bhas not (?:established|demonstrated|satisfied|met|shown)\b",
    r"\bhave not (?:established|demonstrated|satisfied|met|shown)\b",
    r"\bdid not (?:establish|demonstrate|satisfy|meet|show)\b",
    r"\bdoes not (?:establish|demonstrate|satisfy|meet|support|show)\b",
    r"\bis not (?:met|satisfied|sufficient)\b",
    r"\bare not (?:met|satisfied|sufficient)\b",
    r"\bwas not (?:met|satisfied)\b",
    r"\binsufficient\b",
    r"\bfails? to (?:establish|demonstrate|satisfy|meet|show)\b",
    r"\bfailed to (?:establish|demonstrate|satisfy|meet|show)\b",
    r"\bwithdraw the director'?s?\s+(?:finding|determination|conclusion)",
    r"\bhas not overcome\b",
    r"\bnot persuasive\b",
    r"\bdoes not establish\b",
]

ABANDON_CUES = [
    r"\babandon(?:ed|s)?\b",
    r"\bwaived\b",
    r"\bdoes not (?:contest|dispute|challenge)\b",
    r"\bdid not (?:claim|assert)\b",
    r"\bno longer (?:claims|pursues)\b",
]

OUTCOME_PATTERNS = [
    (r"we (?:will )?dismiss the appeal", "Appeal dismissed"),
    (r"the appeal (?:is|will be) dismissed", "Appeal dismissed"),
    (r"orders?:\s*the appeal is dismissed", "Appeal dismissed"),
    (r"we (?:will )?sustain the appeal", "Appeal sustained"),
    (r"the appeal is sustained", "Appeal sustained"),
    (r"we (?:will )?withdraw the director'?s? decision and remand", "Remanded"),
    (r"remand(?:ed|ing)? (?:the matter|this matter)", "Remanded"),
    (r"the matter is remanded", "Remanded"),
    (r"we (?:will )?reject the appeal", "Appeal rejected"),
    (r"dismiss the (?:combined )?motions?", "Motion dismissed"),
    (r"the motions? (?:is|are) dismissed", "Motion dismissed"),
    (r"we (?:will )?deny the motion", "Motion denied"),
    (r"the motion is denied", "Motion denied"),
    (r"grant the motion", "Motion granted"),
    (r"we (?:will )?summarily dismiss", "Appeal summarily dismissed"),
    (r"the appeal is summarily dismissed", "Appeal summarily dismissed"),
]

# Beneficiary-occupation patterns are tried before petitioner-business patterns.
BENEFICIARY_OCC_PATTERNS = [
    r"classify the beneficiary,? an? ([^,.;]{3,90}?), as",
    r"classify the beneficiary,? an? ([^,.;]{3,90}?),",
    r"classify the beneficiary,? as an? ([^,.;]{3,90}?),",
    r"classify the beneficiary as an? ([^,.;]{3,90}?) (?:of|for) extraordinary",
    r"classify (?:him|her|the beneficiary) as an? ([^,.;]{3,90}?) (?:of|for) extraordinary",
    r"classify the beneficiary as an? ([^,.;]{3,90}?)[,.]",
    r"the beneficiary, an? ([^,.;]{3,90}?), as a (?:person|foreign national|individual)",
    r"the beneficiary, an? ([^,.;]{3,90}?),",
    r"beneficiary(?:'s)? (?:position|role|job|occupation) (?:as|of) an? ([^,.;]{3,90}?)[,.]",
    r"(?:employ|employs|employed|employing)(?:\s+\w+){0,2}\s+the beneficiary as an? ([^,.;]{3,90}?)[,.]",
    r"beneficiary(?:'s)? (?:employment|services) as an? ([^,.;]{3,90}?)[,.]",
    r"to work as an? ([^,.;]{3,90}?)[,.]",
    r"classify (?:himself|herself),? an? ([^,.;]{3,90}?), as",
    r"self-petition\w*[^.]{0,60}as an? ([^,.;]{3,90}?)[,.]",
    r"beneficiary(?:'s)? (?:field|occupation) (?:of endeavor )?(?:as|is) (?:that of )?an? ([^,.;]{3,90}?)[,.]",
]

# Phrases that describe immigration status rather than an occupation.
OCC_BLOCKLIST = re.compile(
    r"extraordinary|foreign national|nonimmigrant|non-?immigrant|"
    r"person of|individual of|alien of|beneficiary|petitioner|classification",
    re.IGNORECASE,
)

# Occupation keyword -> statutory field, used when a decision does not state one.
FIELD_KEYWORDS: list[tuple[str, str]] = [
    (r"coach|athlete|wrestler|boxer|gymnast|bodybuild|skydiv|parachut|"
     r"soccer|tennis|hockey|badminton|ski\b|sumo|mma|martial|"
     r"showjumping|equestrian|trainer|fitness|sport", "Athletics"),
    (r"research|scientist|physicist|physician|cardiolog|endocrinolog|"
     r"ophthalmolog|surgeon|biolog|chemist|engineer|scholar|"
     r"fellow|postdoc|animal science|medical|clinic", "Science"),
    (r"professor|lecturer|teacher|instructor|counselor|educator|"
     r"dean|principal|curricul|academic|tutor", "Education"),
    (r"executive|ceo|chief|president|manager|director|entrepreneur|"
     r"founder|business|financ|market|invest|bank|consult|sales|"
     r"software|developer|technician|technolog|analyst|"
     r"accountant|producer|mechanic", "Business"),
]

STATED_FIELD_TO_FOLDER = {
    "athletics": "Athletics",
    "science": "Science",
    "business": "Business",
    "education": "Education",
    "art": "Arts (out of O-1A scope)",
}


def infer_field(occupation: str | None, petitioner: str | None) -> str | None:
    for text in (occupation or "", petitioner or ""):
        low = text.lower()
        for pattern, field in FIELD_KEYWORDS:
            if re.search(pattern, low):
                return field
    return None

PETITIONER_OCC_PATTERNS = [
    r"the petitioner, an? ([^,.;]{3,90}?),",
]

FIELD_STATEMENT = re.compile(
    r"extraordinary ability in (?:the )?"
    r"(athletics|sciences|science|business|education|arts|art)\b(?!\s*,)",
    re.IGNORECASE,
)


def normalize_pages(raw: str) -> list[str]:
    return raw.split("\n\n===PAGE_BREAK===\n\n")


def flat(text: str) -> str:
    """Collapse hyphen line-breaks, whitespace, and OCR spacing artifacts."""
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;])", r"\1", text)  # "Beneficiary , a" -> "Beneficiary, a"
    text = re.sub(r"\(\s+", "(", text)  # "( o )(3)" -> "(o)(3)"
    text = re.sub(r"\s+\)", ")", text)
    return text


def parse_date(text: str) -> str | None:
    # Modern header: "Date : AUG . 12, 2021" (OCR inserts stray spaces).
    m = re.search(
        r"date\s*:?\s*([A-Za-z]{2,9})\s*\.?\s*(\d{1,2})\s*,\s*((?:19|20)\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        mon = month_number(m.group(1))
        if mon:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    # Legacy header: "Date: JUN 1 3 2005" (day digits split by OCR).
    m = re.search(
        r"date\s*:?\s*([A-Za-z]{2,9})\s*\.?\s*((?:\d\s*){1,3})\s*((?:19|20)\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        mon = month_number(m.group(1))
        day = re.sub(r"\D", "", m.group(2))
        if mon and day and 1 <= int(day) <= 31:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(day):02d}"
    return None


def parse_decision_number(text: str) -> tuple[str | None, str]:
    """Return (decision_number, id_format)."""
    m = re.search(r"in\s*re\s*:?\s*([0-9OoIl\s]{5,20})", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        raw = (
            raw.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
        )
        digits = re.sub(r"\D", "", raw)
        if digits:
            return digits, "AAO In Re number"
    # Legacy decisions identify the case by receipt number, e.g. "WAC 03 209 54393".
    m = re.search(
        r"file\s*:?\s*([A-Z]{3})\s*((?:\d\s*){8,14})", text, re.IGNORECASE
    )
    if m:
        digits = re.sub(r"\D", "", m.group(2))
        return f"{m.group(1).upper()}-{digits}", "legacy receipt number"
    return None, "unknown"


def _clean_occ(occ: str) -> str | None:
    occ = re.sub(r"\s+", " ", occ).strip(" ,.;:")
    occ = re.sub(r"^(?:the|an|a)\s+", "", occ, flags=re.IGNORECASE)
    occ = occ.strip(" ,.;:|I")
    if not (3 <= len(occ) <= 90):
        return None
    if OCC_BLOCKLIST.search(occ):
        return None
    if not re.search(r"[a-z]{3}", occ):
        return None
    return occ


def parse_occupation(text: str) -> tuple[str | None, str | None]:
    """Return (beneficiary_occupation, petitioner_description)."""
    low = text.lower()
    beneficiary = None
    for pat in BENEFICIARY_OCC_PATTERNS:
        m = re.search(pat, low)
        if m:
            beneficiary = _clean_occ(m.group(1))
            if beneficiary:
                break
    petitioner = None
    for pat in PETITIONER_OCC_PATTERNS:
        m = re.search(pat, low)
        if m:
            petitioner = _clean_occ(m.group(1))
            if petitioner:
                break
    return beneficiary, petitioner


def parse_stated_field(text: str) -> str | None:
    counts: dict[str, int] = {}
    for m in FIELD_STATEMENT.finditer(text):
        key = m.group(1).lower()
        key = {"sciences": "science", "arts": "art"}.get(key, key)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def ocr_digit(token: str) -> int | None:
    token = token.strip().lower()
    mapping = {"]": "1", "l": "1", "i": "1", "|": "1", "j": "1", "!": "1", "[": "1"}
    token = "".join(mapping.get(ch, ch) for ch in token)
    token = re.sub(r"\D", "", token)
    if token and token.isdigit() and 1 <= int(token) <= 8:
        return int(token)
    return None


def cited_criteria(text: str) -> set[int]:
    found: set[int] = set()
    for m in re.finditer(r"\(B\)\s*((?:\(\s*[^)]{1,4}\s*\)|\s*(?:and|,|or)\s*)+)", text):
        for token in re.finditer(r"\(\s*([^)]{1,4}?)\s*\)", m.group(1)):
            n = ocr_digit(token.group(1))
            if n:
                found.add(n)
    return found


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


LEADING_CONCESSIVE = re.compile(
    r"^\s*(?:while|although|though|whereas|even though)\b", re.IGNORECASE
)


def clauses(sentence: str) -> list[str]:
    """Split compound sentences so opposite findings are not cross-attributed."""
    parts = re.split(
        r",?\s+(?:but|while|whereas|however|although|though)\s+|;\s*",
        sentence,
        flags=re.IGNORECASE,
    )
    out: list[str] = []
    for part in parts:
        low = part.lower()
        conflicting = any(re.search(p, low) for p in ACCEPT_CUES) and any(
            re.search(p, low) for p in REJECT_CUES
        )
        # "we agree ... under the awards criterion, we do not agree ..." ->
        # split so the accepted and rejected criteria are not conflated.
        if conflicting or LEADING_CONCESSIVE.match(part):
            out.extend(
                re.split(
                    r",\s+(?=we\b|it\b|the (?:petitioner|record|evidence|director)\b)",
                    part,
                    flags=re.IGNORECASE,
                )
            )
        else:
            out.append(part)
    return [p.strip() for p in out if p.strip()]


def verdict_for(clause: str) -> str | None:
    low = clause.lower()
    if any(re.search(p, low) for p in ABANDON_CUES):
        return "not_pursued"
    reject = any(re.search(p, low) for p in REJECT_CUES)
    accept = any(re.search(p, low) for p in ACCEPT_CUES)
    if reject:
        return "rejected"
    if accept:
        return "accepted"
    return None


def criteria_in(clause: str) -> set[int]:
    nums = cited_criteria(clause)
    low = clause.lower()
    for n, pats in CRITERION_PHRASES.items():
        if any(re.search(p, low) for p in pats):
            nums.add(n)
    return nums


THIS_CRITERION = re.compile(
    r"\bthis criterion\b|\bthe criterion\b|\bthis regulatory criterion\b", re.IGNORECASE
)

# Explicit holdings carry more weight than passing references.
HOLDING_CUES = re.compile(
    r"\b(?:met|satisfied|fulfilled)\s+this criterion\b|"
    r"\bthis criterion (?:is|has been|was) (?:not )?(?:met|satisfied)\b|"
    r"\bwe agree with the director|"
    r"\bwe do not agree with the director|"
    r"\bwithdraw the director'?s?\b|"
    r"\bhas not met this criterion\b",
    re.IGNORECASE,
)


AAO_SUBJECT = re.compile(
    r"\bwe\s+(?:agree|do not agree|disagree|conclude|find|determine|withdraw|"
    r"are not persuaded|acknowledge|note)\b|\bupon de novo review\b",
    re.IGNORECASE,
)
DIRECTOR_SUBJECT = re.compile(
    r"\bthe director\s+(?:determined|found|concluded|denied|acknowledged|stated|"
    r"noted|held|did not)\b|\bdirector'?s? (?:determination|finding|conclusion|decision)\b",
    re.IGNORECASE,
)
PETITIONER_SUBJECT = re.compile(
    r"\bthe petitioner\s+(?:asserts|claims|argues|contends|maintains|submits|"
    r"avers|states|alleges|indicates|posits|responds)\b|"
    r"\bon appeal, the petitioner\b|\bcounsel (?:asserts|argues|claims)\b",
    re.IGNORECASE,
)


def speaker_of(clause: str) -> str:
    """Whose position a clause reports: the AAO, the Director, or the petitioner."""
    if AAO_SUBJECT.search(clause):
        return "aao"
    if DIRECTOR_SUBJECT.search(clause):
        return "director"
    if PETITIONER_SUBJECT.search(clause):
        return "petitioner"
    return "aao"


def collect(pages: list[str]) -> dict[int, list[dict[str, object]]]:
    """Walk the decision in order, tracking which criterion is under discussion.

    AAO decisions analyze one criterion per section and often conclude with
    "he has not met this criterion", so the criterion in scope must be carried
    forward to attribute such holdings correctly.
    """
    hits: dict[int, list[dict[str, object]]] = {n: [] for n in CRITERIA}
    current: int | None = None
    for page_no, page in enumerate(pages, start=1):
        for sent in sentences(flat(page)):
            sent_nums = criteria_in(sent)
            if len(sent_nums) == 1:
                current = next(iter(sent_nums))
            for clause in clauses(sent):
                nums = criteria_in(clause)
                verdict = verdict_for(clause)
                if not nums:
                    # "Therefore, he has not met this criterion." -> current section
                    if verdict and current and THIS_CRITERION.search(clause):
                        nums = {current}
                    else:
                        continue
                speaker = speaker_of(clause)
                weight = 3 if HOLDING_CUES.search(clause) else 1
                if speaker != "aao":
                    weight = 0  # recorded for context, not counted as a holding
                for n in nums:
                    hits[n].append(
                        {
                            "page": page_no,
                            "verdict": verdict,
                            "weight": weight,
                            "attributed_to": speaker,
                            "passage": clause[:400],
                        }
                    )
    return hits


def parse_outcome(text_flat: str) -> str | None:
    low = text_flat.lower()
    best: tuple[int, str] | None = None
    for pat, label in OUTCOME_PATTERNS:
        for m in re.finditer(pat, low):
            if best is None or m.start() > best[0]:
                best = (m.start(), label)
    return best[1] if best else None


def main() -> None:
    records = []
    review_lines = []
    for txt in sorted(TEXT_DIR.glob("*.txt")):
        if txt.name.startswith("_"):
            continue
        raw = txt.read_text(encoding="utf-8")
        pages = normalize_pages(raw)
        whole = flat(raw)
        head = flat("\n".join(pages[:1]))

        date = parse_date(whole)
        number, id_format = parse_decision_number(whole)
        beneficiary_occ, petitioner_desc = parse_occupation(head)
        if not beneficiary_occ:
            beneficiary_occ, _ = parse_occupation(whole)
        stated_field = parse_stated_field(whole)
        if stated_field:
            field = STATED_FIELD_TO_FOLDER.get(stated_field, stated_field.title())
            field_basis = "stated in decision"
        else:
            field = infer_field(beneficiary_occ, petitioner_desc)
            field_basis = "inferred from occupation" if field else "unresolved"
        outcome = parse_outcome(whole)
        hits = collect(pages)

        discussed: list[str] = []
        accepted: list[str] = []
        rejected: list[str] = []
        not_pursued: list[str] = []
        evidence: dict[str, list[dict[str, object]]] = {}

        unclear: list[str] = []
        for n, items in hits.items():
            if not items:
                continue
            scored = [i for i in items if i["verdict"] and int(i["weight"]) > 0]
            if len(items) < 2 and not scored:
                continue
            name = CRITERIA[n]
            discussed.append(name)
            weights: dict[str, int] = {}
            for i in scored:
                key = str(i["verdict"])
                weights[key] = weights.get(key, 0) + int(i["weight"])
            acc = weights.get("accepted", 0)
            rej = weights.get("rejected", 0)
            aban = weights.get("not_pursued", 0)
            if aban and aban > acc and aban > rej:
                not_pursued.append(name)
            elif acc or rej:
                strong, weak = max(acc, rej), min(acc, rej)
                if weak and strong < 2 * weak:
                    unclear.append(name)  # conflicting signals; do not guess
                elif acc > rej:
                    accepted.append(name)
                else:
                    rejected.append(name)
            else:
                unclear.append(name)
            # Keep the strongest passages, holdings first, with page numbers.
            ranked = sorted(items, key=lambda i: (-int(i["weight"]), i["page"]))
            evidence[name] = [i for i in ranked if i["verdict"]][:5] or ranked[:2]

        records.append(
            {
                "original_filename": txt.stem + ".pdf",
                "date": date,
                "decision_number": number,
                "decision_number_format": id_format,
                "beneficiary_occupation": beneficiary_occ,
                "petitioner_description": petitioner_desc,
                "stated_field": stated_field,
                "field": field,
                "field_basis": field_basis,
                "outcome": outcome,
                "page_count": len(pages),
                "criteria_discussed": discussed,
                "criteria_accepted": accepted,
                "criteria_rejected": rejected,
                "criteria_not_pursued": not_pursued,
                "criteria_unclear": unclear,
                "criterion_evidence": evidence,
            }
        )
        review_lines.append(
            f"{txt.stem}\n"
            f"  date={date} num={number} field={field} ({field_basis}) "
            f"outcome={outcome} pages={len(pages)}\n"
            f"  beneficiary={beneficiary_occ}\n"
            f"  petitioner={petitioner_desc}\n"
            f"  discussed={discussed}\n"
            f"  accepted={accepted}\n  rejected={rejected}\n"
            f"  not_pursued={not_pursued}\n  unclear={unclear}\n"
        )

    (TEXT_DIR / "_draft_catalog.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (TEXT_DIR / "_review.txt").write_text("\n".join(review_lines), encoding="utf-8")
    missing = [
        r["original_filename"]
        for r in records
        if not (r["date"] and r["decision_number"])
    ]
    no_field = [r["original_filename"] for r in records if not r["field"]]
    no_occ = [r["original_filename"] for r in records if not r["beneficiary_occupation"]]
    no_outcome = [r["original_filename"] for r in records if not r["outcome"]]
    print(f"parsed {len(records)} records")
    print(f"missing date/number ({len(missing)}): {missing}")
    print(f"missing field ({len(no_field)}): {no_field}")
    print(f"missing occupation ({len(no_occ)}): {no_occ}")
    print(f"missing outcome ({len(no_outcome)}): {no_outcome}")


if __name__ == "__main__":
    main()
