"""The handover's five planner safety scenarios (``tests/test_planner_safety.py``).

These run before any model call, so they need none. The checks asserted are the
handover's, verbatim, plus the one fix: an oral JAK inhibitor is not a biológico.
"""

import asyncio

from app.core.navigator.planner_agent import (
    PatientProfile,
    _inject_safety_checks,
    generate_action_plan,
    is_biologic,
    run_safety_checks,
)
from tests.navigator.helpers import (
    PARSED_METLIFE,
    PLAN,
    TODAY,
    context,
    scripted,
)


def _plan(patient: PatientProfile, carrier: str) -> dict:
    alerts, force_critical = run_safety_checks(patient, carrier, TODAY)
    mock_plan = {
        "carrier": carrier,
        "urgency_level": "medium",
        "steps": [{"step": 1, "title": "placeholder"}],
        "carrier_alerts": ["LLM-generated alert"],
    }
    return _inject_safety_checks(mock_plan, alerts, force_critical)


def _patient(**overrides) -> PatientProfile:
    values = {
        "carrier": "AXA",
        "diagnosis_icd10": "L20.9",
        "treatment_rx": "dupilumab 300mg",
        "preexisting": False,
        "months_insured": 36,
        "rider_preexisting": False,
        "programacion_done": False,
        "notification_sent": True,
        "days_since_incidence": 2,
        "policy_age_days": 1080,
    }
    values.update(overrides)
    return PatientProfile(**values)


def test_scenario_1_axa_biologic_block():
    plan = _plan(_patient(treatment_rx="Dupilumab 300mg SC Q2W"), "AXA")
    assert plan["urgency_level"] == "critical"
    assert any("EXCLUYE MEDICAMENTOS BIOLÓGICOS" in a for a in plan["carrier_alerts"])
    assert any("Protocolo de Brecha" in a for a in plan["carrier_alerts"])
    assert any("arbitraje" in a for a in plan["carrier_alerts"])
    assert "EXCLUYE" in plan["carrier_alerts"][0]


def test_scenario_2_metlife_programacion():
    plan = _plan(_patient(carrier="MetLife", preexisting=True, months_insured=28, days_since_incidence=1), "METLIFE")
    assert any("Programar pago directo" in a for a in plan["carrier_alerts"])
    assert any("ANTES" in a for a in plan["carrier_alerts"])
    assert any("retroactivo" in a for a in plan["carrier_alerts"])
    assert any("0% coaseguro" in a for a in plan["carrier_alerts"])


def test_scenario_3_smnyl_no_rider():
    plan = _plan(_patient(carrier="SMNYL", preexisting=True, months_insured=12, policy_age_days=365), "SMNYL")
    assert any("rider" in a.lower() for a in plan["carrier_alerts"])
    assert any("Padecimientos Preexistentes" in a for a in plan["carrier_alerts"])
    assert any("día 1" in a for a in plan["carrier_alerts"])
    assert any("permanentemente excluido" in a for a in plan["carrier_alerts"])


def test_scenario_4_notification_breach():
    plan = _plan(_patient(carrier="GNP", notification_sent=False, days_since_incidence=7, policy_age_days=720), "GNP")
    assert plan["urgency_level"] == "critical"
    assert "VENCIDO" in plan["carrier_alerts"][0]
    assert any("Ley sobre el Contrato" in a for a in plan["carrier_alerts"])


def test_scenario_5_axa_30_day_rule():
    plan = _plan(_patient(months_insured=0, days_since_incidence=1, policy_age_days=15), "AXA")
    assert plan["urgency_level"] == "critical"
    assert "REGLA 30 DÍAS" in plan["carrier_alerts"][0]
    assert any("NO presentar reclamación" in a for a in plan["carrier_alerts"])
    assert any("Esperar hasta el día 31 (2026-09-29)" in a for a in plan["carrier_alerts"])


def test_notification_imminent_is_a_warning_not_critical():
    plan = _plan(_patient(carrier="GNP", notification_sent=False, days_since_incidence=3), "GNP")
    assert plan["carrier_alerts"][0].startswith("⚠️ URGENTE: Quedan 2 día(s)")
    assert plan["urgency_level"] == "medium"


def test_fix_jak_inhibitors_are_not_biologics():
    assert is_biologic("Nemluvio 30mg cada 4 semanas")
    assert not is_biologic("upadacitinib 30mg VO diario")
    assert not is_biologic("abrocitinib")
    # A therapy outside the catalog still matches the handover's keywords.
    assert is_biologic("tralokinumab 150mg")

    plan = _plan(_patient(treatment_rx="upadacitinib 30mg"), "AXA")
    assert not any("EXCLUYE MEDICAMENTOS BIOLÓGICOS" in a for a in plan["carrier_alerts"])
    assert plan["urgency_level"] == "medium"


def test_plan_gets_safety_alerts_baseline_docs_and_catalog_prices(monkeypatch):
    model = scripted(monkeypatch, {"planner": PLAN})
    patient = _patient(carrier="MetLife", treatment_rx="dupilumab", notification_sent=False, days_since_incidence=4)
    policy = {**PARSED_METLIFE, "meta": {**PARSED_METLIFE["meta"], "carrier": "MetLife"}}

    plan = asyncio.run(generate_action_plan(context(), policy, patient))

    assert plan["carrier_alerts"][0].startswith("⚠️ URGENTE")
    assert plan["carrier_alerts"][-1] == "Alerta del planificador"
    assert "Registro COFEPRIS del medicamento" in plan["docs_checklist"]["clinical"]
    assert "Facturas CFDI originales de farmacia" in plan["docs_checklist"]["insurance"]
    # The model's figure is overwritten from the catalog.
    assert plan["cost_projection"]["monthly_drug_cost_estimate_mxn"] == 38000
    assert plan["cost_projection"]["unit_cost_mxn"] == 19000
    # The prompt carries the handover's precomputed dates.
    prompt = model.calls[0]["prompt"]
    assert "NOTIFICATION DEADLINE: 2026-09-15" in prompt
    assert "PREAUTH SUBMIT BY: 2026-09-19" in prompt
    assert "Eres el Planificador de Acciones InnovaDerm" in model.calls[0]["system"]


def test_failed_planner_still_carries_the_safety_alerts(monkeypatch):
    scripted(monkeypatch, {"planner": None})
    patient = _patient(carrier="AXA", treatment_rx="dupilumab")
    plan = asyncio.run(generate_action_plan(context(), {"meta": {"carrier": "AXA"}}, patient))
    assert plan["urgency_level"] == "critical"
    assert "EXCLUYE" in plan["carrier_alerts"][0]
    assert "SYSTEM ERROR: Action plan generation failed" in plan["carrier_alerts"]
