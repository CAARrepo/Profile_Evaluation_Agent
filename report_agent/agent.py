"""Report Agent: Evaluation JSON → initial user-facing report (no attorney review)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from .config import EVAL_OUTPUT_DIR, INTAKE_OUTPUT_DIR, REPORT_OUTPUT_DIR
from .renderer import build_report_model, render_markdown
from .schema import InitialReport


class ReportAgent:
    """Template-based report generator. Does not re-evaluate the case."""

    def generate_from_evaluation(
        self,
        evaluation: dict[str, Any],
        *,
        intake: Optional[dict[str, Any]] = None,
        evaluation_path: str = "",
    ) -> tuple[InitialReport, str]:
        report = build_report_model(
            evaluation,
            intake=intake,
            evaluation_path=evaluation_path,
        )
        markdown = render_markdown(report, evaluation)
        return report, markdown

    def generate_for_lead(
        self,
        lead_id: str,
        *,
        eval_dir: Path = EVAL_OUTPUT_DIR,
        intake_dir: Path = INTAKE_OUTPUT_DIR,
    ) -> tuple[InitialReport, str, Path]:
        eval_path = eval_dir / f"{lead_id}_evaluation.json"
        if not eval_path.is_file():
            raise FileNotFoundError(
                f"Evaluation output not found: {eval_path}. Run the Evaluation Agent first."
            )
        evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
        intake = None
        intake_path = intake_dir / f"{lead_id}_intake.json"
        if intake_path.is_file():
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
        report, markdown = self.generate_from_evaluation(
            evaluation,
            intake=intake,
            evaluation_path=str(eval_path),
        )
        return report, markdown, eval_path

    def generate_from_file(
        self,
        evaluation_file: Union[str, Path],
        *,
        intake_file: Optional[Union[str, Path]] = None,
    ) -> tuple[InitialReport, str]:
        eval_path = Path(evaluation_file)
        evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
        intake = None
        if intake_file:
            intake = json.loads(Path(intake_file).read_text(encoding="utf-8"))
        return self.generate_from_evaluation(
            evaluation,
            intake=intake,
            evaluation_path=str(eval_path),
        )

    def generate_and_save(
        self,
        lead_id: str,
        *,
        eval_dir: Path = EVAL_OUTPUT_DIR,
        intake_dir: Path = INTAKE_OUTPUT_DIR,
        output_dir: Path = REPORT_OUTPUT_DIR,
    ) -> tuple[Path, Path]:
        report, markdown, _ = self.generate_for_lead(
            lead_id,
            eval_dir=eval_dir,
            intake_dir=intake_dir,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / f"{lead_id}_initial_report.md"
        json_path = output_dir / f"{lead_id}_initial_report.json"
        report.markdown_path = str(md_path)
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return md_path, json_path
