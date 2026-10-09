"""The whole pipeline, on a scripted model: order, summary shape, privacy."""

import asyncio
from datetime import date

from app.core.navigator.orchestrator import (
    run_pipeline,
    sanitize_output,
)
from tests.navigator.helpers import (
    TODAY,
    all_answers,
    intake,
    scripted,
)

SUMMARY_KEYS = {
    "run_id",
    "patient_id",
    "carrier",
    "urgency_level",
    "policy_confidence",
    "action_plan",
    "notification_letter",
    "policy_extraction",
    "financial_roadmap",
    "adherence",
    "appeal_package",
    "carrier_alerts",
    "docs_checklist",
    "deadlines",
    "cost_projection",
    "_privacy",
}


def _run(case=None, **kwargs):
    agents: list[str] = []

    async def on_agent(agent: str) -> None:
        agents.append(agent)

    outcome = asyncio.run(
        run_pipeline("CARÁTULA REDACTADA", case or intake(), "PAC-2026-0001", today=TODAY, on_agent=on_agent, **kwargs)
    )
    return outcome, agents


def test_runs_the_handover_order_and_builds_its_summary(monkeypatch):
    model = scripted(monkeypatch, all_answers())
    outcome, progress = _run()
    summary = outcome.summary

    assert model.order == ["parser", "planner", "notification", "optimizer", "adherence"]
    assert progress == model.order
    assert SUMMARY_KEYS <= set(summary)
    assert summary["carrier"] == "MetLife"
    assert summary["patient_id"] == "PAC-2026-0001"
    assert summary["appeal_package"] is None
    assert summary["policy_confidence"] == 0.82
    assert summary["notification_letter"].endswith("Datos procesados bajo pseudonimización conforme a LFPDPPP.")
    assert summary["carrier_alerts"][0].startswith("🚨 MetLife: Programar pago directo")
    assert summary["adherence"]["dose_calendar"][0]["scheduled_date"] == "2026-09-28"  # the planner's first dose
    assert summary["financial_roadmap"]["financial_summary"]["coaseguro_pct"] == 10  # programación not done
    assert summary["policy_extraction"]["meta"]["policy_number"] == (
        "[PSEUDONYMIZED — coordinator CRM ref: PAC-2026-0001]"
    )
    assert outcome.degraded_agents == []
    assert len(outcome.usage) == 5


def test_notice_already_sent_skips_the_letter_and_a_denial_runs_the_advocate(monkeypatch):
    model = scripted(monkeypatch, all_answers())
    outcome, _ = _run(intake(notification_sent=True, denial_reason="Padecimiento preexistente — Cláusula 18"))

    assert model.order == ["parser", "planner", "optimizer", "adherence", "advocate"]
    package = outcome.summary["appeal_package"]
    assert package["_privacy_footer"]
    assert "Datos procesados bajo pseudonimización" in package["carta_apelacion"]["cuerpo"]
    # The dermatologist's name is a credential the letter cites, not patient data.
    assert "Roberto Sánchez Morales" in package["carta_apelacion"]["cuerpo"]
    assert "Cédula Profesional: 7654321" in package["carta_apelacion"]["cuerpo"]
    advocate_prompt = model.calls[-1]["prompt"]
    assert "Dermatólogo: Dr. Roberto Sánchez Morales (Cédula: 7654321)" in advocate_prompt
    assert "Motivo de negativa: Padecimiento preexistente — Cláusula 18" in advocate_prompt


def test_the_prompts_never_carry_the_patient_id(monkeypatch):
    model = scripted(monkeypatch, all_answers())
    _run(intake(denial_reason="Negada"))
    for call in model.calls:
        assert "PAC-2026-0001" not in call["prompt"]


def test_every_agent_failing_still_produces_a_summary(monkeypatch):
    scripted(monkeypatch, {})
    outcome, _ = _run(intake(denial_reason="Negada"))
    summary = outcome.summary

    assert outcome.degraded_agents == ["parser", "planner", "notification", "optimizer", "adherence", "advocate"]
    assert summary["carrier"] == "MetLife"  # the operator's hint
    assert summary["carrier_alerts"][0].startswith("🚨 MetLife")
    assert "[NOMBRE_COMPLETO_PACIENTE]" in summary["notification_letter"]
    assert summary["financial_roadmap"]["utilization_score"] == 50
    assert summary["adherence"]["adherence_score"] == 75
    assert summary["appeal_package"]["_error"]
    assert any("no respondió" in warning for warning in summary["_warnings"])
    # Without a valid first dose from the planner, two weeks out.
    assert summary["adherence"]["dose_calendar"][0]["scheduled_date"] == "2026-09-28"


def test_a_malformed_first_dose_falls_back(monkeypatch):
    answers = all_answers(planner={**all_answers()["planner"], "deadlines": {"first_dose_earliest": "pronto"}})
    scripted(monkeypatch, answers)
    outcome, _ = _run()
    assert outcome.summary["adherence"]["dose_calendar"][0]["scheduled_date"] == "2026-09-28"


def test_days_since_incidence_and_policy_age_come_from_the_dates(monkeypatch):
    model = scripted(monkeypatch, all_answers())
    _run(intake(incidence_date=date(2026, 9, 7), policy_year_start=date(2026, 9, 1), carrier="AXA"))
    planner_prompt = model.calls[1]["prompt"]
    assert "- Days since incidence: 7" in planner_prompt
    assert "- Policy age (days): 13" in planner_prompt


def test_off_catalog_therapy_uses_the_generic_schedule(monkeypatch):
    scripted(monkeypatch, all_answers())
    outcome, _ = _run(intake(treatment_rx="tralokinumab 150mg"))
    summary = outcome.summary
    assert summary["financial_roadmap"]["monthly_projections"][0]["drug_cost_mxn"] > 0
    assert any("no está en el catálogo" in warning for warning in summary["_warnings"])


def test_sanitize_output_replaces_pii_fields_recursively():
    output = {"patient_id": "PAC-9", "nested": {"policy_number": "ML-1", "rfc": "X"}, "keep": "y"}
    sanitized = sanitize_output(output)
    assert sanitized["nested"]["policy_number"] == "[PSEUDONYMIZED — coordinator CRM ref: PAC-9]"
    assert sanitized["nested"]["rfc"].startswith("[PSEUDONYMIZED")
    assert sanitized["keep"] == "y"
