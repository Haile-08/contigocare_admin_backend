"""InnovaDerm Navigator — Agent 5: Adherence & Access Monitor.

Ported from the handover's ``agents/adherence_agent.py``. Same monitoring rules,
same reauthorisation documents, same alerts, same prompt and fallback.

Fixes, marked ``FIX`` where they live:

- 30-day months: the dose calendar ran 360 days and the monitoring calendar
  stepped in 30-day blocks. Both use calendar months, and the year is a year.
- Invented authorisation: with no authorisation given, the handover assumed one
  "granted today, valid 180 days, 26 doses" and built expiry alerts and the
  prompt on it. An authorisation now exists only when the operator records one.
- Loading-dose units: each dose carries the units it takes, so Nemluvio's 60 mg
  loading dose reads as two 30 mg units.
"""

import json
from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    date,
    datetime,
    timedelta,
)
from typing import (
    Any,
    Optional,
)

from app.core.navigator.agent_calls import AgentContext
from app.core.navigator.dates import add_months

# ── Data models ───────────────────────────────────────────────────────────


@dataclass
class AuthorizationStatus:
    """An authorisation the insurer granted."""

    authorization_id: str = ""
    granted_date: str = ""
    expiry_date: str = ""
    doses_authorized: int = 0
    doses_used: int = 0
    reauth_required_by: str = ""
    status: str = "active"  # active | expiring | expired | pending


# ── Hard-coded monitoring rules ───────────────────────────────────────────

MONITORING_RULES: dict[str, Any] = {
    "reauth_lead_days": 30,  # Start reauth process 30 days before expiry
    "refill_lead_days": 7,  # Order refill 7 days before next dose
    "clinical_update_months": 6,  # EASI/SCORAD/DLQI refresh every 6 months
    "lab_monitoring_months": 3,  # Safety labs every 3 months
    "photo_documentation_months": 3,  # Clinical photography every 3 months
    "continuity_gap_max_days": 90,  # >90 days gap may trigger new incidence
    "renewal_warning_days": [60, 30, 15],  # Alerts before policy renewal
    "dose_window_days": 3,  # Acceptable window around scheduled dose
}

# Required documentation freshness for reauthorization
REAUTH_DOCS: list[dict[str, Any]] = [
    {"doc": "EASI o SCORAD score actualizado", "max_age_months": 6, "owner": "doctor", "critical": True},
    {"doc": "DLQI actualizado", "max_age_months": 6, "owner": "doctor", "critical": True},
    {"doc": "Registro fotográfico clínico", "max_age_months": 6, "owner": "doctor", "critical": False},
    {"doc": "Panel de laboratorio (BH, QS, PFH)", "max_age_months": 3, "owner": "doctor", "critical": True},
    {"doc": "Nota médica de seguimiento", "max_age_months": 3, "owner": "doctor", "critical": True},
    {"doc": "Carta de necesidad médica continuada", "max_age_months": 12, "owner": "doctor", "critical": True},
]


def _iso(day: date) -> str:
    """``YYYY-MM-DD``.

    Args:
        day: The date.

    Returns:
        str: ISO date.
    """
    return day.strftime("%Y-%m-%d")


def _parse(value: str) -> date:
    """Read an ISO date.

    Args:
        value: ``YYYY-MM-DD``.

    Returns:
        date: The date.
    """
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


# ── Deterministic calendar generation ─────────────────────────────────────


