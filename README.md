# Profile Evaluation Agent (MVP)

Multi-agent visa profile pipeline for **O-1A**, **EB-1A**, and **EB-2 NIW**.

```
User Submission
        ↓
   Intake Agent
        ↓
 Evaluation Agent Router
        ↓
 ┌──────────┬──────────┬──────────┐
 O-1A       EB-1A      EB-2 NIW
 Evaluator  Evaluator  Evaluator
 (+ KB)     (+ KB)     (+ KB)
        ↓
 Structured Evaluation JSON
        ↓
 Report Agent → Initial User Report (no attorney review)
        ↓
 (Optional later) Attorney Review → Final Report
```

## Setup

```bash
conda activate profile-evaluation
pip install -r requirements.txt
# Intake LLM (optional):
ollama serve
ollama pull qwen2.5:7b-instruct
```

Env name: **`profile-evaluation`** (Python 3.11)

## Intake Agent

Organizes questionnaire + optional docs into `intake_outputs/<lead_id>_intake.json` for **O-1A, EB-1A, and EB-2 NIW**. Category comes from `User_Info.csv` `immigration_category`.

MVP rules: assume Yes-claims true; no follow-up questions; missing docs → `information_gaps` only (never blocks).

```bash
python -m intake_agent list-leads
python -m intake_agent list-o1
python -m intake_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136
python -m intake_agent run --no-llm --lead-id 00b14135-8fa0-4525-a88d-21605f615136
```

## Evaluation Agent

Reads Intake JSON, detects visa category, and uses a **local Ollama LLM** to reason about each criterion against the knowledge base (no heuristic keyword scoring).

| Category | Knowledge base |
|----------|----------------|
| O-1A | `knowledge_base/O1A_Knowledge_Base/01_Controlling_Sources/` |
| EB-1A | `knowledge_base/EB1A_Knowledge_Base/01_Controlling_Sources/` |
| EB-2 NIW | `knowledge_base/EB2NIW_Knowledge_Base/01_Controlling_Sources/` |

```bash
# Ensure Ollama is running and model is pulled
ollama serve
ollama pull qwen2.5:7b-instruct

# After intake exists:
python -m evaluation_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136

# Optional model override:
python -m evaluation_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136 --model qwen2.5:7b-instruct

# Or evaluate a specific intake file / force category:
python -m evaluation_agent run --intake-file tests/fixtures/intake_o1a.json
python -m evaluation_agent run --intake-file tests/fixtures/intake_eb1a.json --category "EB-1A"
python -m evaluation_agent run --intake-file tests/fixtures/intake_niw.json
```

Env overrides: `OLLAMA_HOST`, `OLLAMA_MODEL`, or `EVAL_OLLAMA_MODEL`.

Output: `evaluation_outputs/<lead_id>_evaluation.json`

## Report Agent (initial user report)

Turns Evaluation JSON into:
- internal Markdown + JSON
- polished client-facing PDF: `report_outputs/<case_id>_initial_profile_evaluation.pdf`

- Does **not** re-score or reclassify the case
- **`attorney_reviewed: false`**
- Client-friendly status labels; no mid-sentence truncation

```bash
# After evaluation exists:
python -m report_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136

# Or from an evaluation file:
python -m report_agent run --evaluation-file evaluation_outputs/<id>_evaluation.json
```

Output:
- `report_outputs/<lead_id>_initial_report.md`
- `report_outputs/<lead_id>_initial_report.json`
- `report_outputs/<lead_id>_initial_profile_evaluation.pdf`

## Tests

```bash
pytest -q
```

## Data layout

| Path | Role |
|------|------|
| `datasets/User_Info.csv` | Lead identity + immigration category |
| `datasets/Detailed_questionarie.csv` | Questionnaire answers |
| `datasets/lead-documents/<lead_id>/` | Optional uploads |
| `knowledge_base/<CAT>_Knowledge_Base/` | Per-category material. Runtime reads `01_Controlling_Sources/` only |
| `knowledge_base/<CAT>_Knowledge_Base_original/` | Untouched archive copies (never modify) |
| `intake_outputs/` | Intake Agent JSON |
| `evaluation_outputs/` | Evaluation Agent JSON |
| `report_outputs/` | Initial user reports (Markdown + JSON) |

### Knowledge base layout

Each category folder holds material separated by legal authority:

```
knowledge_base/O1A_Knowledge_Base/
├── 00_Catalog/                            metadata for the AAO decisions
├── 01_Controlling_Sources/                loaded at evaluation runtime
│   ├── CFR/                               binding regulation
│   └── USCIS_Policy_Manual/               USCIS policy guidance
└── 02_AAO_Non_Precedent_Decisions/        51 decisions, filed by field
```

`EB1A_Knowledge_Base/` follows the same pattern, filing AAO PDFs by statutory
field (Sciences, Business, Arts, Education, Athletics).
`EB2NIW_Knowledge_Base/` uses NIW tracks instead: **Research**, **Entrepreneurs**,
and **Directors**. Original non-precedent PDFs stay in the matching
`*_Knowledge_Base_original/` archive and must not be modified. Matter of
Dhanasar is **precedent** and belongs with controlling sources, not in the
NIW non-precedent catalog.

`load_knowledge_base()` merges the CFR criteria with Policy Manual evidence
guidance. The older `*_evaluation_knowledge_base.json` files are not read.
For O-1A, each criterion prompt may include up to two **catalog cards**.
For EB-1A, evaluation retrieves criterion intelligence plus 3–5 similar
sustained and 3–5 similar dismissed AAO cases (metadata + TF-IDF, never the
full PDFs). For EB-2 NIW, the same retrieval runs per Dhanasar prong.
Cards are labeled non-precedent and are not the legal test.

Rebuild the EB-1A AAO indexes (does not touch the original folder):

```bash
python tools/eb1a_aao_extract.py
python tools/eb1a_aao_parse.py
python tools/eb1a_aao_build_kb.py
```

Rebuild the EB-2 NIW AAO indexes (does not touch the original folder):

```bash
python tools/niw_aao_extract.py
python tools/niw_aao_parse.py
python tools/niw_aao_build_kb.py
```

Accessors live in `evaluation_agent/kb_loader.py`:

```python
from evaluation_agent.kb_loader import (
    load_knowledge_base, load_controlling_sources, find_aao_decisions,
    aao_decision_pdf, aao_authority_label,
)

sources = load_controlling_sources("EB-2 NIW")     # {"cfr": [...], "policy_manual": [...]}
hits = find_aao_decisions(                          # illustrative only, non-binding
    "O-1A", criterion="Original contributions", determination="rejected",
    field="Science", limit=3,
)
pdf = aao_decision_pdf("O-1A", hits[0])
```

AAO decisions are **non-precedent and non-binding**; surface them with
`aao_authority_label()` and cite CFR or the Policy Manual for the legal
standard. Distinctions:

- **LEGAL REQUIREMENT** — statute / CFR / Policy Manual / binding precedent
- **OBSERVED AAO PATTERN** — non-precedent illustrations and multi-case patterns


## Notes

- Evaluation is **preliminary** only; `attorney_review_required` is always true on eval output.
- Initial user reports are generated **without** attorney review; attorney review is a later optional step.
- Missing evidence does **not** auto-fail a criterion in MVP.
- O-1A / EB-1A include criterion scores + final-merits notes.
- EB-2 NIW includes underlying EB-2 + NIW prongs 1–3.
