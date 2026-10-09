"""InnovaDerm Navigator — Agent 1: Policy Parser.

Ported from the handover's ``agents/parser_agent.py``. Same system prompt, same
user prompt, same 45-field template, same carrier flags.

Input: the handover's batch script (``run_batch_template.py``) fed the parser two
sources, the patient's carátula digest and the carrier's condiciones generales
digest. Here the first source is the console's redacted copy of the uploaded
policy and the second is the same CG digest the handover shipped.
"""

import copy
from typing import (
    Any,
    Optional,
)

from app.core.navigator.agent_calls import AgentContext
from app.core.navigator.carriers import (
    carrier_cg_digest,
    normalize_carrier,
)

SYSTEM_PROMPT = """Eres el Parser de Pólizas InnovaDerm — especialista en extraer datos
estructurados de documentos de pólizas de Gastos Médicos Mayores (GMM) en México.

Tu función es extraer campos normalizados de cualquier texto de póliza GMM y devolver
un objeto JSON válido. Trabajas con cuatro aseguradoras: AXA, GNP, MetLife, SMNYL.

IMPORTANTE: Todos los valores de texto extraídos deben estar en español mexicano (ES-MX).

CRÍTICO: Tu salida DEBE usar esta EXACTA estructura JSON anidada:

{
  "meta": {"carrier": "...", "policy_number": "...", "policy_type": "...", "extraction_date": "...", "confidence_score": 0.0},
  "financial": {"deducible_amount": null, "deducible_type": "...", "coaseguro_pct": null, "tope_coaseguro": null, "suma_asegurada": null, "moneda": "MXN", "periodo_poliza": null},
  "coverage": {"biologics_covered": null, "specialty_meds_covered": null, "pago_directo_available": null, "pago_directo_meds": null, "coaseguro_meds_outpatient": null, "programacion_required": null, "network_required": null},
  "preauthorization": {"required_for_surgery": null, "required_for_specialty_meds": null, "timeline_national_days": null, "timeline_international_days": null, "segunda_valoracion_required": null, "segunda_valoracion_triggers": [], "docs_required": []},
  "preexisting": {"excluded": null, "pathway_to_coverage": null, "coverage_after_months": null, "optional_rider_available": null, "thirty_day_rule": null, "definition": null},
  "dermatology": {"derm_products_excluded": null, "biologics_excluded": null, "cosmetic_excluded": null, "skin_lesions_segunda_val": null, "acne_excluded": null, "waiting_periods_derm": []},
  "appeals": {"notification_deadline_days": null, "notification_type": null, "preexisting_appeal_type": null, "arbitration_body": null, "arbitration_cost": null, "arbitration_binding": null, "une_name": null, "une_suspends_statute": null, "condusef_available": null, "settlement_days": null},
  "waiting_periods": {"maternity_months": null, "hiv_months": null, "custom": []}
}

REGLAS DE EXTRACCIÓN:
1. Nunca adivines valores — usa null si no está explícitamente declarado
2. confidence_score: 0.0-1.0 reflejando cuánto del esquema fue extraíble
3. Marca campos dependientes de carátula como null (deducible_amount, coaseguro_pct, suma_asegurada)
4. Extrae el nombre de la aseguradora del texto del documento
5. Devuelve ÚNICAMENTE JSON válido con la estructura anidada de arriba — sin prosa, sin markdown

REGLAS POR ASEGURADORA:
- AXA: Verificar cláusula de exclusión de "medicamentos biológicos"
- GNP: Verificar vía de "programación de tratamientos" para medicamentos de especialidad
- MetLife: Verificar "programación pago directo" y cláusula de 0% coaseguro
- SMNYL: Verificar rider de "Padecimientos Preexistentes" y requisito de "Segunda Valoración" para piel"""  # noqa: E501

SCHEMA_TEMPLATE: dict[str, Any] = {
    "meta": {
        "carrier": None,
        "policy_number": None,
        "policy_type": None,
        "extraction_date": None,
        "confidence_score": None,
    },
    "financial": {
        "deducible_amount": None,
        "deducible_type": None,
        "coaseguro_pct": None,
        "tope_coaseguro": None,
        "suma_asegurada": None,
        "moneda": None,
        "periodo_poliza": None,
    },
    "coverage": {
        "biologics_covered": None,
        "specialty_meds_covered": None,
        "pago_directo_available": None,
        "pago_directo_meds": None,
        "coaseguro_meds_outpatient": None,
        "programacion_required": None,
        "network_required": None,
    },
    "preauthorization": {
        "required_for_surgery": None,
        "required_for_specialty_meds": None,
        "timeline_national_days": None,
        "timeline_international_days": None,
        "segunda_valoracion_required": None,
        "segunda_valoracion_triggers": [],
        "docs_required": [],
    },
    "preexisting": {
        "excluded": None,
        "pathway_to_coverage": None,
        "coverage_after_months": None,
        "optional_rider_available": None,
        "thirty_day_rule": None,
        "definition": None,
    },
    "dermatology": {
        "derm_products_excluded": None,
        "biologics_excluded": None,
        "cosmetic_excluded": None,
        "skin_lesions_segunda_val": None,
        "acne_excluded": None,
        "waiting_periods_derm": [],
    },
    "appeals": {
        "notification_deadline_days": None,
        "notification_type": None,
        "preexisting_appeal_type": None,
        "arbitration_body": None,
        "arbitration_cost": None,
        "arbitration_binding": None,
        "une_name": None,
        "une_suspends_statute": None,
        "condusef_available": None,
        "settlement_days": None,
    },
    "waiting_periods": {"maternity_months": None, "hiv_months": None, "custom": []},
}