def generate_dose_calendar(
    drug_name: str,
    frequency_days: int,
    loading_doses: int,
    start_date: str,
    months: int = 12,
    loading_units_per_dose: int = 1,
) -> list[dict[str, Any]]:
    """Generate complete dosing calendar for the treatment period.

    Args:
        drug_name: The generic name.
        frequency_days: Maintenance interval.
        loading_doses: Administrations on day 0.
        start_date: The first dose, ``YYYY-MM-DD``.
        months: Calendar months to cover.
        loading_units_per_dose: Units in each loading administration.

    Returns:
        list[dict]: Doses in order, with the handover's keys plus ``units``.
    """
    doses = []
    start = _parse(start_date)
    dose_num = 0
    refill_lead = MONITORING_RULES["refill_lead_days"]

    # Loading doses (day 0)
    for _ in range(loading_doses):
        dose_num += 1
        doses.append(
            {
                "dose_number": dose_num,
                "scheduled_date": _iso(start),
                "type": "loading" if loading_doses > 1 else "standard",
                "units": max(int(loading_units_per_dose), 1),
                "status": "scheduled",
                "refill_order_by": _iso(start - timedelta(days=refill_lead)),
            }
        )

    # Maintenance doses.
    # FIX (30-day months): the calendar covers calendar months, not 30 * months days.
    end_date = add_months(start, months)
    frequency = max(int(frequency_days), 1)
    next_dose = start + timedelta(days=frequency) if loading_doses else start
    while next_dose < end_date:
        dose_num += 1
        doses.append(
            {
                "dose_number": dose_num,
                "scheduled_date": _iso(next_dose),
                "type": "maintenance",
                "units": 1,
                "status": "scheduled",
                "refill_order_by": _iso(next_dose - timedelta(days=refill_lead)),
            }
        )
        next_dose += timedelta(days=frequency)

    return doses


def generate_monitoring_calendar(start_date: str, policy_year_end: str, months: int = 12) -> list[dict[str, Any]]:
    """Generate clinical monitoring events (labs, photos, scores).

    Args:
        start_date: The first dose.
        policy_year_end: The policy year end.
        months: Months to cover.

    Returns:
        list[dict]: Events in date order.
    """
    events = []
    start = _parse(start_date)

    for m in range(months):
        # FIX (30-day months)
        month_date = add_months(start, m)

        # Labs every 3 months
        if m % 3 == 0:
            events.append(
                {
                    "event": "lab_panel",
                    "title": "Panel de laboratorio de seguridad (BH, QS, PFH, IgE, eosinófilos)",
                    "scheduled_date": _iso(month_date),
                    "owner": "doctor",
                    "critical": True,
                    "reason": "Monitoreo de seguridad requerido para biológicos",
                }
            )

        # Clinical photography every 3 months
        if m % 3 == 0:
            events.append(
                {
                    "event": "clinical_photo",
                    "title": "Registro fotográfico clínico estandarizado",
                    "scheduled_date": _iso(month_date),
                    "owner": "doctor",
                    "critical": False,
                    "reason": "Documentación visual de respuesta al tratamiento",
                }
            )

        # EASI/SCORAD/DLQI every 6 months
        if m % 6 == 0:
            events.append(
                {
                    "event": "clinical_scores",
                    "title": "Actualización EASI/SCORAD + DLQI",
                    "scheduled_date": _iso(month_date),
                    "owner": "doctor",
                    "critical": True,
                    "reason": "Scores clínicos requeridos para reautorización",
                }
            )

        # Dermatology follow-up every 2 months
        if m % 2 == 0:
            events.append(
                {
                    "event": "derm_followup",
                    "title": "Consulta de seguimiento dermatología",
                    "scheduled_date": _iso(month_date),
                    "owner": "patient",
                    "critical": False,
                    "reason": "Evaluación de respuesta y ajuste de tratamiento",
                }
            )

    # Renewal warnings
    py_end = _parse(policy_year_end)
    for days_before in MONITORING_RULES["renewal_warning_days"]:
        warn_date = py_end - timedelta(days=days_before)
        if warn_date >= start:
            events.append(
                {
                    "event": "renewal_warning",
                    "title": f"Renovación de póliza en {days_before} días",
                    "scheduled_date": _iso(warn_date),
                    "owner": "coordinator",
                    "critical": days_before <= 15,
                    "reason": "Verificar renovación, analizar cambio de carrier, "
                    "preparar documentación de continuidad",
                }
            )

    return sorted(events, key=lambda e: e["scheduled_date"])


