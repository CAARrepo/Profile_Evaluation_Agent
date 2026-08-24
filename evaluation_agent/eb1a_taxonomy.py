"""EB-1A occupation / field / industry / specialty tags.

Used both when ingesting AAO decisions and when classifying an applicant
profile. Tags are multi-label: a case is not forced into one folder.
"""

from __future__ import annotations

import re
from typing import Any

# Display names used in catalogs and reports.
FIELD_SCIENCES = "Sciences"
FIELD_BUSINESS = "Business"
FIELD_ARTS = "Arts"
FIELD_EDUCATION = "Education"
FIELD_ATHLETICS = "Athletics"

# Canonical occupation families. Related titles share the same family so
# "Software Developer" and "Senior Software Engineer" retrieve together.
OCCUPATION_FAMILIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "software_engineer": (
        "Software Engineer",
        (
            "software engineer", "software developer", "software architect",
            "senior software engineer", "staff software engineer",
            "principal software engineer", "app developer", "application developer",
            "ios developer", "android developer", "full stack", "fullstack",
            "backend engineer", "frontend engineer", "programmer", "coder",
            "swe ", " sde", "dev ops", "devops",
        ),
    ),
    "data_scientist": (
        "Data Scientist",
        (
            "data scientist", "machine learning engineer", "ml engineer",
            "ai engineer", "applied scientist", "research scientist",
            "nlp engineer", "computer vision",
        ),
    ),
    "researcher": (
        "Researcher",
        (
            "researcher", "research fellow", "research scientist",
            "postdoctoral", "postdoc", "principal investigator",
            "associate researcher", "assistant research",
        ),
    ),
    "startup_founder": (
        "Startup Founder",
        (
            "founder", "co-founder", "cofounder", "entrepreneur",
            "startup", "chief executive", " ceo",
        ),
    ),
    "product_manager": (
        "Product Manager",
        ("product manager", "product lead", "group product", "director of product"),
    ),
    "executive": (
        "Business Executive",
        (
            "chief ", "vice president", "svp", "evp", "managing director",
            "general manager", "executive director",
        ),
    ),
    "consultant": (
        "Consultant",
        ("consultant", "advisor", "strategist"),
    ),
    "engineer": (
        "Engineer",
        (
            "engineer", "engineering", "structural engineer",
            "mechanical engineer", "electrical engineer", "civil engineer",
        ),
    ),
    "physician": (
        "Physician",
        (
            "physician", "doctor", "surgeon", "cardiolog", "radiolog",
            "ophthalmolog", "neurolog", "oncolog", "veterinary",
        ),
    ),
    "attorney": (
        "Attorney",
        ("attorney", "lawyer", "legal consultant", "counsel"),
    ),
    "academic": (
        "Academic",
        (
            "professor", "lecturer", "faculty", "instructor", "teacher",
            "dean", "educator",
        ),
    ),
    "designer": (
        "Designer",
        (
            "designer", "creative director", "art director", "design director",
        ),
    ),
    "finance": (
        "Finance Professional",
        (
            "financ", "investment", "banker", "portfolio", "trader",
            "accountant",
        ),
    ),
}

INDUSTRY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Technology", (
        "software", "technology", "tech", "artificial intelligence", " ai",
        "machine learning", "saas", "computer", "internet", "app ",
        "digital", "data", "robot", "semiconductor", "cyber",
    )),
    ("Healthcare", (
        "health", "hospital", "medical", "clinic", "pharma", "biotech",
        "biomed", "patient", "veterinary",
    )),
    ("Life Sciences", (
        "biology", "biophysics", "nanofluid", "environmental", "chemistry",
        "genom", "molecular",
    )),
    ("Finance", (
        "financ", "bank", "invest", "capital", "insurance", "fintech",
    )),
    ("Hospitality", ("hospitality", "hotel", "tourism", "restaurant")),
    ("Legal", ("legal", "law ", "attorney", "lawyer", "claims")),
    ("Education", ("education", "university", "college", "academic", "school")),
    ("Engineering", (
        "structural", "civil", "mechanical", "electrical", "construction",
        "transportation",
    )),
    ("Media", ("advertising", "marketing", "media", "creative", "journal")),
    ("Energy", ("energy", "oil", "gas", "renewable", "climate")),
]

SPECIALTY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Artificial Intelligence", (
        "artificial intelligence", " ai", "machine learning", "deep learning",
        "neural", "nlp", "computer vision", "llm",
    )),
    ("SaaS", ("saas", "software as a service", "cloud")),
    ("Computer Science", ("computer science", "software", "programming", "algorithm")),
    ("Structural Engineering", ("structural engineer", "structural engineering")),
    ("Hospitality Consulting", ("hospitality", "hotel consult")),
    ("Cardiology", ("cardiolog",)),
    ("Oncology", ("oncolog", "cancer")),
    ("Biophysics", ("biophysics", "biomedicine")),
    ("Environmental Science", ("environmental",)),
    ("Veterinary Medicine", ("veterinary",)),
    ("FinTech", ("fintech", "financial services", "payment")),
    ("Transportation", ("transportation", "intelligent transportation")),
    ("Nanotechnology", ("nanofluid", "nano")),
    ("Product Design", ("tech design", "product design", "industrial design")),
]