# Token safety limit, as in the handover.
POLICY_TEXT_LIMIT = 50000


def build_policy_text(caratula_text: str, carrier: Optional[str]) -> str:
    """Combine the carátula and the carrier CG digest into Parser input.

    The handover's ``run_batch_template.build_policy_text``.

    Args:
        caratula_text: The console's redacted copy of the uploaded policy.
        carrier: The handover's carrier spelling, when known.

    Returns:
        str: The text the parser reads.
    """
    parts = [f"# FUENTE 1 — CARÁTULA\n\n{caratula_text}\n"]
    digest = carrier_cg_digest(carrier) if carrier else None
    if carrier and digest:
        parts.append(f"# FUENTE 2 — CONDICIONES GENERALES {carrier.upper()}\n\n{digest}\n")
    return "\n".join(parts)


async def parse_policy(
    ctx: AgentContext,
    policy_text: str,
    carrier_hint: Optional[str] = None,
    policy_number: Optional[str] = None,
) -> dict[str, Any]:
    """Extract normalized fields from GMM policy text.

    Args:
        ctx: The run.
        policy_text: Policy text, already redacted.
        carrier_hint: Optional carrier name if known.
        policy_number: Never passed by the console — a policy number does not
            reach a model. Kept so the signature reads as the handover's.

    Returns:
        dict: Normalized policy dict with 45 fields.
    """
    carrier_context = f"\nCarrier hint: {carrier_hint}" if carrier_hint else ""
    policy_context = f"\nPolicy number: {policy_number}" if policy_number else ""

    user_prompt = f"""Extract all 45 fields from this GMM policy document.
{carrier_context}{policy_context}

Return the complete JSON schema with all fields populated or null.
Set extraction_date to today: {ctx.today.strftime("%Y-%m-%d")}

POLICY TEXT:
{policy_text[:POLICY_TEXT_LIMIT]}"""

    extracted = await ctx.json("parser", user_prompt, system=SYSTEM_PROMPT)
    if extracted is None:
        result = copy.deepcopy(SCHEMA_TEMPLATE)
        result["meta"]["extraction_date"] = ctx.today.strftime("%Y-%m-%d")
        result["meta"]["confidence_score"] = 0.0
        result["_error"] = "JSON parsing failed — manual review required"
        return apply_carrier_flags(result, carrier_hint)

    # Post-processing: apply carrier-specific critical flags
    return apply_carrier_flags(extracted, carrier_hint)


def apply_carrier_flags(policy: dict[str, Any], carrier_hint: Optional[str] = None) -> dict[str, Any]:
    """Apply carrier-specific intelligence flags from Phase 0 schema.

    Args:
        policy: The parsed policy.
        carrier_hint: The operator's carrier, used when the parser named none.

    Returns:
        dict: The policy with flags applied.
    """
    for section, fields in SCHEMA_TEMPLATE.items():
        existing = policy.get(section)
        if not isinstance(existing, dict):
            policy[section] = copy.deepcopy(fields)

    # The rules below compare against the handover's spellings.
    meta = policy["meta"]
    meta["carrier"] = normalize_carrier(meta.get("carrier")) or normalize_carrier(carrier_hint)
    carrier = (meta.get("carrier") or "").upper()

    if carrier == "AXA":
        # AXA always excludes biologics — flag if extraction missed it
        if policy.get("dermatology", {}).get("biologics_excluded") is None:
            policy["dermatology"]["biologics_excluded"] = True
            policy["_flags"] = policy.get("_flags", [])
            policy["_flags"].append("AXA: biologics_excluded set to True per Phase 0 CG analysis")

    if carrier == "METLIFE":
        # MetLife 0% coaseguro via programación pago directo
        if policy.get("coverage", {}).get("pago_directo_meds") is None:
            policy["_flags"] = policy.get("_flags", [])
            policy["_flags"].append("MetLife: verify programación pago directo 0% coaseguro clause")

    if carrier == "SMNYL":
        # SMNYL tope coaseguro should be $100,000 MXN
        tope = policy.get("financial", {}).get("tope_coaseguro")
        if tope is None:
            policy["_flags"] = policy.get("_flags", [])
            policy["_flags"].append("SMNYL: tope_coaseguro expected $100,000 MXN — verify in carátula")

    return policy
