"""Report Agent: Evaluation JSON → Markdown/JSON (internal) + polished client PDF."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from .config import EVAL_OUTPUT_DIR, INTAKE_OUTPUT_DIR, REPORT_OUTPUT_DIR
from .pdf_report import write_client_pdf
from .renderer import build_full_report_bundle
from .schema import ClientReportContent, InitialReport


class ReportAgent:
    """Template-based report generator. Does not re-evaluate or reclassify the case."""

    def generate_from_evaluation(
        self,
        evaluation: dict[str, Any],
        *,
        intake: Optional[dict[str, Any]] = None,
        evaluation_path: str = "",
    ) -> tuple[InitialReport, str, ClientReportContent]:
        return build_full_report_bundle(
            evaluation,
            intake=intake,
            evaluation_path=evaluation_path,
        )

    def generate_for_lead(
        self,
        lead_id: str,
        *,
        eval_dir: Path = EVAL_OUTPUT_DIR,
        intake_dir: Path = INTAKE_OUTPUT_DIR,
    ) -> tuple[InitialReport, str, ClientReportContent, Path]:
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
        report, markdown, client = self.generate_from_evaluation(
            evaluation,
            intake=intake,
            evaluation_path=str(eval_path),
        )
        return report, markdown, client, eval_path

    def generate_from_file(
        self,
        evaluation_file: Union[str, Path],
        *,
        intake_file: Optional[Union[str, Path]] = None,
    ) -> tuple[InitialReport, str, ClientReportContent]:
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
    ) -> tuple[Path, Path, Path]:
        report, markdown, client, _ = self.generate_for_lead(
            lead_id,
            eval_dir=eval_dir,
            intake_dir=intake_dir,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        case_id = report.case_id or lead_id
        md_path = output_dir / f"{case_id}_initial_report.md"
        json_path = output_dir / f"{case_id}_initial_report.json"
        pdf_path = output_dir / f"{case_id}_initial_profile_evaluation.pdf"

        write_client_pdf(client, pdf_path)
        report.markdown_path = str(md_path)
        report.pdf_path = str(pdf_path)
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return md_path, json_path, pdf_path
