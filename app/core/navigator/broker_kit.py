"""InnovaDerm Navigator — Broker Handoff Kit.

Ported from the handover's ``scripts/export_broker_kit.py``. The same per-patient
package for the insurance broker, with the same file names — PDF where the
handover wrote DOCX:

  • ``<patient>_cover_sheet.pdf`` — what the broker needs to do, and by when
  • the coordinator PDF report
  • ``notification_letter.txt`` — the letter, with placeholders
  • ``README.txt``

The handover found these files in a batch directory and zipped them to
``outputs/broker-kits/``. Here they are built from the stored summary and zipped
in memory when the kit is downloaded.
"""

import zipfile
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib.enums import TA_CENTER

from app.core.navigator import branding
from app.core.navigator.report import (
    DARK_GRAY,
    DEEP_BLUE,
    RED,
    TEAL,
    ReportBuilder,
    _span,
    render_report,
    report_filename,
    safe_filename_part,
)


def build_cover_sheet(patient_id: str, data: dict[str, Any]) -> bytes:
    """Generate cover_sheet.pdf — what the broker needs to act on.

    Args:
        patient_id: The patient id.
        data: The pipeline summary.

    Returns:
        bytes: The PDF.
    """
    doc = ReportBuilder()

    # Title
    doc.paragraph("Hoja de Entrega al Broker", bold=True, color=DEEP_BLUE, size=20, alignment=TA_CENTER)
    doc.rich(
        [_span(f"{branding.PRODUCT_NAME} · {branding.ORGANIZATION}", color=TEAL, size=11, italic=True)],
        size=11,
        space_after=14,
        alignment=TA_CENTER,
    )

    # Patient block
    urg = str(data.get("urgency_level") or "—").upper()
    doc.rich([_span("Paciente (pseudonimizado): ", bold=True), _span(patient_id)], size=11)
    doc.rich([_span("Aseguradora: ", bold=True), _span(data.get("carrier") or "—")], size=11)
    doc.rich(
        [
            _span("Urgencia: ", bold=True),
            _span(urg, bold=urg == "CRITICAL", color=RED if urg == "CRITICAL" else DARK_GRAY),
        ],
        size=11,
        space_after=10,
    )

    # Key dates
    doc.paragraph("Fechas críticas", bold=True, color=DEEP_BLUE, size=14)
    raw_deadlines = data.get("deadlines")
    deadlines: dict[str, Any] = raw_deadlines if isinstance(raw_deadlines, dict) else {}
    for label, key in [
        ("Notificación de siniestro", "notification"),
        ("Solicitud de preautorización", "preauth_submit"),
        ("Primera dosis estimada", "first_dose_earliest"),
    ]:
        doc.bullet(f"{label}: {deadlines.get(key) or 'ver plan completo'}", size=11)

    doc.paragraph("", size=8)

    # Broker actions
    doc.paragraph("Lo que necesita hacer el broker", bold=True, color=DEEP_BLUE, size=14)

    actions = [
        "Insertar nombre completo del paciente, número de póliza y fecha de nacimiento "
        "en los placeholders del archivo notification_letter.txt antes de enviarla a la aseguradora.",
        "Enviar la notificación de siniestro por escrito con acuse de recibo a la aseguradora ANTES "
        "de la fecha de notificación arriba indicada.",
        "Revisar el reporte coordinador (PDF) — secciones 5 (Plan de Acción), 6 (Checklist) y 10 "
        "(Vía de apelación) — y ejecutar los pasos en orden.",
        f"Cualquier negativa por escrito de la aseguradora debe llegar al coordinador {branding.ORGANIZATION} "
        "dentro de 24 hrs para activar Agente 3 (Advocate) y generar carta de apelación.",
        "Confirmar al coordinador la entrega de cada paso completado (notificación, preauth, primera dosis).",
    ]
    for number, action in enumerate(actions, start=1):
        doc.bullet(action, size=11, numbered=number)

    # Carrier alerts
    alerts = data.get("carrier_alerts") if isinstance(data.get("carrier_alerts"), list) else []
    if alerts:
        doc.paragraph("", size=8)
        doc.paragraph("Alertas específicas de la aseguradora", bold=True, color=DEEP_BLUE, size=14)
        for alert in alerts[:5]:
            doc.bullet(alert, size=11)

    # Footer
    doc.paragraph("", size=12)
    footer_text = (
        f"{branding.PRODUCT_NAME} · {branding.ORGANIZATION} · Confidencial · LFPDPPP\n"
        "El identificador del paciente corresponde al paciente en el CRM del coordinador. "
        "No incluir nombres reales en sistemas de IA."
    )
    if branding.PRIVACY_NOTICE_URL:
        footer_text += f" Aviso de Privacidad: {branding.PRIVACY_NOTICE_URL}"
    for line in footer_text.split("\n"):
        doc.rich([_span(line, size=8, italic=True)], size=8, space_after=1, alignment=TA_CENTER)

    return doc.render(f"Hoja de Entrega al Broker — {patient_id}")


def broker_kit_filename(summary: dict[str, Any], today: datetime | None = None) -> str:
    """``PAC-2026-0042_broker_kit_2026-06-15.zip``.

    Args:
        summary: The pipeline summary.
        today: The download date.

    Returns:
        str: The file name.
    """
    return f"{safe_filename_part(summary.get('patient_id', 'PAC-XXXX'))}_broker_kit_{(today or datetime.now()):%Y-%m-%d}.zip"


def build_broker_kit(summary: dict[str, Any], generated_at: datetime | None = None) -> bytes:
    """The broker kit ZIP, built in memory.

    Args:
        summary: The pipeline summary.
        generated_at: The date printed on the report cover.

    Returns:
        bytes: The ZIP.
    """
    patient_id = str(summary.get("patient_id", "PAC-XXXX"))
    safe_patient = safe_filename_part(patient_id)
    report_name = report_filename(summary)
    letter = summary.get("notification_letter")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{safe_patient}_cover_sheet.pdf", build_cover_sheet(patient_id, summary))
        z.writestr(report_name, render_report(summary, generated_at))
        if letter:
            z.writestr("notification_letter.txt", str(letter))
        # README inside the zip
        readme = (
            f"Broker Kit — {patient_id}\n"
            f"Generated: {datetime.now().isoformat(timespec='seconds')}\n"
            f"\n"
            f"Contents:\n"
            f"  1. {safe_patient}_cover_sheet.pdf    — Empieza aquí (qué hacer y cuándo)\n"
            f"  2. {report_name} — Reporte coordinador completo (11 secciones)\n"
            + ("  3. notification_letter.txt           — Carta de notificación con placeholders\n" if letter else "")
            + "\n"
            "Antes de enviar a la aseguradora:\n"
            "  - Reemplaza [NOMBRE_COMPLETO_PACIENTE], [NÚMERO_DE_PÓLIZA] y [FECHA_DE_NACIMIENTO]\n"
            "    en notification_letter.txt con los datos reales del paciente.\n"
            "  - El ID de paciente es solo el pseudónimo del coordinador — no usar en documentos formales.\n"
        )
        z.writestr("README.txt", readme)

    return buffer.getvalue()
