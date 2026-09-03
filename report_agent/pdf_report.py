"""Polished client-facing PDF generator (ReportLab)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Image as PdfImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .config import BRAND_CHARCOAL, BRAND_LAVENDER, BRAND_NAVY, BRAND_PAPER
from .schema import ClientReportContent
from .text_utils import complete_sentences, fix_mojibake

_NAVY = HexColor(f"#{BRAND_NAVY}")
_SLATE = HexColor(f"#{BRAND_CHARCOAL}")
_RULE = HexColor(f"#{BRAND_LAVENDER}")
_ROW_ALT = HexColor(f"#{BRAND_PAPER}")


def _register_fonts() -> tuple[str, str]:
    """Register Windows / common TTF fonts with Unicode support."""
    candidates = [
        (
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            "ReportArial",
            "ReportArial-Bold",
        ),
        (
            Path(r"C:\Windows\Fonts\calibri.ttf"),
            Path(r"C:\Windows\Fonts\calibrib.ttf"),
            "ReportCalibri",
            "ReportCalibri-Bold",
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            "ReportDejaVu",
            "ReportDejaVu-Bold",
        ),
    ]
    for regular, bold, rname, bname in candidates:
        if regular.is_file() and bold.is_file():
            if rname not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(rname, str(regular)))
                pdfmetrics.registerFont(TTFont(bname, str(bold)))
            return rname, bname
    # Fallback to Helvetica (limited Unicode; still better than crashing)
    return "Helvetica", "Helvetica-Bold"


def _finished_item(text: str) -> str:
    """Keep complete sentences or short labels — never leave a cut ending in '...'."""
    cleaned = " ".join(fix_mojibake(text or "").split())
    if not cleaned:
        return ""
    if "..." in cleaned:
        cleaned = cleaned.split("...")[0].strip()
    finished = complete_sentences(cleaned, max_sentences=3) or cleaned
    finished = finished.rstrip("…").strip()
    if finished.endswith("..."):
        finished = finished[:-3].strip()
    if not finished:
        return ""
    if finished[-1] in ".!?":
        return finished
    # Short document labels (e.g. "Award certificate") are complete as phrases.
    if len(finished) <= 140:
        return finished
    return ""


def _cell_stack(items: list[str], style: ParagraphStyle, width: float):
    """Wrap each document item fully so table cells grow instead of truncating."""
    finished = [_finished_item(item) for item in items]
    finished = [item for item in finished if item]
    if not finished:
        return _p("—", style)
    inner_width = max(width - 8, 40)
    rows = [[_p(item, style)] for item in finished]
    inner = Table(rows, colWidths=[inner_width])
    inner.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return inner


def _bullet_block(items: list[str], styles: dict[str, ParagraphStyle], width: float) -> Table:
    mark_w = 0.18 * inch
    text_w = max(width - mark_w, 1 * inch)
    rows = [
        [_p("•", styles["bullet_mark"]), _p(item, styles["bullet_text"])]
        for item in items
    ]
    table = Table(rows, colWidths=[mark_w, text_w])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 4),
                ("LEFTPADDING", (1, 0), (1, -1), 0),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


class ConsultationButton(Flowable):
    """Clickable CTA; the whole rounded rectangle is a link."""

    def __init__(
        self,
        label: str,
        url: str,
        font: str,
        width: float = 3.35 * inch,
        height: float = 0.46 * inch,
    ) -> None:
        super().__init__()
        self.label = label
        self.url = url
        self.font = font
        self.width = width
        self.height = height

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(_NAVY)
        canvas.roundRect(0, 0, self.width, self.height, 6, fill=1, stroke=0)
        canvas.setFillColor(white)
        canvas.setFont(self.font, 11)
        canvas.drawCentredString(self.width / 2.0, self.height / 2.0 - 3.5, self.label)
        canvas.linkURL(self.url, (0, 0, self.width, self.height), relative=1, thickness=0)
        canvas.restoreState()


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    # Escape HTML so raw tags never appear; use ParagraphStyle for emphasis.
    safe = (
        fix_mojibake(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(safe, style)


def _styles(font: str, font_bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName=font_bold,
            fontSize=18,
            leading=22,
            textColor=_NAVY,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName=font,
            fontSize=10,
            leading=13,
            textColor=_SLATE,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "ReportH1",
            parent=base["Heading2"],
            fontName=font_bold,
            fontSize=12,
            leading=15,
            textColor=_NAVY,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=13,
            textColor=black,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet_mark": ParagraphStyle(
            "ReportBulletMark",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=12.5,
            textColor=_NAVY,
            alignment=TA_LEFT,
            leftIndent=0,
            firstLineIndent=0,
        ),
        "bullet_text": ParagraphStyle(
            "ReportBulletText",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=12.5,
            textColor=black,
            alignment=TA_LEFT,
            leftIndent=0,
            firstLineIndent=0,
        ),
        "table_header": ParagraphStyle(
            "ReportTH",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=8,
            leading=10,
            textColor=white,
        ),
        "table_cell": ParagraphStyle(
            "ReportTD",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=10.5,
            textColor=black,
        ),
        "footer": ParagraphStyle(
            "ReportFooter",
            parent=base["Normal"],
            fontName=font,
            fontSize=7.5,
            leading=9,
            textColor=_SLATE,
            alignment=TA_CENTER,
        ),
        "meta": ParagraphStyle(
            "ReportMeta",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=12,
            textColor=_SLATE,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "section_label": ParagraphStyle(
            "ReportSectionLabel",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=9.5,
            leading=12.5,
            textColor=_NAVY,
            alignment=TA_LEFT,
            spaceBefore=4,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=10.5,
            leading=13.5,
            textColor=_NAVY,
            alignment=TA_LEFT,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "caption": ParagraphStyle(
            "ReportCaption",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=10,
            textColor=_SLATE,
            alignment=TA_CENTER,
            spaceBefore=4,
            spaceAfter=8,
        ),
    }


def _fitted_image(path: str, max_width: float, max_height: float) -> PdfImage:
    reader = ImageReader(path)
    width_px, height_px = reader.getSize()
    if width_px <= 0 or height_px <= 0:
        raise ValueError(f"Invalid image size for {path}")
    scale = min(max_width / width_px, max_height / height_px)
    image = PdfImage(path, width=width_px * scale, height=height_px * scale)
    image.hAlign = "CENTER"
    return image


def write_client_pdf(content: ClientReportContent, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font, font_bold = _register_fonts()
    styles = _styles(font, font_bold)

    def _on_page(canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.5)
        y = 0.55 * inch
        canvas.line(0.75 * inch, y + 12, LETTER[0] - 0.75 * inch, y + 12)
        canvas.setFont(font, 7.5)
        canvas.setFillColor(_SLATE)
        canvas.drawRightString(LETTER[0] - 0.75 * inch, y, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.85 * inch,
        title=content.document_title,
        author="Profile Evaluation Agent",
    )

    story: list = []
    section = 0
    content_width = LETTER[0] - doc.leftMargin - doc.rightMargin

    def _heading(title: str) -> None:
        nonlocal section
        section += 1
        story.append(_p(f"{section}. {title}", styles["h1"]))

    def _bullets(items: list[str]) -> None:
        if items:
            story.append(_bullet_block(items, styles, content_width))

    story.append(_p(content.document_title, styles["title"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_NAVY, spaceAfter=8))
    story.append(_p(f"Applicant: {content.applicant_name}", styles["meta"]))
    story.append(_p(f"Assessment date: {content.assessment_date}", styles["meta"]))
    story.append(_p(f"Visa category: {content.visa_category}", styles["meta"]))
    if content.case_id:
        story.append(_p(f"Case reference: {content.case_id}", styles["meta"]))
    story.append(Spacer(1, 6))

    _heading("Important Preliminary Disclaimer")
    story.append(_p(content.disclaimer, styles["body"]))

    _heading("Executive Summary")
    for para in content.overall_assessment_paragraphs:
        story.append(_p(para, styles["body"]))

    if content.show_snapshot:
        _heading("Assessment Snapshot")
        snap = content.snapshot
        snap_data = [
            [
                _p("Strong", styles["table_header"]),
                _p("Potential", styles["table_header"]),
                _p("Weak", styles["table_header"]),
                _p("Not indicated", styles["table_header"]),
            ],
            [
                _p(str(snap.get("strong", 0)), styles["table_cell"]),
                _p(str(snap.get("potential", 0)), styles["table_cell"]),
                _p(str(snap.get("weak", 0)), styles["table_cell"]),
                _p(str(snap.get("not_indicated", 0)), styles["table_cell"]),
            ],
        ]
        snap_table = Table(snap_data, colWidths=[1.6 * inch, 1.6 * inch, 1.6 * inch, 1.7 * inch])
        snap_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                    ("BACKGROUND", (0, 1), (-1, 1), _ROW_ALT),
                    ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, _RULE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(snap_table)
        story.append(Spacer(1, 8))

    overview_title = content.step1_heading or "Criterion-by-Criterion Overview"
    if not overview_title[:1].isdigit():
        _heading(overview_title)
    else:
        story.append(_p(overview_title, styles["h1"]))
    intro = content.criterion_overview_intro or (
        "Statuses below are preliminary labels for discussion only. "
        "They do not mean a criterion has been legally satisfied."
    )
    story.append(_p(intro, styles["body"]))

    if content.show_status_column:
        header = [
            _p("Criterion", styles["table_header"]),
            _p("Preliminary status", styles["table_header"]),
            _p("Explanation", styles["table_header"]),
            _p("Priority evidence", styles["table_header"]),
        ]
        body_rows = []
        col_widths = [1.45 * inch, 1.55 * inch, 2.35 * inch, 1.55 * inch]
        for row in content.criterion_rows:
            body_rows.append(
                [
                    _p(row.criterion_name, styles["table_cell"]),
                    _p(row.client_status_label, styles["table_cell"]),
                    _p(row.explanation or "—", styles["table_cell"]),
                    _cell_stack(row.top_evidence[:5], styles["table_cell"], col_widths[3]),
                ]
            )
    else:
        header = [
            _p("Criterion", styles["table_header"]),
            _p("Explanation", styles["table_header"]),
            _p("Existing documents", styles["table_header"]),
            _p("Outstanding documents", styles["table_header"]),
        ]
        body_rows = []
        col_widths = [1.45 * inch, 2.35 * inch, 1.55 * inch, 1.55 * inch]
        for row in content.criterion_rows:
            number = row.criterion_number or 0
            label = f"{number}. {row.criterion_name}" if number else row.criterion_name
            body_rows.append(
                [
                    _p(label, styles["table_cell"]),
                    _p(row.explanation or "—", styles["table_cell"]),
                    _cell_stack(row.existing_documents[:6], styles["table_cell"], col_widths[2]),
                    _cell_stack(row.outstanding_documents[:6], styles["table_cell"], col_widths[3]),
                ]
            )

    # One table per criterion so explanation cells can grow vertically and a
    # tall row can start on a new page instead of being clipped with "...".
    header_table = Table([header], colWidths=col_widths, repeatRows=0)
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(header_table)
    for index, cells in enumerate(body_rows, start=1):
        row_table = Table([cells], colWidths=col_widths, repeatRows=0)
        cmds = [
            ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, _RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if index % 2 == 0:
            cmds.append(("BACKGROUND", (0, 0), (-1, -1), _ROW_ALT))
        row_table.setStyle(TableStyle(cmds))
        story.append(row_table)

    if content.step2_heading or content.step2_paragraphs:
        story.append(_p(content.step2_heading or "STEP 2 — Final Merits Determination", styles["h1"]))
        story.append(
            _p(
                "This final-merits discussion is separate from whether three criteria currently look supportable.",
                styles["body"],
            )
        )
        for para in content.step2_paragraphs:
            story.append(_p(para, styles["body"]))

    _heading("Priority Opportunities")
    if content.priority_opportunities:
        _bullets(content.priority_opportunities)
    else:
        story.append(_p("No priority opportunities were identified from the current record.", styles["body"]))

    _heading("Priority Evidence Checklist")
    if content.information_still_needed:
        story.append(_p(content.checklist_gaps_heading or "Information still needed", styles["section_label"]))
        _bullets(content.information_still_needed)
    if content.priority_evidence_checklist:
        story.append(_p(content.checklist_docs_heading or "Recommended supporting materials", styles["section_label"]))
        _bullets(content.priority_evidence_checklist)
    if content.potential_evidence_to_develop:
        story.append(_p("Evidence the applicant does not currently possess", styles["section_label"]))
        _bullets(content.potential_evidence_to_develop)
    if content.aao_trace_note:
        story.append(_p(content.aao_trace_note, styles["body"]))
    if (
        not content.information_still_needed
        and not content.priority_evidence_checklist
        and not content.potential_evidence_to_develop
    ):
        story.append(
            _p(
                "Continue collecting independent, verifiable documents for the strongest opportunities above.",
                styles["body"],
            )
        )

    if content.firm_approval_rate_line or content.firm_results_disclosure:
        _heading("Past Results in This Category")
        if content.firm_approval_rate_line:
            story.append(_p(content.firm_approval_rate_line, styles["body"]))
        if content.firm_results_disclosure:
            story.append(_p(content.firm_results_disclosure, styles["body"]))

    if content.firm_case_study_title or content.firm_case_study_paragraphs:
        _heading("Example of an Approved Case in This Category")
        if content.firm_case_study_heading:
            story.append(_p(content.firm_case_study_heading, styles["section_label"]))
        if content.firm_case_study_attribution:
            story.append(_p(content.firm_case_study_attribution, styles["body"]))
        if content.firm_case_study_title:
            story.append(_p(content.firm_case_study_title, styles["h2"]))
        for para in content.firm_case_study_paragraphs:
            if para.startswith("## "):
                story.append(_p(para[3:], styles["section_label"]))
            else:
                story.append(_p(para, styles["body"]))
        if content.firm_case_study_image and Path(content.firm_case_study_image).is_file():
            image_bits: list = [
                Spacer(1, 8),
                _fitted_image(content.firm_case_study_image, 6.8 * inch, 3.2 * inch),
            ]
            if content.firm_case_study_image_caption:
                image_bits.append(_p(content.firm_case_study_image_caption, styles["caption"]))
            story.append(KeepTogether(image_bits))

    if content.firm_timeline_items or content.firm_cost_items:
        _heading(content.timeline_section_title or "Preparation and Processing Timeline")
        if content.firm_timeline_heading:
            story.append(_p(content.firm_timeline_heading, styles["section_label"]))
        if content.firm_timeline_items:
            _bullets(content.firm_timeline_items)
        if content.firm_cost_items:
            if content.firm_cost_heading:
                story.append(_p(content.firm_cost_heading, styles["section_label"]))
            _bullets(content.firm_cost_items)

    if content.consultation_heading or content.consultation_url:
        _heading(content.consultation_heading or "Book a free consultation")
        if content.consultation_photo and Path(content.consultation_photo).is_file():
            story.append(_fitted_image(content.consultation_photo, 1.6 * inch, 1.6 * inch))
        if content.consultation_intro:
            story.append(_p(content.consultation_intro, styles["body"]))
        if content.consultation_items:
            _bullets(content.consultation_items)
        if content.consultation_url:
            story.append(Spacer(1, 10))
            button = ConsultationButton(
                "Book a Free Consultation",
                content.consultation_url,
                font_bold,
            )
            button.hAlign = "CENTER"
            story.append(button)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return output_path
