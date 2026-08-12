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

Organizes questionnaire + optional docs into `intake_outputs/<lead_id>_intake.json`.

MVP rules: assume Yes-claims true; no follow-up questions; missing docs → `information_gaps` only (never blocks).

```bash
python -m intake_agent list-o1
python -m intake_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136
python -m intake_agent run --no-llm --lead-id 00b14135-8fa0-4525-a88d-21605f615136
```

## Evaluation Agent

Reads Intake JSON, detects visa category, routes to the matching evaluator + knowledge base:

| Category | Knowledge base |
|----------|----------------|
| O-1A | `knowledge_base/O1A_evaluation_knowledge_base.json` |
| EB-1A | `knowledge_base/EB1A_evaluation_knowledge_base.json` |
| EB-2 NIW | `knowledge_base/EB2_NIW_evaluation_knowledge_base.json` |

```bash
# After intake exists:
python -m evaluation_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136

# Or evaluate a specific intake file / force category:
python -m evaluation_agent run --intake-file tests/fixtures/intake_o1a.json
python -m evaluation_agent run --intake-file tests/fixtures/intake_eb1a.json --category "EB-1A"
python -m evaluation_agent run --intake-file tests/fixtures/intake_niw.json
```

Output: `evaluation_outputs/<lead_id>_evaluation.json`

## Report Agent (initial user report)

Turns Evaluation JSON into a **user-facing initial report** (Markdown + JSON).

- Does **not** re-score the case
- **`attorney_reviewed: false`** — safe to send as a preliminary assessment
- Includes strengths, gaps, recommended evidence, and a clear disclaimer

```bash
# After evaluation exists:
python -m report_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136

# Or from an evaluation file:
python -m report_agent run --evaluation-file evaluation_outputs/00b14135-8fa0-4525-a88d-21605f615136_evaluation.json
```

Output:
- `report_outputs/<lead_id>_initial_report.md`
- `report_outputs/<lead_id>_initial_report.json`

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
| `knowledge_base/*.json` | Evaluation rules (do not modify) |
| `intake_outputs/` | Intake Agent JSON |
| `evaluation_outputs/` | Evaluation Agent JSON |
| `report_outputs/` | Initial user reports (Markdown + JSON) |

## Notes

- Evaluation is **preliminary** only; `attorney_review_required` is always true on eval output.
- Initial user reports are generated **without** attorney review; attorney review is a later optional step.
- Missing evidence does **not** auto-fail a criterion in MVP.
- O-1A / EB-1A include criterion scores + final-merits notes.
- EB-2 NIW includes underlying EB-2 + NIW prongs 1–3.
