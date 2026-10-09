"""InnovaDerm Navigator — Agent 4: Benefits Optimizer.

Ported from the handover's ``agents/optimizer_agent.py``. Same carrier rules,
same bundling services, same strategic prompt and fallback, same roadmap keys.
The projection still starts at the policy year and still runs twelve months.

The arithmetic had four defects, all visible in the handover's own saved
projections, and each is fixed where it lives (search for ``FIX``):

1. Negative payments — the whole deducible was charged in month one whatever
   month one cost, so an $86,000 deducible against a $30,000 month produced an
   insurer payment of −$56,000.
2. Loading-dose units — every administration cost one unit, so Nemluvio's
   60 mg day-0 dose was priced as 30 mg, and the doses per month came from
   ``30 // frequency_days`` rather than from the schedule.
3. 30-day months — the months drifted from the calendar.
4. MetLife's 0% coaseguro — applied whether or not programación was scheduled,
   projecting a saving the patient does not get.
"""

import json
from dataclasses import dataclass
from datetime import (
    date,
    timedelta,
)
from typing import (
    Any,
    Optional,
)

from app.core.navigator.agent_calls import AgentContext
from app.core.navigator.dates import add_months
from app.core.navigator.drug_catalog import get_drug

# ── Data models ───────────────────────────────────────────────────────────


@dataclass
class TreatmentSchedule:
    """The therapy the roadmap is built on."""

    drug_name: str  # e.g., "dupilumab"
    brand_name: str  # e.g., "Dupixent"
    dose_mg: float  # e.g., 300
    frequency_days: int  # e.g., 14 (Q2W)
    route: str  # e.g., "SC"
    unit_cost_mxn: float  # per dose
    loading_doses: int = 2  # first visit = 2 syringes
    loading_units_per_dose: int = 1  # FIX (loading-dose units)
    start_date: str = ""
    requires_infusion_center: bool = False
    requires_cold_chain: bool = True
    cofepris_registration: str = ""
    psp_program_name: str = ""  # e.g., "Dupixent MyWay"
    psp_copay_bridge_pct: float = 0.0  # % covered by manufacturer


# ── Hard-coded carrier financial rules ────────────────────────────────────

CARRIER_FINANCIAL_RULES: dict[str, dict[str, Any]] = {
    "METLIFE": {
        "deducible_type": "per_event",
        "deducible_resets": "per_policy_year",
        "coaseguro_default_pct": 10,
        "tope_coaseguro_range": (12650, 63250),
        "tope_coaseguro_default": 25300,  # 10% plan
        "pago_directo_coaseguro_pct": 0,
        "programacion_required": True,
        "deducible_reduction_network": 0.50,  # 50% reduction in-network
        "moneda": "MXN",
        "renewal_increase_typical_pct": 8,  # ~8% annual for healthy
        "renewal_increase_claims_pct": 15,  # ~15% if heavy claims
        "preexisting_continuity_months": 24,
    },
    "GNP": {
        "deducible_type": "per_event",
        "deducible_resets": "per_policy_year",
        "coaseguro_default_pct": 10,
        "tope_coaseguro_range": (15000, 60000),
        "tope_coaseguro_default": 30000,
        "pago_directo_coaseguro_pct": None,  # via programacion only
        "programacion_required": True,
        "deducible_reduction_network": 0,
        "moneda": "MXN",
        "renewal_increase_typical_pct": 10,
        "renewal_increase_claims_pct": 18,
        "preexisting_continuity_months": 24,
    },
    "SMNYL": {
        "deducible_type": "per_event",
        "deducible_resets": "per_policy_year",
        "coaseguro_default_pct": 10,
        "tope_coaseguro_range": (100000, 100000),
        "tope_coaseguro_default": 100000,
        "pago_directo_coaseguro_pct": None,  # no pago directo
        "programacion_required": False,
        "deducible_reduction_network": 0,
        "moneda": "MXN",
        "renewal_increase_typical_pct": 10,
        "renewal_increase_claims_pct": 20,
        "preexisting_continuity_months": 0,  # rider-based
        "segunda_valoracion_skin": True,
    },
    "AXA": {
        "deducible_type": "per_event",
        "deducible_resets": "per_policy_year",
        "coaseguro_default_pct": 10,
        "tope_coaseguro_range": (20000, 50000),
        "tope_coaseguro_default": 30000,
        "pago_directo_coaseguro_pct": None,  # reimbursement only for meds
        "programacion_required": False,
        "deducible_reduction_network": 0,
        "moneda": "MXN",
        "renewal_increase_typical_pct": 12,
        "renewal_increase_claims_pct": 25,
        "preexisting_continuity_months": 0,  # 30-day rule, arbitration
        "biologics_excluded": True,
    },
}

