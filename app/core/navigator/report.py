"""InnovaDerm Navigator — Coordinator Report Generator.

Ported from the handover's ``scripts/gen-coordinator-report.py``: the same
branded report, section for section and label for label, rendered from the
pipeline summary for human-in-the-loop review. The handover wrote a DOCX under
``outputs/reports/``; here it is a PDF, built in memory when it is downloaded,
and it never touches disk.

The layout calls mirror the handover's ``python-docx`` calls — a styled
paragraph, a branded heading, a branded table, a page break — through
:class:`ReportBuilder`, so each section below can still be read against the
original script line by line.

The text is set in ReportLab's standard Helvetica, which needs no font file on
the server. Those fonts cover the Windows-1252 repertoire — every Spanish letter
and the punctuation the agents write — but not emoji, so the handover's alert
emoji become the alert's colour, and any other character outside that repertoire
is dropped rather than printed as a box.

The cover, section 11's instructions and the closing page name the
organisation from :mod:`app.core.navigator.branding`.
"""

from datetime import datetime
from io import BytesIO
from typing import (
    Any,
    Literal,
)
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import (
    TA_CENTER,
    TA_LEFT,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.navigator import branding

# ── Brand colors ──────────────────────────────────────────────────────────
DEEP_BLUE = colors.HexColor("#264194")
TEAL = colors.HexColor("#00AFD0")
GREEN = colors.HexColor("#3AAA35")
DARK_GRAY = colors.HexColor("#333333")
LIGHT_GRAY = colors.HexColor("#F5F5F5")
WHITE = colors.white
RED = colors.HexColor("#CC0000")
AMBER = colors.HexColor("#E68A00")
GRID_GRAY = colors.HexColor("#BFBFBF")

URGENCY_COLORS = {
    "critical": RED,
    "high": AMBER,
    "medium": TEAL,
    "low": GREEN,
}

PDF_MEDIA_TYPE = "application/pdf"

# ReportLab's paragraph alignments: TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY.
Alignment = Literal[0, 1, 2, 4]

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
MARGIN = 2 * cm

# Characters the agents and the handover's own strings use that Helvetica
# cannot draw. The emoji carry meaning only through their colour, which the
# callers read from the original text before it is cleaned.
_REPLACEMENTS = {
    "⚑": "»",
    "↔": "<->",
    "→": "->",
    "≥": ">=",
    "≤": "<=",
    "✓": "Sí",
    "✔": "Sí",
    " ": " ",
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _dict(value: Any) -> dict[str, Any]:
    """A mapping, or an empty one when the model gave something else.

    Args:
        value: Any value.

    Returns:
        dict: The value, or ``{}``.
    """
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    """A list, or an empty one when the model gave something else.

    Args:
        value: Any value.

    Returns:
        list: The value, or ``[]``.
    """
    return value if isinstance(value, list) else []


def pdf_text(value: Any) -> str:
    """Text Helvetica can draw, escaped for a ReportLab paragraph.

    Args:
        value: Any value.

    Returns:
        str: The cleaned, markup-safe text.
    """
    text = str(value)
    for original, replacement in _REPLACEMENTS.items():
        text = text.replace(original, replacement)
    return escape(text.encode("cp1252", errors="ignore").decode("cp1252"))


def fmt_currency(val) -> str:
    """Format a numeric value as MXN currency string.

    Args:
        val: The value.

    Returns:
        str: ``$12,345 MXN`` or the value as text.
    """
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return f"${val:,.0f} MXN"
    return str(val) if val else "—"


def fmt_val(val) -> str:
    """Format any value for display.

    Args:
        val: The value.

    Returns:
        str: The display text.
    """
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "Sí" if val else "No"
    return str(val)


def _hex(color: colors.Color) -> str:
    """``#RRGGBB`` for a colour, for use inside paragraph markup.

    Args:
        color: The colour.

    Returns:
        str: The hex string.
    """
    return "#" + color.hexval()[2:]


def _span(
    text: Any,
    bold: bool = False,
    color: colors.Color = DARK_GRAY,
    size: float | None = None,
    italic: bool = False,
) -> str:
    """One run of text, as paragraph markup.

    Args:
        text: The text; escaped here.
        bold: Bold.
        color: Font colour.
        size: Font size in points; the paragraph's when not given.
        italic: Italic.

    Returns:
        str: The markup.
    """
    size_attr = f' size="{size}"' if size else ""
    body = pdf_text(text)
    if bold:
        body = f"<b>{body}</b>"
    if italic:
        body = f"<i>{body}</i>"
    return f'<font color="{_hex(color)}"{size_attr}>{body}</font>'


class ReportBuilder:
    """The handful of layout calls the report is written in.

    Each method stands in for the ``python-docx`` call the handover made at the
    same place, and collects ReportLab flowables to be laid out at the end.
    """

    def __init__(self) -> None:
        """Start an empty story."""
        self.story: list[Flowable] = []

    def paragraph(
        self,
        text: Any,
        bold: bool = False,
        color: colors.Color = DARK_GRAY,
        size: float = 11,
        alignment: Alignment = TA_LEFT,
        space_after: float = 6,
    ) -> None:
        """Add a paragraph with explicit formatting.

        Args:
            text: The text.
            bold: Bold.
            color: Font colour.
            size: Font size in points.
            alignment: Paragraph alignment.
            space_after: Points after.
        """
        if not str(text).strip():
            self.story.append(Spacer(1, size))
            return
        style = ParagraphStyle(
            "p",
            fontName=FONT_BOLD if bold else FONT,
            fontSize=size,
            leading=size * 1.3,
            textColor=color,
            alignment=alignment,
            spaceAfter=space_after,
        )
        self.story.append(Paragraph(pdf_text(text), style))

    def rich(self, spans: list[str], size: float = 10, space_after: float = 4, alignment: Alignment = TA_LEFT) -> None:
        """Add a paragraph built from several differently formatted runs.

        Args:
            spans: Markup from :func:`_span`.
            size: Base font size.
            space_after: Points after.
            alignment: Paragraph alignment.
        """
        style = ParagraphStyle(
            "rich",
            fontName=FONT,
            fontSize=size,
            leading=size * 1.3,
            textColor=DARK_GRAY,
            spaceAfter=space_after,
            alignment=alignment,
        )
        self.story.append(Paragraph("".join(spans), style))

    def heading(self, text: str, level: int = 1) -> None:
        """Add heading with brand colors.

        Args:
            text: The heading.
            level: Heading level.
        """
        size = {1: 16, 2: 13}.get(level, 11)
        style = ParagraphStyle(
            f"h{level}",
            fontName=FONT_BOLD,
            fontSize=size,
            leading=size * 1.25,
            textColor=DEEP_BLUE if level <= 2 else TEAL,
            spaceBefore=10 if level == 1 else 6,
            spaceAfter=6,
            keepWithNext=True,
        )
        self.story.append(Paragraph(pdf_text(text), style))

    def bullet(self, text: Any, size: float = 10, numbered: int | None = None) -> None:
        """Add one bullet or numbered item.

        Args:
            text: The item.
            size: Font size.
            numbered: The item's number, for a numbered list.
        """
        style = ParagraphStyle(
            "li",
            fontName=FONT,
            fontSize=size,
            leading=size * 1.3,
            textColor=DARK_GRAY,
            leftIndent=14,
            bulletIndent=2,
            spaceAfter=2,
        )
        marker = f"{numbered}." if numbered is not None else "•"
        self.story.append(Paragraph(pdf_text(text), style, bulletText=marker))

    def table(self, headers: list[str], rows: list[list[Any]], col_widths: list[float] | None = None) -> None:
        """Create a branded table.

        Args:
            headers: Column headers.
            rows: Row values.
            col_widths: Column widths in centimetres.
        """
        many_columns = len(headers) > 5
        size = 8 if many_columns else 9.5
        header_style = ParagraphStyle("th", fontName=FONT_BOLD, fontSize=size, leading=size * 1.25, textColor=WHITE)
        cell_style = ParagraphStyle("td", fontName=FONT, fontSize=size, leading=size * 1.25, textColor=DARK_GRAY)

        data = [[Paragraph(pdf_text(header), header_style) for header in headers]]
        data.extend([Paragraph(pdf_text(cell), cell_style) for cell in row] for row in rows)

        widths = [width * cm for width in col_widths] if col_widths else None
        table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
        commands: list[tuple[Any, ...]] = [
            ("BACKGROUND", (0, 0), (-1, 0), DEEP_BLUE),
            ("GRID", (0, 0), (-1, -1), 0.5, GRID_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        # The handover shaded every second data row.
        for r_idx in range(len(rows)):
            if r_idx % 2 == 1:
                commands.append(("BACKGROUND", (0, r_idx + 1), (-1, r_idx + 1), LIGHT_GRAY))
        table.setStyle(TableStyle(commands))
        self.story.append(table)
        self.story.append(Spacer(1, 4))

    def rule(self) -> None:
        """Add a horizontal rule."""
        self.story.append(HRFlowable(width="100%", thickness=0.6, color=DARK_GRAY, spaceBefore=4, spaceAfter=4))

    def page_break(self) -> None:
        """Start a new page."""
        self.story.append(PageBreak())

    def render(self, title: str) -> bytes:
        """Lay the story out on A4 pages.

        Args:
            title: The PDF's document title.

        Returns:
            bytes: The PDF.
        """
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN,
            title=title,
            author=branding.ORGANIZATION,
            creator=branding.PRODUCT_NAME,
        )
        document.build(list(self.story), onFirstPage=_footer, onLaterPages=_footer)
        return buffer.getvalue()


def _footer(canvas, document) -> None:
    """The page number and confidentiality mark at the foot of every page.

    Args:
        canvas: The page canvas.
        document: The document being built.
    """
    canvas.saveState()
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(DARK_GRAY)
    canvas.drawString(MARGIN, MARGIN / 2, f"{branding.PRODUCT_NAME} · Confidencial")
    canvas.drawRightString(A4[0] - MARGIN, MARGIN / 2, f"Página {document.page}")
    canvas.restoreState()


def _alert_color(text: str) -> colors.Color:
    """The handover's alert colour, read from the emoji the alert starts with.

    Args:
        text: The alert.

    Returns:
        Color: Red, amber or green.
    """
    if text.startswith(("🚨", "🔴")):
        return RED
    if text.startswith(("⚠️", "⚠", "🟡")):
        return AMBER
    return GREEN


def _placeholder_spans(line: str, size: float = 11) -> list[str]:
    """A letter line with its ``[PLACEHOLDERS]`` highlighted in teal.

    Args:
        line: One line of the letter.
        size: Font size.

    Returns:
        list[str]: The runs.
    """
    parts = line.split("[")
    if len(parts) == 1:
        return [_span(line, size=size)]
    spans = [_span(parts[0], size=size)] if parts[0] else []
    for part in parts[1:]:
        if "]" in part:
            placeholder, rest = part.split("]", 1)
            spans.append(_span(f"[{placeholder}]", bold=True, color=TEAL, size=size))
            if rest:
                spans.append(_span(rest, size=size))
        else:
            spans.append(_span(f"[{part}", size=size))
    return spans


# ── Document builder ──────────────────────────────────────────────────────


def build_report(summary: dict[str, Any], generated_at: datetime | None = None) -> ReportBuilder:
    """Build the full coordinator report.

    Args:
        summary: The pipeline summary.
        generated_at: The date printed on the cover; now when not given.

    Returns:
        ReportBuilder: The report, ready to render.
    """
    doc = ReportBuilder()

    run_id = summary.get("run_id", "unknown")
    patient_id = summary.get("patient_id", "PAC-XXXX-XXXX")
    carrier = summary.get("carrier", "Unknown")
    urgency = str(summary.get("urgency_level") or "medium")
    plan = _dict(summary.get("action_plan"))
    alerts = _list(summary.get("carrier_alerts"))
    docs_checklist = _dict(summary.get("docs_checklist"))
    deadlines = _dict(summary.get("deadlines"))
    cost = _dict(summary.get("cost_projection"))
    appeal = plan.get("appeal_pathway")
    notification = summary.get("notification_letter")
    policy_extraction = _dict(summary.get("policy_extraction"))
    fin_roadmap = _dict(summary.get("financial_roadmap"))
    adherence_data = _dict(summary.get("adherence"))

    # ── COVER PAGE ────────────────────────────────────────────────────
    doc.paragraph(branding.PRODUCT_NAME, bold=True, color=DEEP_BLUE, size=28, alignment=TA_CENTER, space_after=10)
    doc.paragraph(
        "Reporte de Navegación de Cobertura", bold=True, color=DEEP_BLUE, size=18, alignment=TA_CENTER, space_after=12
    )
    doc.paragraph(branding.TAGLINE or branding.ORGANIZATION, color=TEAL, size=14, alignment=TA_CENTER, space_after=24)

    # Cover metadata table
    cover_rows = [
        ["Paciente (ID)", patient_id],
        ["Aseguradora", carrier],
        ["Nivel de Urgencia", urgency.upper()],
        ["Run ID", run_id],
        ["Fecha de generación", (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")],
    ]
    doc.table(["Campo", "Valor"], cover_rows, col_widths=[6, 10])

    doc.paragraph("", size=6)
    doc.paragraph(
        "CONFIDENCIAL — Documento para uso exclusivo del coordinador PSP. No contiene datos personales del paciente.",
        bold=True,
        color=RED,
        size=10,
        alignment=TA_CENTER,
    )

    doc.page_break()

    # ── 1. RESUMEN EJECUTIVO ──────────────────────────────────────────
    doc.heading("1. Resumen Ejecutivo", level=1)
    doc.paragraph(f"URGENCIA: {urgency.upper()}", bold=True, color=URGENCY_COLORS.get(urgency, TEAL), size=14)
    doc.paragraph(str(plan.get("summary") or "Sin resumen disponible."), size=11, space_after=12)

    # ── 2. EXTRACCIÓN DE PÓLIZA (Agent 1) ────────────────────────────
    if policy_extraction:
        doc.heading("2. Extracción de Póliza (Agent 1 — Parser)", level=1)

        meta = _dict(policy_extraction.get("meta"))
        confidence = meta.get("confidence_score", 0)
        confidence_pct = (
            f"{confidence:.0%}"
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else str(confidence)
        )

        # Meta summary
        meta_rows = [
            ["Aseguradora", fmt_val(meta.get("carrier"))],
            ["Tipo de póliza", fmt_val(meta.get("policy_type"))],
            ["Confianza de extracción", confidence_pct],
            ["Fecha de extracción", fmt_val(meta.get("extraction_date"))],
        ]
        doc.table(["Campo", "Valor"], meta_rows, col_widths=[7, 9])

        # Financial fields
        fin = _dict(policy_extraction.get("financial"))
        if any(v is not None for v in fin.values()):
            doc.heading("Datos Financieros", level=3)
            fin_rows = [
                ["Deducible", fmt_val(fin.get("deducible_amount"))],
                ["Tipo de deducible", fmt_val(fin.get("deducible_type"))],
                ["Coaseguro (%)", fmt_val(fin.get("coaseguro_pct"))],
                ["Tope de coaseguro", fmt_val(fin.get("tope_coaseguro"))],
                ["Suma asegurada", fmt_val(fin.get("suma_asegurada"))],
                ["Moneda", fmt_val(fin.get("moneda"))],
                ["Periodo de póliza", fmt_val(fin.get("periodo_poliza"))],
            ]
            doc.table(["Campo", "Valor extraído"], fin_rows, col_widths=[7, 9])

        # Coverage fields
        cov = _dict(policy_extraction.get("coverage"))
        if any(v is not None for v in cov.values()):
            doc.heading("Cobertura", level=3)
            cov_rows = [
                ["Biológicos cubiertos", fmt_val(cov.get("biologics_covered"))],
                ["Meds especialidad cubiertos", fmt_val(cov.get("specialty_meds_covered"))],
                ["Pago directo disponible", fmt_val(cov.get("pago_directo_available"))],
                ["Pago directo medicamentos", fmt_val(cov.get("pago_directo_meds"))],
                ["Coaseguro meds ambulatorio", fmt_val(cov.get("coaseguro_meds_outpatient"))],
                ["Programación requerida", fmt_val(cov.get("programacion_required"))],
                ["Red requerida", fmt_val(cov.get("network_required"))],
            ]
            doc.table(["Campo", "Valor extraído"], cov_rows, col_widths=[7, 9])

        # Preexisting
        pre = _dict(policy_extraction.get("preexisting"))
        if any(v is not None for v in pre.values()):
            doc.heading("Padecimientos Preexistentes", level=3)
            pre_rows = [
                ["Excluidos", fmt_val(pre.get("excluded"))],
                ["Vía de cobertura", fmt_val(pre.get("pathway_to_coverage"))],
                ["Cobertura después de (meses)", fmt_val(pre.get("coverage_after_months"))],
                ["Rider opcional disponible", fmt_val(pre.get("optional_rider_available"))],
                ["Regla de 30 días", fmt_val(pre.get("thirty_day_rule"))],
            ]
            doc.table(["Campo", "Valor extraído"], pre_rows, col_widths=[7, 9])

        # Dermatology
        derm = _dict(policy_extraction.get("dermatology"))
        if any(v is not None for v in derm.values() if not isinstance(v, list)):
            doc.heading("Dermatología", level=3)
            derm_rows = [
                ["Productos derm excluidos", fmt_val(derm.get("derm_products_excluded"))],
                ["Biológicos excluidos", fmt_val(derm.get("biologics_excluded"))],
                ["Cosméticos excluidos", fmt_val(derm.get("cosmetic_excluded"))],
                ["Lesiones piel → 2a valoración", fmt_val(derm.get("skin_lesions_segunda_val"))],
                ["Acné excluido", fmt_val(derm.get("acne_excluded"))],
            ]
            doc.table(["Campo", "Valor extraído"], derm_rows, col_widths=[7, 9])

        # Appeals
        app_section = _dict(policy_extraction.get("appeals"))
        if any(v is not None for v in app_section.values()):
            doc.heading("Apelaciones y Recursos", level=3)
            app_rows = [
                ["Plazo notificación (días)", fmt_val(app_section.get("notification_deadline_days"))],
                ["Tipo de notificación", fmt_val(app_section.get("notification_type"))],
                ["Recurso preexistentes", fmt_val(app_section.get("preexisting_appeal_type"))],
                ["Cuerpo de arbitraje", fmt_val(app_section.get("arbitration_body"))],
                ["UNE suspende prescripción", fmt_val(app_section.get("une_suspends_statute"))],
                ["CONDUSEF disponible", fmt_val(app_section.get("condusef_available"))],
                ["Plazo liquidación (días)", fmt_val(app_section.get("settlement_days"))],
            ]
            doc.table(["Campo", "Valor extraído"], app_rows, col_widths=[7, 9])

        # Flags from parser
        flags = _list(policy_extraction.get("_flags"))
        if flags:
            doc.heading("Banderas de Extracción", level=3)
            for flag in flags:
                doc.paragraph(f"⚑ {flag}", color=AMBER, size=10, space_after=3)

    doc.page_break()

    # ── 3. ALERTAS DE ASEGURADORA ─────────────────────────────────────
    doc.heading("3. Alertas de Aseguradora", level=1)

    for alert in alerts:
        text = str(alert)
        doc.paragraph(text, color=_alert_color(text), size=10, space_after=4)

    # ── 4. FECHAS LÍMITE ──────────────────────────────────────────────
    doc.heading("4. Fechas Límite", level=1)

    deadline_rows = []
    deadline_labels = {
        "notification": "Notificación de siniestro",
        "preauth_submit": "Envío de preautorización",
        "first_dose_earliest": "Primera dosis (más temprano)",
    }
    for key, label in deadline_labels.items():
        deadline_rows.append([label, fmt_val(deadlines.get(key))])
    doc.table(["Concepto", "Fecha"], deadline_rows, col_widths=[8, 8])

    # ── 5. PLAN DE ACCIÓN ─────────────────────────────────────────────
    doc.page_break()
    doc.heading("5. Plan de Acción (Agent 2 — Planner)", level=1)

    owner_labels = {
        "psp_coordinator": "Coordinador PSP",
        "doctor": "Médico tratante",
        "patient": "Paciente",
    }
    for step in _list(plan.get("steps")):
        step = _dict(step)
        doc.heading(f"Paso {step.get('step', '')}: {step.get('title', '')}", level=2)

        doc.paragraph(str(step.get("action", "")), size=11)

        meta_parts = []
        if step.get("deadline"):
            meta_parts.append(f"Fecha límite: {step['deadline']}")
        if step.get("owner"):
            meta_parts.append(f"Responsable: {owner_labels.get(step['owner'], step['owner'])}")
        if meta_parts:
            doc.paragraph(" | ".join(meta_parts), bold=True, color=TEAL, size=10)

        # Docs needed for this step
        docs_needed = _list(step.get("docs_needed"))
        if docs_needed:
            doc.paragraph("Documentos requeridos:", bold=True, size=10, space_after=2)
            for d in docs_needed:
                doc.bullet(d, size=10)

        # Carrier-specific note
        note = step.get("carrier_specific_note", "")
        if note:
            doc.rich([_span(f"Nota {carrier}: ", bold=True, color=DEEP_BLUE), _span(note)])

    # ── 6. CHECKLIST DE DOCUMENTACIÓN ─────────────────────────────────
    doc.page_break()
    doc.heading("6. Checklist de Documentación", level=1)

    checklist_sections = {
        "clinical": "Documentos Clínicos",
        "insurance": "Documentos de Seguro",
        "carrier_specific": f"Documentos Específicos {carrier}",
    }
    for key, title in checklist_sections.items():
        items = _list(docs_checklist.get(key))
        if not items:
            continue
        doc.heading(title, level=3)
        for item in items:
            doc.bullet(f"[ ]  {item}", size=10)

    # ── 7. PROYECCIÓN DE COSTOS ───────────────────────────────────────
    doc.heading("7. Proyección de Costos (Agent 2)", level=1)

    cost_rows = [
        ["Deducible", fmt_val(cost.get("deducible"))],
        ["Coaseguro (%)", fmt_val(cost.get("coaseguro_pct"))],
        ["Tope de coaseguro", fmt_val(cost.get("tope_coaseguro"))],
        ["Costo mensual medicamento (est.)", fmt_currency(cost.get("monthly_drug_cost_estimate_mxn"))],
        ["Costo mensual paciente (est.)", fmt_currency(cost.get("patient_monthly_estimate_mxn"))],
    ]
    doc.table(["Concepto", "Valor"], cost_rows, col_widths=[7, 9])

    tip = cost.get("optimization_tip", "")
    if tip:
        doc.rich([_span("Tip de optimización: ", bold=True, color=GREEN), _span(tip)])

    # ── 8. ROADMAP FINANCIERO 12 MESES (Agent 4) ─────────────────────
    fin_sum = _dict(fin_roadmap.get("financial_summary"))
    if fin_sum:
        doc.page_break()
        doc.heading("8. Roadmap Financiero — 12 Meses (Agent 4 — Optimizer)", level=1)

        tope_m = fin_sum.get("tope_reached_month")
        free_months = fin_sum.get("months_remaining_free", 0)
        annual_savings = fin_sum.get("savings_from_optimization_mxn", 0)

        roadmap_rows = [
            ["Costo anual del medicamento", fmt_currency(fin_sum.get("drug_cost_annual_mxn", 0))],
            ["Costo anual del paciente (optimizado)", fmt_currency(fin_sum.get("patient_cost_annual_mxn", 0))],
            ["Costo sin optimización", fmt_currency(fin_sum.get("cost_without_optimization_mxn", 0))],
            ["Ahorro por optimización", fmt_currency(annual_savings)],
            ["Costo que absorbe la aseguradora", fmt_currency(fin_sum.get("carrier_cost_annual_mxn", 0))],
            ["Tope de coaseguro alcanzado", f"Mes {tope_m}" if tope_m else "No alcanzado en 12 meses"],
            ["Meses restantes sin costo", f"{free_months} meses" if free_months else "—"],
        ]
        doc.table(["Concepto", "Valor"], roadmap_rows, col_widths=[8, 8])

        # ── 8a. Monthly projections table ─────────────────────────────
        monthly = _list(fin_roadmap.get("monthly_projections"))
        if monthly:
            doc.heading("Proyección Mensual Detallada", level=2)

            monthly_rows = []
            for m in monthly:
                m = _dict(m)
                monthly_rows.append(
                    [
                        str(m.get("month", "")),
                        m.get("date", ""),
                        str(m.get("doses", "")),
                        fmt_currency(m.get("drug_cost_mxn")),
                        fmt_currency(m.get("deducible_mxn")),
                        fmt_currency(m.get("coaseguro_mxn")),
                        fmt_currency(m.get("patient_pays_mxn")),
                        "Sí" if m.get("tope_reached") else "No",
                    ]
                )
            doc.table(
                ["Mes", "Fecha", "Dosis", "Costo med.", "Deducible", "Coaseguro", "Paciente paga", "Tope?"],
                monthly_rows,
                col_widths=[1.2, 2.1, 1.3, 2.6, 2.5, 2.5, 2.6, 1.4],
            )

        # ── 8b. All optimization tips ─────────────────────────────────
        opt_tips = _list(fin_roadmap.get("optimization_tips"))
        if opt_tips:
            doc.heading("Tips de Optimización", level=2)
            for tip_item in opt_tips:
                if not isinstance(tip_item, dict):
                    continue
                title = tip_item.get("title", "")
                action = tip_item.get("action", "")
                sav = tip_item.get("savings_estimate_mxn")
                owner = tip_item.get("owner", "")
                timing = tip_item.get("timing", "")
                risk = tip_item.get("risk_if_ignored", "")

                doc.paragraph(title, bold=True, color=GREEN, size=11, space_after=2)
                doc.paragraph(str(action), size=10, space_after=2)

                meta_line = []
                if owner:
                    owner_map = {"coordinator": "Coordinador PSP", "doctor": "Médico", "patient": "Paciente"}
                    meta_line.append(f"Responsable: {owner_map.get(owner, owner)}")
                if timing:
                    meta_line.append(f"Timing: {timing}")
                if sav:
                    meta_line.append(f"Ahorro est: {fmt_currency(sav)}")
                if meta_line:
                    doc.paragraph(" | ".join(meta_line), bold=True, color=TEAL, size=9, space_after=2)

                if risk:
                    doc.rich([_span("Riesgo si se ignora: ", bold=True, color=RED), _span(risk)], size=9)

                doc.paragraph("", size=2)

        # ── 8c. Renewal projection ────────────────────────────────────
        renewal = _dict(fin_roadmap.get("renewal_projection"))
        if renewal:
            doc.heading("Proyección de Renovación", level=2)

            renewal_rows = []
            if renewal.get("premium_increase_estimate_pct"):
                renewal_rows.append(["Aumento de prima estimado", f"{renewal['premium_increase_estimate_pct']}%"])
            if renewal.get("stay_vs_switch_recommendation"):
                renewal_rows.append(["Recomendación", renewal["stay_vs_switch_recommendation"]])
            if renewal.get("continuity_risk"):
                renewal_rows.append(["Riesgo de continuidad", renewal["continuity_risk"]])
            if renewal.get("optimal_renewal_action"):
                renewal_rows.append(["Acción óptima de renovación", renewal["optimal_renewal_action"]])
            if renewal_rows:
                doc.table(["Concepto", "Detalle"], renewal_rows, col_widths=[5, 11])

            # Negotiation tactics
            tactics = _list(renewal.get("negotiation_tactics"))
            if tactics:
                doc.heading("Tácticas de Negociación", level=3)
                for tactic in tactics:
                    doc.bullet(tactic, size=10)

    # ── 9. ADHERENCIA Y MONITOREO (Agent 5) ──────────────────────────
    if adherence_data:
        doc.page_break()
        doc.heading("9. Adherencia y Monitoreo (Agent 5 — Monitor)", level=1)

        adh_score = adherence_data.get("adherence_score", "N/A")
        n_doses_12 = adherence_data.get("total_doses_12_months", "—")
        n_monitoring = adherence_data.get("total_monitoring_events", "—")
        active_alerts = adherence_data.get("active_alerts", [])
        n_active = len(active_alerts) if isinstance(active_alerts, list) else active_alerts

        adh_rows = [
            ["Score de adherencia", f"{adh_score}/100"],
            ["Dosis programadas (12 meses)", str(n_doses_12)],
            ["Eventos de monitoreo", str(n_monitoring)],
            ["Alertas activas", str(n_active)],
        ]
        doc.table(["Métrica", "Valor"], adh_rows, col_widths=[8, 8])

        # Most urgent action
        most_urgent = adherence_data.get("most_urgent")
        if isinstance(most_urgent, dict) and most_urgent.get("action"):
            spans = [
                _span("Acción más urgente: ", bold=True, color=RED, size=11),
                _span(f"{most_urgent.get('title', '')} — {most_urgent.get('action', '')}"),
            ]
            if most_urgent.get("deadline"):
                spans.append(_span(f" (fecha límite: {most_urgent['deadline']})", bold=True, color=RED))
            doc.rich(spans)

        # ── 9a. Dose calendar table ──────────────────────────────────
        dose_cal = _list(adherence_data.get("dose_calendar"))
        if dose_cal:
            doc.heading("Calendario de Dosis", level=2)

            dose_rows = []
            for d in dose_cal:
                d = _dict(d)
                dose_rows.append(
                    [
                        str(d.get("dose_number", "")),
                        d.get("scheduled_date", ""),
                        str(d.get("type", "")).capitalize(),
                        str(d.get("status", "")).capitalize(),
                        d.get("refill_order_by", ""),
                    ]
                )
            doc.table(
                ["#", "Fecha programada", "Tipo", "Estado", "Ordenar refill antes de"],
                dose_rows,
                col_widths=[1, 3.5, 3, 3, 4],
            )

        owner_names = {"doctor": "Médico", "patient": "Paciente", "coordinator": "Coordinador"}

        # ── 9b. Monitoring calendar table ─────────────────────────────
        mon_cal = _list(adherence_data.get("monitoring_calendar"))
        if mon_cal:
            doc.heading("Calendario de Monitoreo", level=2)

            mon_rows = []
            for m in mon_cal:
                m = _dict(m)
                mon_rows.append(
                    [
                        m.get("scheduled_date", ""),
                        m.get("title", ""),
                        m.get("event", ""),
                        owner_names.get(m.get("owner", ""), m.get("owner", "")),
                        # The handover printed a warning emoji here.
                        "Sí" if m.get("critical") else "",
                    ]
                )
            doc.table(
                ["Fecha", "Descripción", "Tipo", "Responsable", "Crítico"],
                mon_rows,
                col_widths=[2.5, 5.5, 2.5, 2.5, 1.5],
            )

        # ── 9c. Reauthorization docs ─────────────────────────────────
        reauth_docs = _list(adherence_data.get("reauth_docs_required"))
        if reauth_docs:
            doc.heading("Documentos para Reautorización", level=2)

            reauth_rows = []
            for rd in reauth_docs:
                rd = _dict(rd)
                reauth_rows.append(
                    [
                        rd.get("doc", ""),
                        f"{rd.get('max_age_months', '—')} meses",
                        owner_names.get(rd.get("owner", ""), rd.get("owner", "")),
                        "Sí" if rd.get("critical") else "No",
                    ]
                )
            doc.table(
                ["Documento", "Antigüedad máx.", "Responsable", "Crítico"],
                reauth_rows,
                col_widths=[6, 3, 3, 2.5],
            )

        # Continuity risk
        cont_risk = adherence_data.get("continuity_risk")
        if isinstance(cont_risk, dict):
            risk_level = str(cont_risk.get("risk_level", "unknown"))
            risk_color = {"critical": RED, "high": RED, "medium": AMBER, "low": GREEN}.get(risk_level, DARK_GRAY)
            doc.paragraph(f"Riesgo de continuidad: {risk_level.upper()}", bold=True, color=risk_color, size=11)
            for rf in _list(cont_risk.get("risk_factors")):
                doc.bullet(rf, size=10)
            mitigation = _list(cont_risk.get("mitigation_actions"))
            if mitigation:
                doc.paragraph("Acciones de mitigación:", bold=True, color=GREEN, size=10, space_after=2)
                for ma in mitigation:
                    doc.bullet(ma, size=10)

        # Adherence plan recommendations
        adh_plan = _dict(adherence_data.get("adherence_plan"))
        tips = _list(adh_plan.get("patient_engagement_tips"))
        if tips:
            doc.heading("Recomendaciones de Adherencia", level=2)
            for t in tips:
                doc.bullet(t, size=10)

    # ── 10. VÍA DE APELACIÓN ─────────────────────────────────────────
    if isinstance(appeal, dict) and appeal:
        doc.page_break()
        doc.heading("10. Vía de Apelación (Agent 3 — Advocate)", level=1)

        trigger = appeal.get("trigger", "")
        if trigger:
            doc.rich([_span("Activación: ", bold=True, color=DEEP_BLUE, size=11), _span(trigger, size=11)], size=11)

        appeal_steps = []
        for i in range(1, 6):
            step_key = f"step_{i}"
            if step_key in appeal:
                s = _dict(appeal[step_key])
                deadline_val = (
                    s.get("deadline_from_denial")
                    or s.get("deadline_from_une_response")
                    or s.get("deadline_from_condusef")
                    or s.get("deadline_relative", "—")
                )
                appeal_steps.append([f"Paso {i}", s.get("action", ""), deadline_val])
        if appeal_steps:
            doc.table(["Paso", "Acción", "Plazo"], appeal_steps, col_widths=[2, 10, 4])

        # Key arguments
        key_args = _list(appeal.get("key_arguments"))
        if key_args:
            doc.heading("Argumentos Clave", level=3)
            for arg in key_args:
                doc.bullet(arg, size=10)

        timeline = appeal.get("estimated_resolution_timeline", "")
        if timeline:
            doc.rich([_span("Tiempos estimados: ", bold=True, color=TEAL), _span(timeline)])

    # ── 11. CARTA DE NOTIFICACIÓN ─────────────────────────────────────
    if notification:
        doc.page_break()
        doc.heading("11. Carta de Notificación de Siniestro", level=1)

        doc.paragraph(
            "INSTRUCCIONES: Imprima esta carta, complete los campos entre "
            "corchetes con los datos reales del paciente, firme y envíe a "
            "la aseguradora. NO modifique el texto legal.",
            bold=True,
            color=RED,
            size=10,
        )

        # Add letter text preserving line breaks
        for line in str(notification).split("\n"):
            if line.strip() == "---":
                doc.rule()
            elif not line.strip():
                doc.paragraph("", size=6)
            elif line.startswith("[") and line.endswith("]"):
                doc.paragraph(line, bold=True, color=TEAL, size=11, space_after=2)
            else:
                doc.rich(_placeholder_spans(line), size=11, space_after=2)

    # ── FOOTER / PRIVACY ──────────────────────────────────────────────
    doc.page_break()
    doc.paragraph("", size=12)
    doc.paragraph(branding.generated_by(), bold=True, color=DEEP_BLUE, size=14, alignment=TA_CENTER)
    if branding.TAGLINE:
        doc.paragraph(branding.TAGLINE, color=TEAL, size=12, alignment=TA_CENTER, space_after=24)

    privacy_lines = [
        f"Este documento fue generado por {branding.PRODUCT_NAME} de {branding.ORGANIZATION}.",
        "Datos procesados bajo pseudonimización conforme a LFPDPPP.",
        "No contiene datos personales identificables del paciente.",
        f"El mapeo {patient_id} ↔ datos reales se mantiene exclusivamente en el CRM del coordinador.",
        "",
    ]
    if branding.PRIVACY_NOTICE_URL:
        privacy_lines.append(f"Aviso de Privacidad: {branding.PRIVACY_NOTICE_URL}")
    if branding.ARCO_EMAIL:
        privacy_lines.append(f"Derechos ARCO: {branding.ARCO_EMAIL}")
    if branding.CONTACT_EMAIL:
        privacy_lines.append(f"Contacto: {branding.CONTACT_EMAIL}")
    for line in privacy_lines:
        doc.paragraph(line, size=9, color=DARK_GRAY, alignment=TA_CENTER, space_after=2)

    return doc


def report_filename(summary: dict[str, Any]) -> str:
    """``InnovaDerm-PAC-2026-0001-MetLife-20260522_131650.pdf``.

    Args:
        summary: The pipeline summary.

    Returns:
        str: The file name, safe for a Content-Disposition header.
    """
    patient_id = safe_filename_part(summary.get("patient_id", "PAC-XXXX"))
    carrier = safe_filename_part(summary.get("carrier", "Unknown"))
    run_id = safe_filename_part(summary.get("run_id", datetime.now().strftime("%Y%m%d")))
    return f"{branding.FILE_PREFIX}-{patient_id}-{carrier}-{run_id}.pdf"


def safe_filename_part(value: Any) -> str:
    """Keep a file-name part to letters, digits, dash and underscore.

    Args:
        value: The part.

    Returns:
        str: The safe part.
    """
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value)) or "x"


def render_report(summary: dict[str, Any], generated_at: datetime | None = None) -> bytes:
    """The coordinator report as PDF bytes, built in memory.

    Args:
        summary: The pipeline summary.
        generated_at: The date printed on the cover.

    Returns:
        bytes: The document.
    """
    title = f"{branding.PRODUCT_NAME} — {summary.get('patient_id', 'PAC-XXXX')}"
    return build_report(summary, generated_at).render(title)
