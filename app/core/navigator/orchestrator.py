"""InnovaDerm Navigator — Orchestrator.

Ported from the handover's ``agents/orchestrator.py``: the same pipeline, in the
same order, assembling the same summary.

    Parser → Planner → Notification Letter → Optimizer → Adherence → Advocate (if denial)

What the handover did around the agents that is not done here: write each
agent's JSON, the letter and the summary under ``outputs/``, and shell out to
the report generator. The summary is returned and stored as a database row; the
coordinator report and the broker kit are built from it when downloaded.
"""

import re
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
)
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
)

from app.core.navigator.adherence_agent import (
    AuthorizationStatus,
    generate_adherence_report,
)
from app.core.navigator.advocate_agent import (
    ClinicalData,
    generate_appeal,
    generate_notification_letter,
)
from app.core.navigator.agent_calls import (
    AgentContext,
    AgentUsage,
)
from app.core.navigator.carriers import normalize_carrier
from app.core.navigator.dates import add_months
from app.core.navigator.drug_catalog import (
    get_drug,
    get_effective_price,
)
from app.core.navigator.optimizer_agent import generate_financial_roadmap
from app.core.navigator.parser_agent import (
    build_policy_text,
    parse_policy,
)
from app.core.navigator.planner_agent import (
    PatientProfile,
    generate_action_plan,
)
from app.schemas.navigation import NavigationIntake

# ─── PRIVACY LAYER ────────────────────────────────────────────────────────────

PII_FIELDS = [
    "patient_name",
    "titular_name",
    "full_name",
    "nombre_paciente",
    "policy_number",
    "numero_poliza",
    "date_of_birth",
    "fecha_nacimiento",
    "rfc",
    "address",
    "domicilio",
]

PII_PATTERNS = [
    r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b",  # RFC
    r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d{2}\b",  # CURP
    r"\b\d{10}\b",  # MX phone
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b",  # email
]

ProgressCallback = Callable[[str], Awaitable[None]]


def detect_pii(text: str) -> list[str]:
    """Flag potential PII patterns in any text before processing.

    Args:
        text: The text.

    Returns:
        list[str]: One flag per matching pattern.
    """
    findings = []
    for pattern in PII_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(f"[PII_DETECTED: {pattern[:30]}]")
    return findings


def sanitize_output(output: dict[str, Any], patient_id: Optional[str] = None) -> dict[str, Any]:
    """MANDATORY: Enforce pseudonymization before any output is stored.

    Replaces all PII fields with pseudonymized reference.

    Args:
        output: The output, or a part of it.
        patient_id: The patient id the reference names.

    Returns:
        dict: The output.
    """
    pid = patient_id or output.get("patient_id", "[PAC-ID-MISSING]")
    ref = f"[PSEUDONYMIZED — coordinator CRM ref: {pid}]"
    for pii_field in PII_FIELDS:
        if pii_field in output:
            output[pii_field] = ref
    for key, value in output.items():
        if isinstance(value, dict):
            output[key] = sanitize_output(value, pid)
    return output


def build_patient_data(intake: NavigationIntake, patient_id: str, today: date) -> dict[str, Any]:
    """The handover's ``patient_data`` dict, from the intake.

    ``days_since_incidence`` and ``policy_age_days`` are computed here, on the
    run date, as the handover's batch script computed ``policy_age_days``.

    Args:
        intake: The intake, free text already redacted.
        patient_id: The analysis's patient id.
        today: The run date.

    Returns:
        dict: The patient data.
    """
    data = intake.model_dump(mode="python", exclude_none=True)
    data["patient_id"] = patient_id
    data["days_since_incidence"] = max((today - intake.incidence_date).days, 0)
    data["policy_age_days"] = max((today - intake.policy_year_start).days, 0)
    data["incidence_date"] = intake.incidence_date.isoformat()
    return data


def _first_dose(action_plan: dict[str, Any], today: date) -> date:
    """The first dose the adherence calendar starts on.

    The planner's ``deadlines.first_dose_earliest``, as in the handover, with the
    handover's fallback of two weeks out when there is none — or when what the
    model wrote is not a date, which the handover would have crashed on.

    Args:
        action_plan: The planner's plan.
        today: The run date.

    Returns:
        date: The first dose.
    """
    deadlines = action_plan.get("deadlines")
    value = deadlines.get("first_dose_earliest") if isinstance(deadlines, dict) else None
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return today + timedelta(days=14)


@dataclass
class PipelineOutcome:
    """What one run produced.

    Attributes:
        summary: The InnovaDerm summary.
        usage: One entry per model call.
        degraded_agents: Agents whose call failed.
    """

    summary: dict[str, Any]
    usage: list[AgentUsage]
    degraded_agents: list[str]


