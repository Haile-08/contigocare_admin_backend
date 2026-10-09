"""InnovaDerm Navigator — Agent 2: Action Planner.

Ported from the handover's ``agents/planner_agent.py``. Same safety checks, same
prompts, same post-processing: safety alerts prepended, urgency forced to
critical by a hard rule, baseline documents added, cost figures overwritten
from the catalog.

FIX (JAK inhibitors): the biologic check read the treatment against a keyword
list that included ``abrocitinib`` and ``upadacitinib``. It now asks the drug
catalog, which knows they are small molecules; the keyword list still covers a
therapy the catalog does not carry.
"""

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
from app.core.navigator.drug_catalog import (
    PriceCheck,
    get_drug,
    get_effective_price,
)

SYSTEM_PROMPT = """Eres el Planificador de Acciones InnovaDerm — experto en navegación de
seguros GMM mexicanos para pacientes de dermatología de alta especialidad que buscan
terapia biológica.

Tu función es generar un plan de acción preciso y específico por aseguradora para un
paciente con dermatitis atópica (u otras condiciones dermatológicas) que busca cobertura
de biológicos.

IMPORTANTE: Toda tu salida debe estar en español mexicano (ES-MX).

Tienes experiencia profunda en:
- AXA: biológicos excluidos → Protocolo de Brecha de Cobertura
- GNP: vía de programación de tratamientos
- MetLife: programación pago directo → 0% coaseguro
- SMNYL: Segunda Valoración + apelaciones CONAMED + tope $100K

REGLAS CRÍTICAS:
1. Siempre verificar el plazo de notificación de 5 días PRIMERO
2. Pacientes AXA con Rx biológico → Protocolo de Brecha de Cobertura inmediatamente
3. Pacientes MetLife → verificar programación pago directo agendada ANTES de primera dosis
4. Pacientes SMNYL con piel → preparar documentación de Segunda Valoración proactivamente
5. Señalar implicaciones de padecimiento preexistente por aseguradora
6. Generar máximo 8 pasos numerados — priorizados por urgencia
7. Incluir fechas límite específicas en formato ISO cuando sea calculable
8. Devolver ÚNICAMENTE JSON válido — sin prosa, sin markdown

Devuelve action_plan JSON con: steps[], deadlines{}, docs_checklist[],
carrier_alerts[], cost_projection{}, y appeal_pathway si es relevante."""

# The handover's keyword list, without the two oral JAK inhibitors. Used only
# for a therapy the catalog does not carry.
BIOLOGIC_KEYWORDS = (
    "dupilumab",
    "biológico",
    "biologico",
    "biologic",
    "nemolizumab",
    "nemluvio",
    "tralokinumab",
)


@dataclass
class PatientProfile:
    """The patient, as the planner reads it."""

    carrier: str
    diagnosis_icd10: str  # e.g., "L20.9" for AD
    treatment_rx: str  # e.g., "dupilumab 300mg Q2W"
    preexisting: bool
    months_insured: int
    rider_preexisting: bool  # SMNYL specific
    programacion_done: bool  # MetLife/GNP specific
    notification_sent: bool
    days_since_incidence: int
    policy_age_days: int
    denial_reason: Optional[str] = None


def is_biologic(treatment_rx: str) -> bool:
    """Whether the prescribed therapy is a biológico.

    Args:
        treatment_rx: The prescription.

    Returns:
        bool: True for a biológico.
    """
    drug = get_drug(treatment_rx)
    if drug is not None:
        return bool(drug.get("biologic"))
    return any(keyword in (treatment_rx or "").lower() for keyword in BIOLOGIC_KEYWORDS)


