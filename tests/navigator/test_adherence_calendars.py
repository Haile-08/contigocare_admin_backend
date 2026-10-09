"""The adherence monitor's calendars and alerts, with the handover's defects fixed."""

import asyncio

from app.core.navigator.adherence_agent import (
    REAUTH_DOCS,
    AuthorizationStatus,
    generate_adherence_report,
    generate_alerts,
    generate_dose_calendar,
    generate_monitoring_calendar,
)
from tests.navigator.helpers import (
    ADHERENCE,
    TODAY,
    context,
    scripted,
)


def test_dupilumab_calendar_has_loading_doses_on_day_zero():
    doses = generate_dose_calendar("dupilumab", 14, 2, "2026-03-18")
    assert [d["type"] for d in doses[:3]] == ["loading", "loading", "maintenance"]
    assert doses[0]["scheduled_date"] == doses[1]["scheduled_date"] == "2026-03-18"
    assert doses[2]["scheduled_date"] == "2026-04-01"
    assert doses[0]["refill_order_by"] == "2026-03-11"
    # FIX (30-day months): a calendar year, not 360 days.
    assert doses[-1]["scheduled_date"] < "2027-03-18"
    assert len(doses) == 28


def test_fix_nemluvio_loading_dose_carries_two_units():
    doses = generate_dose_calendar("nemolizumab", 28, 1, "2026-06-06", loading_units_per_dose=2)
    assert doses[0]["type"] == "standard"  # the handover's label for a single loading dose
    assert doses[0]["units"] == 2
    assert doses[1]["units"] == 1
    assert len(doses) == 14


def test_fix_monitoring_calendar_uses_calendar_months():
    events = generate_monitoring_calendar("2026-01-31", "2027-01-15")
    labs = [e["scheduled_date"] for e in events if e["event"] == "lab_panel"]
    assert labs == ["2026-01-31", "2026-04-30", "2026-07-31", "2026-10-31"]
    renewals = [e for e in events if e["event"] == "renewal_warning"]
    assert [e["scheduled_date"] for e in renewals] == ["2026-11-16", "2026-12-16", "2026-12-31"]
    assert [e["critical"] for e in renewals] == [False, False, True]


def test_fix_no_invented_authorization():
    doses = generate_dose_calendar("dupilumab", 14, 2, "2026-10-01")
    alerts = generate_alerts(doses, None, "2027-09-14", TODAY)
    assert not any(alert["alert_id"].startswith("AUTH") for alert in alerts)


def test_recorded_authorization_expiring_raises_an_alert():
    authorization = AuthorizationStatus(expiry_date="2026-09-20")
    alerts = generate_alerts([], authorization, "2027-09-14", TODAY)
    assert alerts[0]["alert_id"] == "AUTH-001"
    assert alerts[0]["severity"] == "critical"  # six days out
    assert alerts[0]["deadline"] == "2026-09-13"


def test_refill_and_renewal_alerts():
    doses = generate_dose_calendar("dupilumab", 14, 2, "2026-09-18")
    alerts = generate_alerts(doses, None, "2026-10-30", TODAY)
    refills = [alert for alert in alerts if alert["alert_id"].startswith("REFILL")]
    renewals = [alert for alert in alerts if alert["alert_id"].startswith("RENEW")]
    # Both loading syringes are due in four days, and the refill window has opened.
    assert [alert["title"] for alert in refills] == [
        "Dosis #1 en 4 días — ordenar refill",
        "Dosis #2 en 4 días — ordenar refill",
    ]
    assert renewals[0]["title"] == "Renovación de póliza en 46 días"
    assert renewals[0]["deadline"] == "2026-10-15"


def test_report_shape_and_prompt(monkeypatch):
    model = scripted(monkeypatch, {"adherence": ADHERENCE})
    report = asyncio.run(
        generate_adherence_report(
            context(),
            carrier="MetLife",
            patient_id="PAC-1",
            treatment_drug="dupilumab",
            frequency_days=14,
            loading_doses=2,
            treatment_start_date="2026-09-28",
            policy_year_end="2027-01-15",
            financial_summary={"tope_coaseguro": 25300},
        )
    )
    assert report["authorization"] == {"status": "not_registered"}
    assert report["total_doses_12_months"] == len(report["dose_calendar"])
    assert report["reauth_docs_required"] == REAUTH_DOCS
    assert report["adherence_plan"]["adherence_score"] == 72
    assert "AUTHORIZATION STATUS: {}" in model.calls[0]["prompt"]
    assert "NEXT 6 DOSES:" in model.calls[0]["prompt"]


def test_failed_adherence_uses_the_handover_fallback(monkeypatch):
    scripted(monkeypatch, {"adherence": None})
    report = asyncio.run(
        generate_adherence_report(context(), "GNP", "PAC-1", "dupilumab", 14, 2, "2026-09-28", "2027-01-15")
    )
    assert report["adherence_plan"]["adherence_score"] == 75
    assert report["adherence_plan"]["most_urgent_action"]["title"] == "Sin alertas activas"