# Ancillary services the patient should bundle into the same policy year
BUNDLING_SERVICES: list[dict[str, Any]] = [
    {
        "service": "Panel de laboratorio completo (BH, QS, PFH, IgE, eosinófilos)",
        "frequency": "Cada 3 meses",
        "est_cost_mxn": 3500,
        "why": "Monitoreo de seguridad requerido para biológicos — cubierto bajo mismo siniestro",
    },
    {
        "service": "Consulta dermatología de seguimiento",
        "frequency": "Cada 2 meses",
        "est_cost_mxn": 1500,
        "why": "Documentación de respuesta (EASI/SCORAD) necesaria para reautorización",
    },
    {
        "service": "Registro fotográfico clínico estandarizado",
        "frequency": "Cada 3 meses",
        "est_cost_mxn": 800,
        "why": "Evidencia visual de mejoría — fortalece expediente para reauth",
    },
    {
        "service": "Evaluación DLQI (calidad de vida)",
        "frequency": "Cada 6 meses",
        "est_cost_mxn": 0,
        "why": "Score gratuito pero obligatorio para justificar continuidad",
    },
    {
        "service": "Consulta psicología/psiquiatría (impacto QoL de DA)",
        "frequency": "Según necesidad",
        "est_cost_mxn": 1200,
        "why": "Documentar impacto emocional fortalece caso clínico; cubierto por GMM",
    },
    {
        "service": "Pruebas de alergia (patch test / IgE específica)",
        "frequency": "Una vez al año",
        "est_cost_mxn": 4500,
        "why": "Identificar triggers reduce brotes; cubierto como diagnóstico",
    },
]


# ── Pre-API financial calculations (deterministic) ────────────────────────


def schedule_units(treatment: TreatmentSchedule, start: date, end: date) -> list[tuple[date, int]]:
    """Every administration from ``start`` up to ``end``, with its units.

    FIX (loading-dose units): the handover estimated doses per month as
    ``30 // frequency_days`` and charged each one unit. The schedule is walked
    instead, and a loading administration carries its units.

    Args:
        treatment: The therapy.
        start: The first administration.
        end: Exclusive end.

    Returns:
        list: ``(date, units)`` per administration.
    """
    frequency = max(int(treatment.frequency_days), 1)
    administrations = [(start, max(int(treatment.loading_units_per_dose), 1))] * int(treatment.loading_doses)
    # With loading doses the first maintenance dose is one interval later; a
    # therapy without one starts maintenance on day zero.
    current = start + timedelta(days=frequency) if treatment.loading_doses else start
    while current < end:
        administrations.append((current, 1))
        current += timedelta(days=frequency)
    return administrations