def run_safety_checks(patient: PatientProfile, carrier: str, today: date) -> tuple[list[str], bool]:
    """The hard-coded safety checks (pre-API — never LLM-generated).

    Args:
        patient: The patient.
        carrier: ``meta.carrier`` upper-cased.
        today: The run date.

    Returns:
        tuple: The alerts, highest priority first, and whether urgency is forced
        to critical.
    """
    safety_alerts: list[str] = []
    force_critical = False
    biologic = is_biologic(patient.treatment_rx)

    # CHECK 1: AXA + biologic Rx → Coverage Gap Protocol
    if carrier == "AXA" and biologic:
        safety_alerts.append(
            "🚨 AXA EXCLUYE MEDICAMENTOS BIOLÓGICOS. Activar Protocolo de Brecha "
            "de Cobertura: (1) documentar registro COFEPRIS + necesidad médica, "
            "(2) solicitar arbitraje médico privado citando necesidad clínica, "
            "(3) escalar a Condusef simultáneamente, (4) contactar laboratorio "
            "para programa de apoyo PSP."
        )
        force_critical = True

    # CHECK 2: MetLife + programación not done → block first dose
    if carrier == "METLIFE" and not patient.programacion_done:
        safety_alerts.append(
            "🚨 MetLife: Programar pago directo ANTES de primera administración — "
            "no retroactivo. Sin programación, el paciente pierde el beneficio de "
            "0% coaseguro permanentemente para este ciclo de tratamiento."
        )

    # CHECK 3: Notification deadline expired or imminent
    if not patient.notification_sent:
        if patient.days_since_incidence >= 5:
            safety_alerts.insert(
                0,
                "🚨 PLAZO DE NOTIFICACIÓN DE 5 DÍAS VENCIDO. La aseguradora puede "
                "reducir o negar la indemnización conforme a la Ley sobre el Contrato "
                "de Seguro. Enviar notificación inmediatamente y documentar la fecha.",
            )
            force_critical = True
        elif patient.days_since_incidence >= 3:
            safety_alerts.insert(
                0,
                f"⚠️ URGENTE: Quedan {5 - patient.days_since_incidence} día(s) para "
                "enviar notificación escrita de siniestro. Redactar y enviar carta hoy.",
            )

    # CHECK 4: AXA 30-day rule — block all claims
    if carrier == "AXA" and patient.policy_age_days < 30:
        safety_alerts.insert(
            0,
            f"🚨 REGLA 30 DÍAS AXA: Póliza tiene {patient.policy_age_days} días de "
            f"vigencia. NO presentar reclamación — cualquier padecimiento será "
            f"clasificado como preexistente. Esperar hasta el día 31 "
            f"({(today + timedelta(days=30 - patient.policy_age_days)).strftime('%Y-%m-%d')}).",
        )
        force_critical = True

    # CHECK 5: SMNYL + preexisting + no rider → recommend purchase
    if carrier == "SMNYL" and patient.preexisting and not patient.rider_preexisting:
        safety_alerts.append(
            "💡 SMNYL: Paciente con padecimiento preexistente SIN rider de cobertura "
            "adicional. Recomendar contratar el rider 'Padecimientos Preexistentes' "
            "antes de solicitar cobertura — otorga cobertura desde día 1. Sin rider, "
            "el padecimiento queda permanentemente excluido."
        )

    return safety_alerts, force_critical