async def run_pipeline(
    policy_text: str,
    intake: NavigationIntake,
    patient_id: str,
    today: Optional[date] = None,
    on_agent: Optional[ProgressCallback] = None,
) -> PipelineOutcome:
    """Run the full InnovaDerm pipeline.

    Args:
        policy_text: The console's redacted copy of the policy.
        intake: The intake, free text already redacted.
        patient_id: The analysis's patient id.
        today: The run date; defaults to today.
        on_agent: Awaited with each agent's key before it starts.

    Returns:
        PipelineOutcome: The summary and its accounting.
    """
    run_date = today or date.today()
    ctx = AgentContext(today=run_date)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    patient_data = build_patient_data(intake, patient_id, run_date)

    async def starting(agent: str) -> None:
        if on_agent is not None:
            await on_agent(agent)

    # ─── PRIVACY CHECK — Reject PII at entry point ────────────
    pii_flags = detect_pii(" ".join(str(value) for key, value in patient_data.items() if key != "patient_id"))
    if pii_flags:
        ctx.warnings.append(
            "Posibles datos personales en los datos del caso "
            f"({', '.join(pii_flags)}); revise el intake antes de compartir los documentos."
        )
    patient_data.pop("patient_name", None)
    patient_data.pop("titular_name", None)

    # ─── AGENT 1: PARSE POLICY ────────────────────────────────
    await starting("parser")
    carrier_hint = normalize_carrier(patient_data.get("carrier"))
    policy = await parse_policy(
        ctx,
        policy_text=build_policy_text(policy_text, carrier_hint),
        carrier_hint=carrier_hint,
    )
    carrier = policy.get("meta", {}).get("carrier") or carrier_hint or "Unknown"
    confidence = policy.get("meta", {}).get("confidence_score", 0)

    # ─── AGENT 2: GENERATE ACTION PLAN ───────────────────────
    await starting("planner")
    patient = PatientProfile(
        carrier=carrier,
        diagnosis_icd10=patient_data.get("diagnosis_icd10", "L20.9"),
        treatment_rx=patient_data.get("treatment_rx", "dupilumab"),
        preexisting=patient_data.get("preexisting", False),
        months_insured=patient_data.get("months_insured", 0),
        rider_preexisting=patient_data.get("rider_preexisting", False),
        programacion_done=patient_data.get("programacion_done", False),
        notification_sent=patient_data.get("notification_sent", False),
        days_since_incidence=patient_data.get("days_since_incidence", 0),
        policy_age_days=patient_data.get("policy_age_days", 0),
        denial_reason=patient_data.get("denial_reason"),
    )
    action_plan = await generate_action_plan(ctx, policy, patient)

    # ─── NOTIFICATION LETTER (always generate if not sent) ────
    notification_letter = None
    if not patient.notification_sent:
        await starting("notification")
        notification_letter = await generate_notification_letter(
            ctx,
            carrier=carrier,
            incidence_date=patient_data.get("incidence_date", run_date.isoformat()),
            diagnosis=patient_data.get("diagnosis", "Dermatitis Atópica"),
            treatment=patient.treatment_rx,
        )

    # ─── AGENT 4: BENEFITS OPTIMIZER ────────────────────────────
    await starting("optimizer")
    policy_year_start: Optional[date] = patient_data.get("policy_year_start")
    financial_roadmap = await generate_financial_roadmap(
        ctx,
        policy=policy,
        patient_id=patient_id,
        carrier=carrier,
        treatment_rx=patient.treatment_rx,
        months_insured=patient.months_insured,
        deducible=patient_data.get("deducible", 15000),
        coaseguro_pct=patient_data.get("coaseguro_pct", 10),
        tope_coaseguro=patient_data.get("tope_coaseguro"),
        policy_year_start=policy_year_start,
        programacion_done=patient.programacion_done,
    )
    fin_summary = financial_roadmap.get("financial_summary", {})
    tope_month = fin_summary.get("tope_reached_month")
    util_score = financial_roadmap.get("utilization_score", 0)

    # ─── AGENT 5: ADHERENCE MONITOR ──────────────────────────────
    await starting("adherence")
    # Derive treatment params from drug catalog
    drug_config = get_drug(patient.treatment_rx)
    if drug_config:
        freq_days = drug_config["frequency_days"]
        loading = drug_config["loading_doses"]
        loading_units = drug_config.get("loading_units_per_dose", 1) or 1
        drug_name = drug_config["generic_name"]
        price = get_effective_price(drug_config["generic_name"], drug_config, run_date)
        if price.stale:
            # The handover's price freshness gate prompted the coordinator on a
            # terminal. Here the caveat travels with the navigation.
            ctx.warnings.append(
                f"El precio de {drug_config['brand_name']} se verificó el {price.verified_at} ({price.source}); "
                "confírmelo con el fabricante antes de compartir la proyección."
            )
    else:
        freq_days = 14
        loading = 0
        loading_units = 1
        drug_name = patient.treatment_rx.split()[0].lower()
        ctx.warnings.append(
            f"«{patient.treatment_rx}» no está en el catálogo de medicamentos: la proyección usa el costo "
            "genérico de $15,000 MXN por dosis cada 14 días."
        )

    # First dose is the earliest from the action plan deadlines
    first_dose = _first_dose(action_plan, run_date)
    py_start = policy_year_start or run_date
    py_end = add_months(py_start, 12)

    authorization_intake = intake.authorization
    authorization = (
        AuthorizationStatus(
            granted_date=authorization_intake.granted_date.isoformat() if authorization_intake.granted_date else "",
            expiry_date=authorization_intake.expiry_date.isoformat(),
            doses_authorized=authorization_intake.doses_authorized or 0,
            status="active",
        )
        if authorization_intake is not None
        else None
    )

    adherence_report = await generate_adherence_report(
        ctx,
        carrier=carrier,
        patient_id=patient_id,
        treatment_drug=drug_name,
        frequency_days=freq_days,
        loading_doses=loading,
        treatment_start_date=first_dose.isoformat(),
        policy_year_end=py_end.isoformat(),
        authorization=authorization,
        months_on_treatment=0,
        financial_summary=fin_summary,
        loading_units_per_dose=loading_units,
    )
    n_doses = adherence_report.get("total_doses_12_months", 0)
    n_events = adherence_report.get("total_monitoring_events", 0)
    adherence_plan = adherence_report.get("adherence_plan", {})
    adherence_score = adherence_plan.get("adherence_score", "N/A") if isinstance(adherence_plan, dict) else "N/A"

    # ─── AGENT 3: APPEAL PACKAGE (if denial present) ─────────
    appeal_package = None
    if patient_data.get("denial_reason"):
        await starting("advocate")
        clinical = ClinicalData(
            patient_name="[NOMBRE_COMPLETO_PACIENTE]",
            policy_number="[NÚMERO_DE_PÓLIZA]",
            carrier=carrier,
            diagnosis=patient_data.get("diagnosis", "Dermatitis Atópica moderada-severa"),
            icd10=patient.diagnosis_icd10,
            treatment=patient.treatment_rx,
            easi_score=patient_data.get("easi_score"),
            scorad_score=patient_data.get("scorad_score"),
            dlqi_score=patient_data.get("dlqi_score"),
            prior_treatments_failed=patient_data.get("prior_treatments_failed", []),
            dermatologist_name=patient_data.get("dermatologist_name", ""),
            dermatologist_cedula=patient_data.get("dermatologist_cedula", ""),
            incidence_date=patient_data.get("incidence_date", ""),
            denial_reason=patient.denial_reason,
            cofepris_registration=patient_data.get("cofepris_registration", ""),
        )
        appeal_package = await generate_appeal(ctx, clinical)

    for agent in ctx.degraded_agents:
        ctx.warnings.append(f"Agente «{agent}»: el modelo no respondió; se usó su respuesta de respaldo.")

    # ─── FINAL PACKAGE ────────────────────────────────────────
    output: dict[str, Any] = {
        "run_id": run_id,
        "patient_id": patient_id,
        "carrier": carrier,
        "urgency_level": action_plan.get("urgency_level"),
        "policy_confidence": confidence,
        "action_plan": action_plan,
        "notification_letter": notification_letter,
        "policy_extraction": {
            "meta": policy.get("meta", {}),
            "financial": policy.get("financial", {}),
            "coverage": policy.get("coverage", {}),
            "preauthorization": policy.get("preauthorization", {}),
            "preexisting": policy.get("preexisting", {}),
            "dermatology": policy.get("dermatology", {}),
            "appeals": policy.get("appeals", {}),
            "waiting_periods": policy.get("waiting_periods", {}),
            "_flags": policy.get("_flags", []),
        },
        "financial_roadmap": {
            "financial_summary": fin_summary,
            "tope_reached_month": tope_month,
            "monthly_projections": financial_roadmap.get("monthly_projections", []),
            "optimization_tips": financial_roadmap.get("optimization_tips", []),
            "utilization_score": util_score,
            "renewal_projection": financial_roadmap.get("renewal_projection", {}),
        },
        "adherence": {
            "adherence_score": adherence_score,
            "total_doses_12_months": n_doses,
            "total_monitoring_events": n_events,
            "active_alerts": adherence_report.get("active_alerts", []),
            "most_urgent": adherence_plan.get("most_urgent_action") if isinstance(adherence_plan, dict) else None,
            "continuity_risk": (
                adherence_plan.get("continuity_risk_assessment") if isinstance(adherence_plan, dict) else None
            ),
            "dose_calendar": adherence_report.get("dose_calendar", []),
            "monitoring_calendar": adherence_report.get("monitoring_calendar", []),
            "reauth_docs_required": adherence_report.get("reauth_docs_required", []),
            "adherence_plan": adherence_plan,
        },
        "appeal_package": appeal_package,
        "carrier_alerts": action_plan.get("carrier_alerts", []),
        "docs_checklist": action_plan.get("docs_checklist", {}),
        "deadlines": action_plan.get("deadlines", {}),
        "cost_projection": action_plan.get("cost_projection", {}),
        "_warnings": ctx.warnings,
        "_generated_at": datetime.now().isoformat(timespec="seconds"),
        "_privacy": "Output pseudonymized per LFPDPPP/GDPR. PII mapping in coordinator CRM.",
    }

    # MANDATORY: sanitize before storing
    output = sanitize_output(output, patient_id)

    return PipelineOutcome(summary=output, usage=ctx.usage, degraded_agents=ctx.degraded_agents)
