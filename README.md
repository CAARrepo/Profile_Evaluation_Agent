# O-1 Intake Agent

First stage of the multi-agent O-1 visa evaluation pipeline.

```
User submits profile/docs
        ↓
   Intake Agent   ← you are here
        ↓
  Evidence Agents
        ↓
 O-1 Evaluation Agent
        ↓
 Quality-Control Agent
        ↓
  Attorney Review
        ↓
 Report sent to user
```

## What it does

For one lead (evaluation case), the Intake Agent:

1. Loads `User_Info.csv` + `Detailed_questionarie.csv`
2. Extracts text from files under `lead-documents/<lead_id>/`
3. Builds a standardized applicant profile
4. Separates **claims** from **supporting evidence**
5. Flags missing / conflicting information
6. Writes `intake_outputs/<lead_id>_intake.json` for Evidence Agents

## Local model

Hardware target: **RTX 4050 (6GB VRAM)** + ~15GB RAM.

Default model: **`qwen2.5:7b-instruct`** via [Ollama](https://ollama.com) — strong structured extraction that fits 6GB VRAM.

```bash
ollama pull qwen2.5:7b-instruct
```

Override with env vars:

- `OLLAMA_MODEL`
- `OLLAMA_HOST` (default `http://127.0.0.1:11434`)

## Setup

```bash
# conda env already available on this machine:
# C:\Users\mujah\miniconda3\envs\eligibility-tool\python.exe

pip install -r requirements.txt
ollama serve
ollama pull qwen2.5:7b-instruct
```

## Run

```bash
# List O-1 leads
python -m intake_agent list-o1

# Auto-pick a completed O-1 lead with local resume and run intake
python -m intake_agent run

# Run a specific lead
python -m intake_agent run --lead-id 00b14135-8fa0-4525-a88d-21605f615136

# Deterministic seed only (no LLM)
python -m intake_agent run --no-llm --lead-id 00b14135-8fa0-4525-a88d-21605f615136
```

## Data layout

| Path | Role |
|------|------|
| `User_Info.csv` | Lead identity + immigration category |
| `Detailed_questionarie.csv` | O-1 questionnaire answers (JSON) |
| `lead-documents/<lead_id>/...` | Résumé / supporting uploads |
| `intake_outputs/` | Intake Agent JSON outputs |

## Output shape (high level)

- `identity` — contact, status, job offer, LinkedIn / Scholar
- `criteria[]` — each O-1 criterion with `claim_only` / `supported` / gaps
- `claims[]` — asserted facts not yet proven by evidence agents
- `missing_information[]` — follow-up questions for the applicant
- `conflicts[]` — questionnaire vs résumé mismatches
- `readiness` — `ready_for_evidence_agents` | `needs_more_info` | `incomplete`