async def generate_action_plan(ctx: AgentContext, policy: dict[str, Any], patient: PatientProfile) -> dict[str, Any]:
    """Generate carrier-specific action plan for biologic therapy coverage.

    Args:
        ctx: The run.
        policy: Normalized policy dict from Parser Agent.
        patient: Patient profile.

    Returns:
        dict: Action plan with steps, deadlines, docs, alerts.
    """
    carrier = (policy.get("meta", {}).get("carrier") or "Unknown").upper()
    today = ctx.today

    safety_alerts, force_critical = run_safety_checks(patient, carrier, today)

    # Pre-compute critical dates
    notification_deadline = today + timedelta(days=max(0, 5 - patient.days_since_incidence))
    preauth_deadline = today + timedelta(days=5)  # min 5 days before treatment

    # Build carrier intelligence summary for prompt
    carrier_intel = _build_carrier_intel(policy, carrier)

    # ─── AUTHORITATIVE DRUG PRICING (deterministic — never let LLM guess) ──
    drug_cfg = get_drug(patient.treatment_rx)
    price: Optional[PriceCheck]
    if drug_cfg:
        price = get_effective_price(drug_cfg["generic_name"], drug_cfg, today)
        drug_pricing_block = (
            f"AUTHORITATIVE DRUG PRICING — USE THESE EXACT NUMBERS, DO NOT ESTIMATE:\n"
            f"- Drug: {drug_cfg['brand_name']} ({drug_cfg['generic_name']})\n"
            f"- Monthly cost (maintenance): ${price.monthly_cost_mxn:,} MXN\n"
            f"- Loading month cost: ${price.loading_month_cost_mxn:,} MXN\n"
            f"- Per-dose cost: ${price.unit_cost_mxn:,} MXN\n"
            f"- Source: {price.source} (verified {price.verified_at})\n"
            f"Any monthly cost figure you mention in narrative text MUST use ${price.monthly_cost_mxn:,} MXN. "
            f"Numeric fields in cost_projection will be overwritten deterministically."
        )
    else:
        price = None
        drug_pricing_block = "DRUG PRICING: Not in catalog. Mark cost_projection numeric fields as null."

    user_prompt = f"""Generate an action plan for this patient. Output valid JSON only.

TODAY: {today.strftime("%Y-%m-%d")}
NOTIFICATION DEADLINE: {notification_deadline.strftime("%Y-%m-%d")}
PREAUTH SUBMIT BY: {preauth_deadline.strftime("%Y-%m-%d")}

PATIENT PROFILE:
- Carrier: {patient.carrier}
- Diagnosis: {patient.diagnosis_icd10} (Atopic Dermatitis)
- Treatment: {patient.treatment_rx}
- Preexisting condition: {patient.preexisting}
- Months insured: {patient.months_insured}
- SMNYL rider active: {patient.rider_preexisting}
- Programación scheduled: {patient.programacion_done}
- 5-day notification sent: {patient.notification_sent}
- Days since incidence: {patient.days_since_incidence}
- Policy age (days): {patient.policy_age_days}
- Denial reason: {patient.denial_reason or "None — first request"}

{drug_pricing_block}

POLICY INTELLIGENCE:
{carrier_intel}

Generate action_plan JSON with these exact keys:
{{
  "carrier": "",
  "urgency_level": "critical|high|medium|low",
  "summary": "",
  "steps": [
    {{
      "step": 1,
      "title": "",
      "action": "",
      "deadline": "YYYY-MM-DD or null",
      "owner": "patient|doctor|psp_coordinator",
      "docs_needed": [],
      "carrier_specific_note": ""
    }}
  ],
  "deadlines": {{
    "notification": "YYYY-MM-DD",
    "preauth_submit": "YYYY-MM-DD",
    "first_dose_earliest": "YYYY-MM-DD"
  }},
  "docs_checklist": {{
    "clinical": [],
    "insurance": [],
    "carrier_specific": []
  }},
  "carrier_alerts": [],
  "cost_projection": {{
    "deducible": "from carátula",
    "coaseguro_pct": null,
    "tope_coaseguro": null,
    "monthly_drug_cost_estimate_mxn": null,
    "patient_monthly_estimate_mxn": null,
    "optimization_tip": ""
  }},
  "appeal_pathway": null
}}"""

    plan = await ctx.json("planner", user_prompt, system=SYSTEM_PROMPT)
    if plan is None:
        # The handover returned this plan and stopped. The safety alerts, the
        # baseline documents and the catalog prices are applied to it below all
        # the same: they were computed before the call so that a failed call
        # could never hide them.
        plan = {
            "carrier": carrier,
            "urgency_level": "high",
            "summary": "Plan generation error — manual review required",
            "_error": "Action plan generation failed",
            "steps": [],
            "carrier_alerts": ["SYSTEM ERROR: Action plan generation failed"],
        }

    # Inject pre-API safety alerts and enforce urgency override
    plan = _inject_safety_checks(plan, safety_alerts, force_critical)

    # Ensure baseline docs are always present in checklist
    plan = _ensure_baseline_docs(plan)

    # Deterministic overwrite of cost_projection numeric fields — never trust LLM for money.
    return _enforce_deterministic_pricing(plan, price)


def _enforce_deterministic_pricing(plan: dict[str, Any], price: Optional[PriceCheck]) -> dict[str, Any]:
    """Overwrite LLM-generated cost figures with catalog/override truth.

    Args:
        plan: The plan.
        price: The catalog price, or None for a therapy outside the catalog.

    Returns:
        dict: The plan.
    """
    if not price:
        return plan
    cp = plan.get("cost_projection")
    if not isinstance(cp, dict):
        cp = {}
        plan["cost_projection"] = cp
    cp["monthly_drug_cost_estimate_mxn"] = price.monthly_cost_mxn
    cp["loading_month_cost_mxn"] = price.loading_month_cost_mxn
    cp["unit_cost_mxn"] = price.unit_cost_mxn
    cp["price_source"] = price.source
    cp["price_verified_at"] = price.verified_at
    return plan


def _build_carrier_intel(policy: dict[str, Any], carrier: str) -> str:
    """Build carrier intelligence summary for planner prompt.

    Args:
        policy: The parsed policy.
        carrier: Upper-cased carrier.

    Returns:
        str: One line per relevant flag.
    """
    intel_lines = []

    # Financial
    fin = policy.get("financial", {})
    if fin.get("tope_coaseguro"):
        intel_lines.append(f"Tope coaseguro: {fin['tope_coaseguro']}")

    # Coverage
    cov = policy.get("coverage", {})
    if cov.get("biologics_covered") is False:
        intel_lines.append("⚠️ BIOLOGICS EXPLICITLY EXCLUDED")
    if cov.get("pago_directo_meds"):
        intel_lines.append("✅ Pago directo available for medications")
    if cov.get("coaseguro_meds_outpatient") == 0:
        intel_lines.append("⭐ 0% coaseguro on outpatient meds (programación)")

    # Preexisting
    pre = policy.get("preexisting", {})
    if pre.get("coverage_after_months"):
        intel_lines.append(f"Preexisting covered after: {pre['coverage_after_months']} months")
    if pre.get("optional_rider_available"):
        intel_lines.append("✅ Optional preexisting rider available")
    if pre.get("thirty_day_rule"):
        intel_lines.append("⚠️ 30-day rule applies (AXA) — no claims first 30 days")

    # Dermatology
    derm = policy.get("dermatology", {})
    if derm.get("biologics_excluded"):
        intel_lines.append("❌ Biologic medications excluded")
    if derm.get("derm_products_excluded"):
        intel_lines.append("❌ Dermatological products excluded")
    if derm.get("skin_lesions_segunda_val"):
        intel_lines.append("⚠️ Segunda Valoración required for skin lesions")

    # Appeals
    appeals = policy.get("appeals", {})
    if appeals.get("arbitration_body") == "CONAMED":
        intel_lines.append("✅ CONAMED arbitration (binding, free)")
    if appeals.get("une_suspends_statute"):
        intel_lines.append("⭐ UNE filing suspends statute of limitations")

    return "\n".join(intel_lines) if intel_lines else "Standard coverage — no critical flags"