def calculate_monthly_projections(
    treatment: TreatmentSchedule,
    deducible: float,
    coaseguro_pct: float,
    tope_coaseguro: float,
    pago_directo_coaseguro_pct: Optional[float],
    policy_year_start: date,
    months: int = 12,
) -> list[dict[str, Any]]:
    """Generate month-by-month financial projection.

    This is deterministic math — never LLM-generated.

    Args:
        treatment: The therapy.
        deducible: The deducible.
        coaseguro_pct: The policy coaseguro.
        tope_coaseguro: The cap on cumulative coaseguro.
        pago_directo_coaseguro_pct: The programación rate when it applies, else None.
        policy_year_start: Month one begins here.
        months: Months to project.

    Returns:
        list[dict]: One row per month, with the handover's keys.
    """
    projections = []
    coaseguro_cumulative = 0.0
    deducible_left = float(deducible)
    tope_reached = False

    # Effective coaseguro rate (pago directo override if available)
    effective_coaseguro = pago_directo_coaseguro_pct if pago_directo_coaseguro_pct is not None else coaseguro_pct

    # FIX (30-day months): calendar months from the policy year start.
    administrations = schedule_units(treatment, policy_year_start, add_months(policy_year_start, months))

    for m in range(months):
        month_start = add_months(policy_year_start, m)
        month_end = add_months(policy_year_start, m + 1)
        this_month = [units for when, units in administrations if month_start <= when < month_end]

        doses_this_month = len(this_month)
        drug_cost = treatment.unit_cost_mxn * sum(this_month)

        # FIX (negative payments): the deducible is consumed by claims as they
        # occur — the lesser of the claim and what is left of it — instead of
        # being charged in full in month one.
        deducible_this_month = min(deducible_left, drug_cost)
        deducible_left -= deducible_this_month

        # Coaseguro calculation
        if tope_reached:
            coaseguro_this_month = 0.0
        else:
            coaseguro_this_month = (drug_cost - deducible_this_month) * (effective_coaseguro / 100)
            if effective_coaseguro > 0 and coaseguro_cumulative + coaseguro_this_month >= tope_coaseguro:
                coaseguro_this_month = max(tope_coaseguro - coaseguro_cumulative, 0.0)
                tope_reached = True

        coaseguro_cumulative += coaseguro_this_month
        patient_pays = deducible_this_month + coaseguro_this_month
        psp_bridge = drug_cost * (treatment.psp_copay_bridge_pct / 100)
        patient_net = max(0.0, patient_pays - psp_bridge)
        carrier_pays = drug_cost - patient_pays

        projections.append(
            {
                "month": m + 1,
                "date": month_start.strftime("%Y-%m"),
                "doses": doses_this_month,
                "drug_cost_mxn": round(drug_cost, 2),
                "deducible_mxn": round(deducible_this_month, 2),
                "coaseguro_mxn": round(coaseguro_this_month, 2),
                "coaseguro_cumulative_mxn": round(coaseguro_cumulative, 2),
                "tope_reached": tope_reached,
                "patient_pays_mxn": round(patient_pays, 2),
                "psp_bridge_mxn": round(psp_bridge, 2),
                "patient_net_mxn": round(patient_net, 2),
                "carrier_pays_mxn": round(carrier_pays, 2),
            }
        )

    return projections


def calculate_no_optimization_cost(
    treatment: TreatmentSchedule,
    coaseguro_pct: float,
    tope_coaseguro: float,
    deducible: float,
    policy_year_start: date,
    months: int = 12,
) -> float:
    """What the patient would pay WITHOUT optimization (no pago directo, no bundling).

    FIX (negative payments): the same month-by-month arithmetic at the policy
    coaseguro, so the saving compares like with like. The handover's version
    charged coaseguro on the full drug cost on top of a separately-added
    deducible, which reported a saving even when nothing was optimised.

    Args:
        treatment: The therapy.
        coaseguro_pct: The policy coaseguro.
        tope_coaseguro: The cap.
        deducible: The deducible.
        policy_year_start: Month one begins here.
        months: Months to project.

    Returns:
        float: The patient's twelve-month cost.
    """
    rows = calculate_monthly_projections(
        treatment, deducible, coaseguro_pct, tope_coaseguro, None, policy_year_start, months
    )
    return round(sum(row["patient_net_mxn"] for row in rows), 2)


# ── LLM-powered strategic analysis ───────────────────────────────────────

SYSTEM_PROMPT = """Eres el Optimizador de Beneficios InnovaDerm — experto en maximizar
el valor de pólizas de GMM mexicanas para pacientes en terapia biológica a largo plazo.

Tu función: dadas las proyecciones financieras del paciente, reglas de la aseguradora y
calendario de tratamiento, generar recomendaciones estratégicas de optimización que
vayan MÁS ALLÁ de los cálculos básicos.

IMPORTANTE: Toda tu salida (textos, recomendaciones, notas) debe estar en español
mexicano (ES-MX).

Analizas:
- Estrategias de temporalidad del año póliza (front-load vs. distribuir gastos)
- Beneficios y oportunidades específicas por aseguradora que la mayoría de pacientes desconoce
- Tácticas de negociación de renovación basadas en historial de siniestros
- Cuándo cambiar de aseguradora vs. permanecer (trade-offs de protección por preexistencia)
- Combinación de programas PSP del fabricante con beneficios del seguro
- Oportunidades de deducción fiscal de gastos médicos (Art. 151 LISR)
- Agrupación de servicios cubiertos complementarios en el mismo año póliza

REGLAS:
1. Todas las recomendaciones deben ser específicas por aseguradora — nunca consejos genéricos
2. Siempre citar el impacto financiero en MXN con comparación clara antes/después
3. Señalar si la recomendación requiere acción del coordinador vs. del paciente
4. Devolver únicamente JSON válido — sin prosa, sin markdown
5. Ser conservador con las estimaciones de ahorro — prometer menos, entregar más
6. Nunca recomendar acciones que puedan poner en riesgo la continuidad de cobertura"""