FIELD_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (FIELD_ATHLETICS, (
        "athlet", "coach", "sport", "soccer", "tennis", "olympic",
    )),
    (FIELD_EDUCATION, (
        "professor", "lecturer", "teacher", "educator", "college",
        "university instructor", "faculty",
    )),
    (FIELD_ARTS, (
        "artist", "designer", "creative director", "advertising creative",
        "musician", "performer", "filmmaker", "photographer",
    )),
    (FIELD_SCIENCES, (
        "research", "scientist", "science", "engineer", "software",
        "physician", "medical", "biology", "physics", "chemist",
        "computer", "data", "ai", "machine learning", "developer",
        "veterinary", "nano",
    )),
    (FIELD_BUSINESS, (
        "business", "entrepreneur", "founder", "ceo", "executive",
        "consultant", "financ", "market", "hospitality", "manager",
        "product", "sales", "attorney", "legal",
    )),
]

_STOP = {
    "the", "and", "of", "in", "for", "a", "an", "or", "to", "at", "with",
    "on", "as", "by", "from", "professional", "specialist", "senior",
    "assistant", "head", "director", "individual", "person", "field",
}

_STATED_FIELD = re.compile(
    r"extraordinary ability in (?:the )?"
    r"(sciences?|arts?|education|business|athletics)\b",
    re.IGNORECASE,
)


def _blob(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            bits.extend(str(v) for v in part.values() if v)
        elif isinstance(part, (list, tuple)):
            bits.extend(str(v) for v in part if v)
        elif part:
            bits.append(str(part))
    return " ".join(bits).lower()


def match_keywords(text: str, table: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    low = (text or "").lower()
    found: list[str] = []
    for label, needles in table:
        if any(n in low for n in needles) and label not in found:
            found.append(label)
    return found


def occupation_families(text: str) -> list[str]:
    low = f" {(text or '').lower()} "
    found: list[str] = []
    for family, (_canonical, needles) in OCCUPATION_FAMILIES.items():
        if any(n in low for n in needles) and family not in found:
            found.append(family)
    return found


def canonical_occupations(text: str) -> list[str]:
    families = occupation_families(text)
    return [OCCUPATION_FAMILIES[f][0] for f in families]


def occupation_search_tags(text: str) -> list[str]:
    """Related titles that should retrieve together."""
    tags: list[str] = []
    for family in occupation_families(text):
        canonical, aliases = OCCUPATION_FAMILIES[family]
        tags.append(canonical.lower())
        tags.extend(aliases)
    extra = [
        tok for tok in re.findall(r"[a-z]{4,}", (text or "").lower())
        if tok not in _STOP
    ]
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags + extra:
        key = tag.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def classify_text(text: str, *, stated_field: str | None = None) -> dict[str, list[str]]:
    """Return multi-label field / industry / occupation / specialty tags."""
    occupations = canonical_occupations(text)
    if not occupations:
        cleaned = re.sub(r"\s+", " ", (text or "").strip(" ,.;"))
        if cleaned:
            occupations = [cleaned[:80]]
    fields = match_keywords(text, FIELD_KEYWORDS)
    if stated_field:
        mapped = {
            "science": FIELD_SCIENCES,
            "sciences": FIELD_SCIENCES,
            "art": FIELD_ARTS,
            "arts": FIELD_ARTS,
            "education": FIELD_EDUCATION,
            "business": FIELD_BUSINESS,
            "athletics": FIELD_ATHLETICS,
        }.get(stated_field.lower())
        if mapped and mapped not in fields:
            fields.insert(0, mapped)
    if not fields:
        fields = [FIELD_SCIENCES]
    return {
        "field": fields,
        "industry": match_keywords(text, INDUSTRY_KEYWORDS) or ["General"],
        "occupation": occupations,
        "specialty": match_keywords(text, SPECIALTY_KEYWORDS),
    }


def stated_field_from_text(text: str) -> str | None:
    counts: dict[str, int] = {}
    for m in _STATED_FIELD.finditer(text or ""):
        key = m.group(1).lower()
        key = {"science": "sciences", "art": "arts"}.get(key, key)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def classify_intake(intake: dict[str, Any]) -> dict[str, list[str]]:
    identity = intake.get("identity") or {}
    jobs = intake.get("employment") or []
    job_bits = []
    for job in jobs:
        if isinstance(job, dict):
            job_bits.extend([job.get("title") or "", job.get("organization") or "",
                             job.get("responsibilities") or ""])
    blob = _blob(
        intake.get("field_of_endeavor"),
        intake.get("summary"),
        identity.get("occupation"),
        identity.get("title"),
        job_bits,
        [e.get("field") for e in (intake.get("education") or []) if isinstance(e, dict)],
    )
    stated = stated_field_from_text(blob)
    return classify_text(blob, stated_field=stated)


def primary_field_folder(fields: list[str]) -> str:
    """One folder name for storing the PDF copy (Sciences, Business, ...)."""
    for name in (FIELD_SCIENCES, FIELD_BUSINESS, FIELD_ARTS, FIELD_EDUCATION, FIELD_ATHLETICS):
        if name in fields:
            return name
    return "_Review_Needed"