def _as_text_list(value: Any) -> list[str]:
    """A checklist section as strings, whatever shape the model gave it.

    Args:
        value: The model's list.

    Returns:
        list[str]: The entries.
    """
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, str) else str(item) for item in value]


def _ensure_baseline_docs(plan: dict[str, Any]) -> dict[str, Any]:
    """Ensure mandatory documentation items are always in the checklist.

    From KNOWLEDGE.md Module 6 Step 4, regardless of LLM output.

    Args:
        plan: The plan.

    Returns:
        dict: The plan with the baseline documents.
    """
    docs = plan.get("docs_checklist", {})
    if not isinstance(docs, dict):
        docs = {"clinical": [], "insurance": [], "carrier_specific": []}

    clinical = _as_text_list(docs.get("clinical", []))
    insurance = _as_text_list(docs.get("insurance", []))
    carrier_specific = _as_text_list(docs.get("carrier_specific", []))

    all_text = " ".join(clinical).lower() + " ".join(insurance).lower() + " ".join(carrier_specific).lower()

    # Clinical baseline (KNOWLEDGE.md Module 6 Step 4)
    baseline_clinical = {
        "EASI o SCORAD score (documentado por dermatólogo)": "easi" in all_text or "scorad" in all_text,
        "DLQI (índice de calidad de vida dermatológica)": "dlqi" in all_text or "calidad de vida" in all_text,
        "Registro fotográfico clínico de lesiones": "fotográfico" in all_text or "fotografía" in all_text,
        "Historial de tratamientos previos fallidos (mín. 2)": "tratamientos previos" in all_text
        or "fallidos" in all_text,
        "Diagnóstico confirmado (CIE-10: L20.x)": "cie-10" in all_text
        or "l20" in all_text
        or "diagnóstico" in all_text,
        "Carta de necesidad médica (biológico específico)": "necesidad médica" in all_text
        or "justificación" in all_text,
        "Registro COFEPRIS del medicamento": "cofepris" in all_text,
    }
    for doc, present in baseline_clinical.items():
        if not present:
            clinical.append(doc)

    # Insurance baseline
    baseline_insurance = {
        "Carátula de póliza vigente": "carátula" in all_text,
        "Aviso de Accidente o Enfermedad (formato de la aseguradora)": "aviso" in all_text,
        "Informe Médico (formato de la aseguradora, firmado por MD tratante)": "informe médico" in all_text,
        "Facturas CFDI originales de farmacia": "cfdi" in all_text,
        "Identificación oficial vigente": "identificación" in all_text or "ine" in all_text,
    }
    for doc, present in baseline_insurance.items():
        if not present:
            insurance.append(doc)

    docs["clinical"] = clinical
    docs["insurance"] = insurance
    docs["carrier_specific"] = carrier_specific
    plan["docs_checklist"] = docs
    return plan


def _inject_safety_checks(plan: dict[str, Any], safety_alerts: list[str], force_critical: bool) -> dict[str, Any]:
    """Inject pre-computed safety alerts into the LLM-generated plan.

    Safety alerts are prepended (highest priority first) so they always appear
    at the top regardless of what the LLM produced.

    Args:
        plan: The plan.
        safety_alerts: The pre-API alerts.
        force_critical: A hard rule requires critical urgency.

    Returns:
        dict: The plan.
    """
    llm_alerts = _as_text_list(plan.get("carrier_alerts", []))
    # Prepend safety alerts before any LLM-generated alerts
    plan["carrier_alerts"] = safety_alerts + llm_alerts

    # Override urgency if any safety check requires critical
    if force_critical:
        plan["urgency_level"] = "critical"

    return plan
