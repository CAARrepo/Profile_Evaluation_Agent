"""Evaluation Agent: route intake profiles to category-specific evaluators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from .config import EVAL_OUTPUT_DIR, INTAKE_OUTPUT_DIR, OLLAMA_HOST, OLLAMA_MODEL
from .evaluators import EB1AEvaluator, NIWEvaluator, O1AEvaluator
from .llm_judge import LLMJudge
from .router import detect_visa_category
from .schema import EvaluationResult, VisaCategory


class EvaluationAgent:
    """Facade: load intake JSON → detect category → run LLM evaluator → save result."""

    def __init__(
        self,
        *,
        model: str = OLLAMA_MODEL,
        host: str = OLLAMA_HOST,
        judge: Optional[LLMJudge] = None,
    ) -> None:
        self.model = model
        self.host = host
        shared_judge = judge or LLMJudge(model=model, host=host, ensure_available=True)
        self._evaluators = {
            "O-1A": O1AEvaluator(model=model, host=host, judge=shared_judge),
            "EB-1A": EB1AEvaluator(model=model, host=host, judge=shared_judge),
            "EB-2 NIW": NIWEvaluator(model=model, host=host, judge=shared_judge),
        }

    def evaluate_intake(
        self,
        intake: dict[str, Any],
        *,
        category_override: Optional[str] = None,
    ) -> EvaluationResult:
        category: VisaCategory = detect_visa_category(intake, override=category_override)
        evaluator = self._evaluators[category]
        return evaluator.evaluate(intake)

    def evaluate_file(
        self,
        intake_path: Union[str, Path],
        *,
        category_override: Optional[str] = None,
    ) -> EvaluationResult:
        path = Path(intake_path)
        intake = json.loads(path.read_text(encoding="utf-8"))
        return self.evaluate_intake(intake, category_override=category_override)

    def evaluate_lead(
        self,
        lead_id: str,
        *,
        intake_dir: Path = INTAKE_OUTPUT_DIR,
        category_override: Optional[str] = None,
    ) -> EvaluationResult:
        path = intake_dir / f"{lead_id}_intake.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Intake output not found: {path}. Run the Intake Agent first."
            )
        return self.evaluate_file(path, category_override=category_override)

    def evaluate_and_save(
        self,
        lead_id: str,
        *,
        intake_dir: Path = INTAKE_OUTPUT_DIR,
        output_dir: Path = EVAL_OUTPUT_DIR,
        category_override: Optional[str] = None,
    ) -> Path:
        result = self.evaluate_lead(
            lead_id,
            intake_dir=intake_dir,
            category_override=category_override,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{lead_id}_evaluation.json"
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return out_path
