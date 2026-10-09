"""The coordinator report and the broker kit, built in memory from a summary."""

import asyncio
import io
import re
import zipfile

import pypdfium2 as pdfium

from app.core.navigator.broker_kit import (
    broker_kit_filename,
    build_broker_kit,
)
from app.core.navigator.orchestrator import run_pipeline
from app.core.navigator.report import (
    render_report,
    report_filename,
)
from tests.navigator.helpers import (
    TODAY,
    all_answers,
    intake,
    scripted,
)

SECTIONS = [
    "1. Resumen Ejecutivo",
    "2. Extracción de Póliza (Agent 1 — Parser)",
    "3. Alertas de Aseguradora",
    "4. Fechas Límite",
    "5. Plan de Acción (Agent 2 — Planner)",
    "6. Checklist de Documentación",
    "7. Proyección de Costos (Agent 2)",
    "8. Roadmap Financiero — 12 Meses (Agent 4 — Optimizer)",
    "9. Adherencia y Monitoreo (Agent 5 — Monitor)",
    "11. Carta de Notificación de Siniestro",
]


def _summary(monkeypatch, **answers):
    scripted(monkeypatch, all_answers(**answers))
    return asyncio.run(run_pipeline("CARÁTULA", intake(), "PAC-2026-0001", today=TODAY)).summary


def _text(pdf_bytes: bytes) -> str:
    assert pdf_bytes.startswith(b"%PDF-")
    document = pdfium.PdfDocument(pdf_bytes)
    pages = [document[index].get_textpage().get_text_range() for index in range(len(document))]
    # Lines wrap wherever the layout put them; the assertions are about words.
    return re.sub(r"\s+", " ", " ".join(pages))


def test_report_has_the_handover_sections(monkeypatch):
    summary = _summary(monkeypatch)
    text = _text(render_report(summary))

    for section in SECTIONS:
        assert section in text
    assert "InnovaDerm Navigator" in text
    assert "Reporte de Navegación de Cobertura" in text
    assert "PAC-2026-0001" in text
    assert "Paso 1: Enviar notificación de siniestro" in text
    assert "[NOMBRE_COMPLETO_PACIENTE]" in text
    assert "InnovaSalud" not in text
    assert report_filename(summary) == f"InnovaDerm-PAC-2026-0001-MetLife-{summary['run_id']}.pdf"


def test_report_keeps_alert_colour_but_drops_characters_helvetica_cannot_draw(monkeypatch):
    summary = _summary(monkeypatch)
    summary["carrier_alerts"] = ["🚨 Programar pago directo", "⚠️ Revisar tope"]
    text = _text(render_report(summary))
    assert "Programar pago directo" in text
    assert "Revisar tope" in text
    assert "🚨" not in text


def test_report_renders_the_appeal_pathway_when_the_planner_gives_one(monkeypatch):
    plan = {
        **all_answers()["planner"],
        "appeal_pathway": {
            "trigger": "Negativa por preexistencia",
            "step_1": {"action": "Queja ante la UNE", "deadline_relative": "30 días"},
            "key_arguments": ["24 meses de antigüedad"],
        },
    }
    text = _text(render_report(_summary(monkeypatch, planner=plan)))
    assert "10. Vía de Apelación (Agent 3 — Advocate)" in text
    assert "Queja ante la UNE" in text


def test_report_survives_a_summary_whose_agents_all_failed(monkeypatch):
    scripted(monkeypatch, {})
    summary = asyncio.run(run_pipeline("CARÁTULA", intake(), "PAC-2026-0001", today=TODAY)).summary
    assert "1. Resumen Ejecutivo" in _text(render_report(summary))


def test_broker_kit_contents(monkeypatch):
    summary = _summary(monkeypatch)
    archive = zipfile.ZipFile(io.BytesIO(build_broker_kit(summary)))
    names = set(archive.namelist())

    assert names == {
        "PAC-2026-0001_cover_sheet.pdf",
        report_filename(summary),
        "notification_letter.txt",
        "README.txt",
    }
    cover = _text(archive.read("PAC-2026-0001_cover_sheet.pdf"))
    assert "1. Resumen Ejecutivo" in _text(archive.read(report_filename(summary)))
    assert "Hoja de Entrega al Broker" in cover
    assert "Notificación de siniestro: 2026-09-17" in cover
    assert archive.read("notification_letter.txt").decode() == summary["notification_letter"]
    assert "Reemplaza [NOMBRE_COMPLETO_PACIENTE]" in archive.read("README.txt").decode()
    assert broker_kit_filename(summary).startswith("PAC-2026-0001_broker_kit_")