def generate_alerts(
    dose_calendar: list[dict[str, Any]],
    authorization: Optional[AuthorizationStatus],
    policy_year_end: str,
    today: date,
) -> list[dict[str, Any]]:
    """Generate all active alerts based on current date.

    Args:
        dose_calendar: The doses.
        authorization: The recorded authorisation, or None.
        policy_year_end: The policy year end.
        today: The run date.

    Returns:
        list[dict]: Alerts, critical first.
    """
    alerts: list[dict[str, Any]] = []
    now = today
    alert_id = 0

    # Authorization expiry alert.
    # FIX (invented authorisation): only for an authorisation that exists.
    if authorization is not None and authorization.expiry_date:
        expiry = _parse(authorization.expiry_date)
        days_to_expiry = (expiry - now).days

        if days_to_expiry <= 0:
            alert_id += 1
            alerts.append(
                {
                    "alert_id": f"AUTH-{alert_id:03d}",
                    "severity": "critical",
                    "trigger_date": _iso(now),
                    "title": "Autorización EXPIRADA",
                    "action_required": "Iniciar proceso de reautorización de emergencia. "
                    "Contactar a la aseguradora HOY. Preparar documentación "
                    "clínica actualizada.",
                    "owner": "coordinator",
                    "deadline": _iso(now),
                }
            )
        elif days_to_expiry <= MONITORING_RULES["reauth_lead_days"]:
            alert_id += 1
            alerts.append(
                {
                    "alert_id": f"AUTH-{alert_id:03d}",
                    "severity": "warning" if days_to_expiry > 7 else "critical",
                    "trigger_date": _iso(now),
                    "title": f"Autorización expira en {days_to_expiry} días ({authorization.expiry_date})",
                    "action_required": "Iniciar reautorización. Verificar que documentación "
                    "clínica esté actualizada (EASI/SCORAD < 6 meses, "
                    "labs < 3 meses).",
                    "owner": "coordinator",
                    "deadline": _iso(expiry - timedelta(days=7)),
                }
            )

    # Upcoming doses needing refill
    for dose in dose_calendar:
        dose_date = _parse(dose["scheduled_date"])
        refill_by = _parse(dose["refill_order_by"])
        days_to_dose = (dose_date - now).days

        if dose["status"] == "scheduled" and 0 <= days_to_dose <= 14 and now >= refill_by:
            alert_id += 1
            alerts.append(
                {
                    "alert_id": f"REFILL-{alert_id:03d}",
                    "severity": "warning" if days_to_dose > 3 else "critical",
                    "trigger_date": _iso(now),
                    "title": f"Dosis #{dose['dose_number']} en {days_to_dose} días — ordenar refill",
                    "action_required": f"Ordenar {dose.get('type', 'maintenance')} dose. "
                    f"Confirmar disponibilidad en farmacia de red.",
                    "owner": "coordinator",
                    "deadline": dose["scheduled_date"],
                }
            )

    # Continuity gap detection
    administered = [d for d in dose_calendar if d["status"] == "administered"]
    if administered:
        last_dose = max(administered, key=lambda d: d["scheduled_date"])
        gap_days = (now - _parse(last_dose["scheduled_date"])).days
        if gap_days > MONITORING_RULES["continuity_gap_max_days"]:
            alert_id += 1
            alerts.append(
                {
                    "alert_id": f"GAP-{alert_id:03d}",
                    "severity": "critical",
                    "trigger_date": _iso(now),
                    "title": f"Gap de continuidad: {gap_days} días sin tratamiento",
                    "action_required": "RIESGO: Gap > 90 días. La aseguradora puede requerir "
                    "nuevo incidente y nueva preautorización. Contactar a "
                    "aseguradora para clarificar estatus de cobertura.",
                    "owner": "coordinator",
                    "deadline": _iso(now),
                }
            )

    # Renewal proximity
    py_end = _parse(policy_year_end)
    days_to_renewal = (py_end - now).days
    if 0 < days_to_renewal <= 60:
        alert_id += 1
        alerts.append(
            {
                "alert_id": f"RENEW-{alert_id:03d}",
                "severity": "warning" if days_to_renewal > 15 else "critical",
                "trigger_date": _iso(now),
                "title": f"Renovación de póliza en {days_to_renewal} días",
                "action_required": "Revisar análisis de renovación del Optimizador Financiero. "
                "Decidir stay vs. switch. Preparar documentación de continuidad "
                "si cambia de carrier.",
                "owner": "coordinator",
                "deadline": _iso(py_end - timedelta(days=15)),
            }
        )

    return sorted(alerts, key=lambda a: {"critical": 0, "warning": 1, "info": 2}.get(a["severity"], 3))


# ── LLM-powered adherence recommendations ────────────────────────────────