def _rules_json(carrier_rules: dict[str, Any]) -> str:
    """The carrier rules as the handover's prompt printed them.

    Args:
        carrier_rules: The rules.

    Returns:
        str: JSON, with the tope range as a list.
    """
    return json.dumps(
        {key: list(value) if isinstance(value, tuple) else value for key, value in carrier_rules.items()},
        ensure_ascii=False,
    )


async def generate_strategic_analysis(
    ctx: AgentContext,
    projections: list[dict[str, Any]],
    carrier: str,
    treatment: TreatmentSchedule,
    patient_months_insured: int,
    tope_reached_month: Optional[int],
) -> dict[str, Any]:
    """Use the model to generate strategic optimization beyond deterministic math.

    Args:
        ctx: The run.
        projections: The monthly rows.
        carrier: The carrier.
        treatment: The therapy.
        patient_months_insured: Tenure.
        tope_reached_month: When the tope is reached, if it is.

    Returns:
        dict: The strategic analysis.
    """
    carrier_rules = CARRIER_FINANCIAL_RULES.get(carrier.upper(), {})

    user_prompt = f"""Analyze this patient's financial position and generate optimization strategy.

CARRIER: {carrier}
CARRIER RULES: {_rules_json(carrier_rules)}
TREATMENT: {treatment.drug_name} ({treatment.brand_name}) {treatment.dose_mg}mg every {treatment.frequency_days} days
UNIT COST: ${treatment.unit_cost_mxn:,.0f} MXN per dose
PATIENT MONTHS INSURED: {patient_months_insured}
TOPE REACHED IN MONTH: {tope_reached_month or "Not reached in 12 months"}
PSP PROGRAM: {treatment.psp_program_name or "None enrolled"}

12-MONTH PROJECTIONS:
{json.dumps(projections, ensure_ascii=False, indent=2)}

Generate JSON with these exact keys:
{{
  "strategic_summary": "2-3 sentence overview of financial position and key opportunity",
  "optimization_tips": [
    {{
      "id": "OPT-001",
      "title": "",
      "action": "",
      "owner": "coordinator|patient|doctor",
      "timing": "immediate|month_X|before_renewal",
      "savings_estimate_mxn": null,
      "risk_if_ignored": "",
      "carrier_specific": true
    }}
  ],
  "bundling_opportunities": [
    {{
      "service": "",
      "recommended_month": 0,
      "est_cost_mxn": 0,
      "patient_cost_mxn": 0,
      "rationale": ""
    }}
  ],
  "renewal_projection": {{
    "premium_increase_estimate_pct": 0,
    "stay_vs_switch_recommendation": "",
    "continuity_risk": "",
    "negotiation_tactics": [],
    "optimal_renewal_action": ""
  }},
  "tax_deduction_note": "",
  "utilization_score": 0,
  "utilization_score_explanation": ""
}}"""

    analysis = await ctx.json("optimizer", user_prompt, system=SYSTEM_PROMPT)
    if analysis is None:
        return _fallback_analysis(tope_reached_month, treatment)
    return analysis