SYSTEM_PROMPT = """Eres el Monitor de Adherencia InnovaDerm — experto en mantener el
acceso continuo a terapia biológica para pacientes con seguro GMM en México.

Tu función: analizar el calendario de tratamiento del paciente, estatus de autorización
y próximos eventos para generar recomendaciones personalizadas de adherencia.

IMPORTANTE: Toda tu salida (textos, recomendaciones, alertas) debe estar en español
mexicano (ES-MX).

Áreas de enfoque:
- Prevenir gaps de tratamiento que puedan detonar requisitos de nuevo incidente
- Reautorización proactiva antes del vencimiento
- Vigencia de documentación clínica para cumplimiento con la aseguradora
- Engagement del paciente y soporte de autoadministración
- Requisitos de continuidad específicos por aseguradora

REGLAS:
1. Priorizar la continuidad de cobertura por encima de todo — un gap puede costar meses de re-aprobación
2. Todas las fechas deben ser específicas (formato ISO)
3. Señalar prominentemente la acción más urgente
4. Devolver únicamente JSON válido
5. Las recomendaciones deben ser ejecutables dentro de 1 semana"""


async def generate_adherence_plan(
    ctx: AgentContext,
    carrier: str,
    dose_calendar: list[dict[str, Any]],
    monitoring_calendar: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    authorization: Optional[AuthorizationStatus],
    months_on_treatment: int = 0,
    policy_year_end: str = "",
    financial_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Use the model to generate personalized adherence recommendations.

    Args:
        ctx: The run.
        carrier: The carrier.
        dose_calendar: The doses.
        monitoring_calendar: The monitoring events.
        alerts: Active alerts.
        authorization: The recorded authorisation, or None.
        months_on_treatment: Months already on treatment.
        policy_year_end: The policy year end.
        financial_summary: The optimizer's summary.

    Returns:
        dict: The adherence plan.
    """
    # Summarize calendar for prompt (avoid sending full calendar)
    upcoming_doses = [d for d in dose_calendar if d["status"] == "scheduled"][:6]
    upcoming_monitoring = [m for m in monitoring_calendar if _parse(m["scheduled_date"]) >= ctx.today][:8]

    user_prompt = f"""Generate adherence plan for this patient.

CARRIER: {carrier}
MONTHS ON TREATMENT: {months_on_treatment}
POLICY YEAR ENDS: {policy_year_end}
AUTHORIZATION STATUS: {json.dumps(asdict(authorization) if authorization is not None else {}, ensure_ascii=False)}

ACTIVE ALERTS ({len(alerts)}):
{json.dumps(alerts[:5], ensure_ascii=False, indent=2)}

NEXT 6 DOSES:
{json.dumps(upcoming_doses, ensure_ascii=False, indent=2)}

UPCOMING MONITORING:
{json.dumps(upcoming_monitoring, ensure_ascii=False, indent=2)}

FINANCIAL CONTEXT:
{json.dumps(financial_summary or {}, ensure_ascii=False, indent=2)}

Generate JSON:
{{
  "most_urgent_action": {{
    "title": "",
    "action": "",
    "deadline": "YYYY-MM-DD",
    "owner": "coordinator|patient|doctor"
  }},
  "adherence_score": 0,
  "adherence_score_factors": [],
  "next_30_days_actions": [
    {{
      "date": "YYYY-MM-DD",
      "action": "",
      "owner": "",
      "type": "dose|lab|reauth|admin|followup"
    }}
  ],
  "reauthorization_status": {{
    "days_until_expiry": 0,
    "docs_needed_for_reauth": [],
    "reauth_start_by": "YYYY-MM-DD"
  }},
  "continuity_risk_assessment": {{
    "risk_level": "low|medium|high|critical",
    "risk_factors": [],
    "mitigation_actions": []
  }},
  "patient_engagement_tips": []
}}"""

    plan = await ctx.json("adherence", user_prompt, system=SYSTEM_PROMPT)
    if plan is None:
        return _fallback_adherence(alerts)
    return plan


def _fallback_adherence(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic fallback.

    Args:
        alerts: Active alerts.

    Returns:
        dict: A minimal adherence plan.
    """
    most_urgent = (
        alerts[0]
        if alerts
        else {
            "title": "Sin alertas activas",
            "action": "Continuar tratamiento según calendario",
            "deadline": "",
            "owner": "patient",
        }
    )
    return {
        "most_urgent_action": {
            "title": most_urgent.get("title", ""),
            "action": most_urgent.get("action_required", most_urgent.get("action", "")),
            "deadline": most_urgent.get("deadline", ""),
            "owner": most_urgent.get("owner", "coordinator"),
        },
        "adherence_score": 75,
        "adherence_score_factors": ["Modo fallback — score estimado"],
        "next_30_days_actions": [],
        "reauthorization_status": {"days_until_expiry": None, "docs_needed_for_reauth": [], "reauth_start_by": ""},
        "continuity_risk_assessment": {
            "risk_level": "medium",
            "risk_factors": ["Análisis en modo fallback"],
            "mitigation_actions": [],
        },
        "patient_engagement_tips": [
            "Mantener calendario de dosis actualizado",
            "No interrumpir tratamiento sin consultar al médico",
        ],
    }


# ── Main entry point ─────────────────────────────────────────────────────


async def generate_adherence_report(
    ctx: AgentContext,
    carrier: str,
    patient_id: str,
    treatment_drug: str,
    frequency_days: int,
    loading_doses: int,
    treatment_start_date: str,
    policy_year_end: str,
    authorization: Optional[AuthorizationStatus] = None,
    months_on_treatment: int = 0,
    financial_summary: Optional[dict[str, Any]] = None,
    loading_units_per_dose: int = 1,
) -> dict[str, Any]:
    """Generate complete adherence monitoring report.

    Args:
        ctx: The run.
        carrier: The carrier.
        patient_id: The console's patient id.
        treatment_drug: The generic name.
        frequency_days: Maintenance interval.
        loading_doses: Administrations on day 0.
        treatment_start_date: The first dose.
        policy_year_end: The policy year end.
        authorization: The recorded authorisation, or None.
        months_on_treatment: Months already on treatment.
        financial_summary: The optimizer's summary.
        loading_units_per_dose: Units in each loading administration.

    Returns:
        dict: Calendars, alerts, adherence plan, and risk assessment.
    """
    # FIX (invented authorisation): the handover defaulted to one "granted
    # today, valid 180 days". With none recorded there is none.

    # ── DETERMINISTIC: Generate calendars ─────────────────────────
    dose_calendar = generate_dose_calendar(
        drug_name=treatment_drug,
        frequency_days=frequency_days,
        loading_doses=loading_doses,
        start_date=treatment_start_date,
        months=12,
        loading_units_per_dose=loading_units_per_dose,
    )

    monitoring_calendar = generate_monitoring_calendar(
        start_date=treatment_start_date,
        policy_year_end=policy_year_end,
        months=12,
    )

    # ── DETERMINISTIC: Generate alerts ────────────────────────────
    alerts = generate_alerts(
        dose_calendar=dose_calendar,
        authorization=authorization,
        policy_year_end=policy_year_end,
        today=ctx.today,
    )

    # ── LLM: Adherence recommendations ───────────────────────────
    adherence_plan = await generate_adherence_plan(
        ctx,
        carrier=carrier,
        dose_calendar=dose_calendar,
        monitoring_calendar=monitoring_calendar,
        alerts=alerts,
        authorization=authorization,
        months_on_treatment=months_on_treatment,
        policy_year_end=policy_year_end,
        financial_summary=financial_summary,
    )

    return {
        "patient_id": patient_id,
        "carrier": carrier,
        "treatment": {
            "drug": treatment_drug,
            "frequency_days": frequency_days,
            "start_date": treatment_start_date,
        },
        "authorization": (
            {
                "id": authorization.authorization_id,
                "status": authorization.status,
                "expiry_date": authorization.expiry_date,
                "doses_authorized": authorization.doses_authorized,
                "doses_used": authorization.doses_used,
            }
            if authorization is not None
            else {"status": "not_registered"}
        ),
        "dose_calendar": dose_calendar,
        "monitoring_calendar": monitoring_calendar,
        "active_alerts": alerts,
        "adherence_plan": adherence_plan,
        "total_doses_12_months": len(dose_calendar),
        "total_monitoring_events": len(monitoring_calendar),
        "reauth_docs_required": REAUTH_DOCS,
        "_privacy": "Pseudonymized per LFPDPPP. No PII in this document.",
    }