def _fallback_analysis(tope_month: Optional[int], treatment: TreatmentSchedule) -> dict[str, Any]:
    """Deterministic fallback if LLM fails.

    Args:
        tope_month: When the tope is reached, if it is.
        treatment: The therapy.

    Returns:
        dict: A minimal strategic analysis.
    """
    tips = []
    if tope_month and tope_month <= 6:
        tips.append(
            {
                "id": "OPT-001",
                "title": f"Tope de coaseguro alcanzado en mes {tope_month}",
                "action": f"Después del mes {tope_month}, programar todos los servicios médicos cubiertos "
                "antes del fin del año póliza — laboratorios, consultas, estudios de imagen.",
                "owner": "coordinator",
                "timing": f"month_{tope_month}",
                "savings_estimate_mxn": None,
                "risk_if_ignored": "Servicios médicos necesarios pagados de bolsillo innecesariamente",
                "carrier_specific": True,
            }
        )
    if treatment.psp_program_name:
        tips.append(
            {
                "id": "OPT-002",
                "title": f"Inscribir en PSP {treatment.psp_program_name}",
                "action": "Registrar al paciente en el programa de soporte del fabricante para copay bridge "
                "y dosis de cortesía durante periodos de autorización pendiente.",
                "owner": "coordinator",
                "timing": "immediate",
                "savings_estimate_mxn": None,
                "risk_if_ignored": "Paciente paga de bolsillo durante gaps de autorización",
                "carrier_specific": False,
            }
        )
    return {
        "strategic_summary": "Análisis estratégico generado en modo fallback — revisar manualmente.",
        "optimization_tips": tips,
        "bundling_opportunities": BUNDLING_SERVICES[:3],
        "renewal_projection": {
            "premium_increase_estimate_pct": 15,
            "stay_vs_switch_recommendation": "Revisar manualmente",
            "continuity_risk": "Alta — cambio de carrier reinicia periodo preexistencias",
            "negotiation_tactics": [],
            "optimal_renewal_action": "Mantener póliza actual",
        },
        "tax_deduction_note": "Los gastos médicos no cubiertos por seguro son deducibles de ISR (Art. 151 LISR).",
        "utilization_score": 50,
        "utilization_score_explanation": "Score parcial — análisis estratégico requiere revisión manual.",
    }


# ── Main entry point ─────────────────────────────────────────────────────


def build_treatment(treatment_rx: str, policy_year_start: date) -> TreatmentSchedule:
    """The treatment schedule from the drug catalog, or the handover's generic fallback.

    Args:
        treatment_rx: The prescription.
        policy_year_start: The projection start.

    Returns:
        TreatmentSchedule: The therapy.
    """
    dc = get_drug(treatment_rx)
    if dc:
        return TreatmentSchedule(
            drug_name=dc["generic_name"],
            brand_name=dc["brand_name"],
            dose_mg=dc["dose_mg"],
            frequency_days=dc["frequency_days"],
            route=dc["route"],
            unit_cost_mxn=dc["unit_cost_mxn"],
            loading_doses=dc["loading_doses"],
            loading_units_per_dose=dc.get("loading_units_per_dose", 1) or 1,
            start_date=policy_year_start.isoformat(),
            cofepris_registration=dc.get("cofepris_registration", ""),
            psp_program_name=dc.get("psp_program_name", ""),
            psp_copay_bridge_pct=dc.get("psp_bridge_pct", 0),
        )
    # Fallback for unknown drugs
    return TreatmentSchedule(
        drug_name=treatment_rx,
        brand_name=treatment_rx,
        dose_mg=300,
        frequency_days=14,
        route="SC",
        unit_cost_mxn=15000,
        loading_doses=0,
        start_date=policy_year_start.isoformat(),
    )


async def generate_financial_roadmap(
    ctx: AgentContext,
    policy: dict[str, Any],
    patient_id: str,
    carrier: str,
    treatment_rx: str,
    months_insured: int,
    deducible: float = 15000.0,
    coaseguro_pct: float = 10.0,
    tope_coaseguro: Optional[float] = None,
    policy_year_start: Optional[date] = None,
    programacion_done: bool = False,
) -> dict[str, Any]:
    """Generate complete financial roadmap for a patient on biologic therapy.

    Args:
        ctx: The run.
        policy: The parsed policy.
        patient_id: The console's patient id.
        carrier: The carrier.
        treatment_rx: The prescription.
        months_insured: Tenure.
        deducible: The deducible.
        coaseguro_pct: The coaseguro.
        tope_coaseguro: The tope, when the operator gave one.
        policy_year_start: The policy year start; today when not given.
        programacion_done: Whether programación de pago directo is scheduled.

    Returns:
        dict: The roadmap, with the handover's keys.
    """
    rules = CARRIER_FINANCIAL_RULES.get(carrier.upper(), {})

    # Resolve tope from policy or carrier defaults
    tope: float
    if tope_coaseguro is not None:
        tope = float(tope_coaseguro)
    else:
        pol_tope = policy.get("financial", {}).get("tope_coaseguro")
        if isinstance(pol_tope, (int, float)) and not isinstance(pol_tope, bool):
            tope = float(pol_tope)
        else:
            tope = float(rules.get("tope_coaseguro_default", 30000))

    # Resolve pago directo coaseguro.
    # FIX (MetLife 0%): the handover applied the programación rate to every
    # MetLife patient. It applies only once programación is scheduled; until
    # then the projection uses the policy's coaseguro.
    pago_directo_pct = rules.get("pago_directo_coaseguro_pct") if programacion_done else None

    # Policy year
    py_start = policy_year_start or ctx.today
    py_end = add_months(py_start, 12)

    treatment = build_treatment(treatment_rx, py_start)

    # ── DETERMINISTIC: Monthly projections ────────────────────────
    projections = calculate_monthly_projections(
        treatment=treatment,
        deducible=deducible,
        coaseguro_pct=coaseguro_pct,
        tope_coaseguro=tope,
        pago_directo_coaseguro_pct=pago_directo_pct,
        policy_year_start=py_start,
        months=12,
    )

    # Find tope month
    tope_month = next((p["month"] for p in projections if p["tope_reached"]), None)

    # Totals
    drug_annual = sum(p["drug_cost_mxn"] for p in projections)
    patient_annual = sum(p["patient_net_mxn"] for p in projections)
    carrier_annual = sum(p["carrier_pays_mxn"] for p in projections)
    psp_annual = sum(p["psp_bridge_mxn"] for p in projections)
    deducible_paid = sum(p["deducible_mxn"] for p in projections)

    # No-optimization comparison
    no_opt_cost = calculate_no_optimization_cost(treatment, coaseguro_pct, tope, deducible, py_start)
    savings = no_opt_cost - patient_annual

    # ── LLM: Strategic analysis ───────────────────────────────────
    strategic = await generate_strategic_analysis(
        ctx,
        projections=projections,
        carrier=carrier,
        treatment=treatment,
        patient_months_insured=months_insured,
        tope_reached_month=tope_month,
    )

    # ── BUILD ROADMAP ─────────────────────────────────────────────
    return {
        "patient_id": patient_id,
        "carrier": carrier,
        "treatment": {
            "drug": treatment.drug_name,
            "brand": treatment.brand_name,
            "dose_mg": treatment.dose_mg,
            "frequency_days": treatment.frequency_days,
            "unit_cost_mxn": treatment.unit_cost_mxn,
            "psp_program": treatment.psp_program_name,
        },
        "policy_year": {
            "start": py_start.isoformat(),
            "end": py_end.isoformat(),
        },
        "financial_summary": {
            "deducible": deducible,
            "deducible_paid": round(deducible_paid, 2),
            "coaseguro_pct": pago_directo_pct if pago_directo_pct is not None else coaseguro_pct,
            "coaseguro_pct_without_optimization": coaseguro_pct,
            "tope_coaseguro": tope,
            "tope_reached_month": tope_month,
            "tope_reached_date": projections[tope_month - 1]["date"] if tope_month else None,
            "months_remaining_free": (12 - tope_month) if tope_month else 0,
            "drug_cost_annual_mxn": round(drug_annual, 2),
            "patient_cost_annual_mxn": round(patient_annual, 2),
            "carrier_cost_annual_mxn": round(carrier_annual, 2),
            "psp_bridge_annual_mxn": round(psp_annual, 2),
            "cost_without_optimization_mxn": no_opt_cost,
            "savings_from_optimization_mxn": round(savings, 2),
        },
        "monthly_projections": projections,
        "strategic_analysis": strategic,
        "optimization_tips": strategic.get("optimization_tips", []),
        "bundling_opportunities": strategic.get("bundling_opportunities", BUNDLING_SERVICES),
        "renewal_projection": strategic.get("renewal_projection", {}),
        "utilization_score": strategic.get("utilization_score", 0),
        "utilization_score_explanation": strategic.get("utilization_score_explanation", ""),
        "tax_deduction_note": strategic.get("tax_deduction_note", ""),
        "_privacy": "Pseudonymized per LFPDPPP. No PII in this document.",
    }
