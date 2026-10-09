"""The drug catalog and its price freshness gate.

Ported from the handover's ``config/drug_catalog.py`` and ``config/price_gate.py``.
The catalog entries are the handover's, with two fields added:

- ``biologic`` — FIX (JAK inhibitors): the planner's biologic check listed
  ``upadacitinib`` and ``abrocitinib``, so an AXA patient on an oral JAK
  inhibitor was told the therapy was excluded as a biológico. It is a small
  molecule; the exclusion does not reach it.
- ``loading_units_per_dose`` — FIX (loading-dose units): Nemluvio's day-0 dose is
  60 mg, two 30 mg units, and the handover priced it as one.

The price gate no longer prompts on a terminal or writes ``price_overrides.yaml``
— the service's filesystem is read-only. A stale price is reported in the
navigation's warnings instead.
"""

from dataclasses import dataclass
from datetime import date
from typing import (
    Any,
    Optional,
)

DRUG_CATALOG: dict[str, dict[str, Any]] = {
    "nemolizumab": {
        # Nemluvio (Galderma) — anti-IL-31RA mAb, AD moderada-severa + prurigo nodularis
        "generic_name": "nemolizumab",
        "brand_name": "Nemluvio",
        "manufacturer": "Galderma",
        "cofepris_holder": "Galderma",
        "cofepris_registration": "COFEPRIS/2024/SSA/GALDERMA",  # placeholder — verify
        "indication": "Dermatitis atópica moderada a severa en adultos; prurigo nodularis",
        "icd10": ["L20.9", "L20.0", "L20.8", "L28.1"],
        "mechanism": "Anti-IL-31RA monoclonal antibody",
        "biologic": True,
        # ── Dosing (per Galderma label, AD adult) ──
        "dose_mg": 30,  # maintenance dose
        "route": "SC",
        "frequency_days": 28,  # Q4W maintenance
        "loading_doses": 1,  # single 60mg loading on day 0
        "loading_units_per_dose": 2,  # the 60mg loading dose is two 30mg units
        "loading_schedule_days": [0],
        "maintenance_start_day": 28,
        # ── Pricing (MXN, 2026) ──
        "unit_cost_mxn": 30000,  # per 30mg maintenance dose
        "monthly_cost_mxn": 30000,  # 1 dose/month at maintenance (Q4W)
        "loading_month_cost_mxn": 60000,  # month 1: 60mg loading + 30mg
        # ── Price provenance (drives freshness gate in orchestrator) ──
        "price_source": "Internal estimate — Galderma MX list price not yet published",
        "price_verified_at": "2026-05-22",
        "price_list_url": "",
        "price_max_age_days": 30,
        "price_points": {
            "list_mxn": 30000,
            "psp_discount_mxn": None,  # filled when Galderma PSP confirms
            "compassionate_mxn": None,  # filled when acceso compasivo confirmed
        },
        # ── PSP Program ──
        "psp_program_name": "ADLuvio",
        "psp_sponsor": "Galderma",
        "psp_phone": "",  # fill when available
        "psp_bridge_pct": 0,  # % of coaseguro PSP covers (0 = none confirmed)
        "psp_services": [
            "Soporte de adherencia al tratamiento",
            "Coordinación de entregas de medicamento",
            "Seguimiento de respuesta clínica (prurito + lesiones)",
        ],
        # ── Clinical ──
        "step_therapy_required": True,
        "prior_therapies_min": 2,
        "monitoring_labs": ["BH", "QS", "PFH", "IgE", "eosinófilos"],
        "monitoring_frequency_months": 3,
        "clinical_scores": ["EASI", "SCORAD", "DLQI", "PP-NRS"],  # PP-NRS for pruritus
        "score_frequency_months": 6,
        "photo_frequency_months": 3,
    },
    "dupilumab": {
        "generic_name": "dupilumab",
        "brand_name": "Dupixent",
        "manufacturer": "Sanofi / Regeneron",
        "cofepris_holder": "Sanofi-Aventis de México",
        "cofepris_registration": "COFEPRIS/2019/042/0001",
        "indication": "Dermatitis atópica moderada a severa en adultos y adolescentes",
        "icd10": ["L20.9", "L20.0", "L20.8"],
        "mechanism": "Anti-IL-4/IL-13 dual monoclonal antibody",
        "biologic": True,
        # ── Dosing ──
        "dose_mg": 300,
        "route": "SC",
        "frequency_days": 14,
        "loading_doses": 2,  # 600mg on day 0 (2x300mg syringes)
        "loading_units_per_dose": 1,
        "loading_schedule_days": [0],  # both doses on day 1
        "maintenance_start_day": 14,
        # ── Pricing (MXN, 2026) ──
        "unit_cost_mxn": 19000,
        "monthly_cost_mxn": 38000,
        "loading_month_cost_mxn": 57000,  # month 1: 3 doses (2 loading + 1 maintenance)
        # ── PSP Program ──
        "psp_program_name": "Dupixent MyWay",
        "psp_sponsor": "Sanofi",
        "psp_phone": "800-849-0631",
        "psp_bridge_pct": 0,
        "psp_services": [
            "Evaluación socioeconómica para apoyo en copago",
            "Enfermera a domicilio para primeras aplicaciones",
            "Seguimiento de adherencia telefónico",
        ],
        # ── Clinical ──
        "step_therapy_required": True,
        "prior_therapies_min": 2,
        "monitoring_labs": ["BH", "QS", "PFH", "IgE", "eosinófilos"],
        "monitoring_frequency_months": 3,
        "clinical_scores": ["EASI", "SCORAD", "DLQI"],
        "score_frequency_months": 6,
        "photo_frequency_months": 3,
    },
    "upadacitinib": {
        "generic_name": "upadacitinib",
        "brand_name": "Rinvoq",
        "manufacturer": "AbbVie",
        "cofepris_holder": "AbbVie de México",
        "cofepris_registration": "COFEPRIS/2021/SSA/ABBVIE",
        "indication": "Dermatitis atópica moderada a severa en adultos",
        "icd10": ["L20.9", "L20.0", "L20.8"],
        "mechanism": "JAK1 selective inhibitor (oral)",
        "biologic": False,
        # ── Dosing ──
        "dose_mg": 30,
        "route": "PO",
        "frequency_days": 1,  # daily oral
        "loading_doses": 0,
        "loading_units_per_dose": 0,
        "loading_schedule_days": [],
        "maintenance_start_day": 0,
        # ── Pricing (MXN, 2026) ──
        "unit_cost_mxn": 733,  # per tablet (~22K/month)
        "monthly_cost_mxn": 22000,
        "loading_month_cost_mxn": 22000,
        # ── PSP Program ──
        "psp_program_name": "AbbVie Care",
        "psp_sponsor": "AbbVie",
        "psp_phone": "",
        "psp_bridge_pct": 0,
        "psp_services": [],
        # ── Clinical ──
        "step_therapy_required": True,
        "prior_therapies_min": 1,
        "monitoring_labs": ["BH", "QS", "PFH", "perfil lipídico", "CPK"],
        "monitoring_frequency_months": 3,
        "clinical_scores": ["EASI", "SCORAD", "DLQI"],
        "score_frequency_months": 6,
        "photo_frequency_months": 3,
    },
    "abrocitinib": {
        "generic_name": "abrocitinib",
        "brand_name": "Cibinqo",
        "manufacturer": "Pfizer",
        "cofepris_holder": "Pfizer de México",
        "cofepris_registration": "COFEPRIS/2022/SSA/PFIZER",
        "indication": "Dermatitis atópica moderada a severa en adultos",
        "icd10": ["L20.9", "L20.0", "L20.8"],
        "mechanism": "JAK1 selective inhibitor (oral)",
        "biologic": False,
        # ── Dosing ──
        "dose_mg": 200,
        "route": "PO",
        "frequency_days": 1,
        "loading_doses": 0,
        "loading_units_per_dose": 0,
        "loading_schedule_days": [],
        "maintenance_start_day": 0,
        # ── Pricing (MXN, 2026) ──
        "unit_cost_mxn": 667,
        "monthly_cost_mxn": 20000,
        "loading_month_cost_mxn": 20000,
        # ── PSP Program ──
        "psp_program_name": "",
        "psp_sponsor": "Pfizer",
        "psp_phone": "",
        "psp_bridge_pct": 0,
        "psp_services": [],
        # ── Clinical ──
        "step_therapy_required": True,
        "prior_therapies_min": 1,
        "monitoring_labs": ["BH", "QS", "PFH", "perfil lipídico"],
        "monitoring_frequency_months": 3,
        "clinical_scores": ["EASI", "SCORAD", "DLQI"],
        "score_frequency_months": 6,
        "photo_frequency_months": 3,
    },
}


def get_drug(treatment_rx: str) -> Optional[dict[str, Any]]:
    """Look up drug config from a free-text treatment_rx string.

    Examples:
        get_drug("nemolizumab 30mg SC Q4W")          → DRUG_CATALOG["nemolizumab"]
        get_drug("Nemluvio 30mg cada 4 semanas")     → DRUG_CATALOG["nemolizumab"]
        get_drug("Dupilumab 300mg SC Q2W")           → DRUG_CATALOG["dupilumab"]

    Args:
        treatment_rx: The prescription as typed.

    Returns:
        Optional[dict]: The catalog entry, or None when nothing matches.
    """
    rx_lower = (treatment_rx or "").lower()

    # Try generic name first
    for generic, config in DRUG_CATALOG.items():
        if generic in rx_lower:
            return config

    # Try brand name
    for config in DRUG_CATALOG.values():
        if config["brand_name"].lower() in rx_lower:
            return config

    # Try PSP program name
    for config in DRUG_CATALOG.values():
        if config["psp_program_name"] and config["psp_program_name"].lower() in rx_lower:
            return config

    return None


@dataclass(frozen=True)
class PriceCheck:
    """The price a navigation uses, and whether it is still fresh.

    Attributes:
        drug_key: Catalog key.
        monthly_cost_mxn: A maintenance month.
        loading_month_cost_mxn: The loading month.
        unit_cost_mxn: One maintenance dose.
        source: Where the price came from.
        verified_at: When it was last checked, or ``unknown``.
        stale: Older than the catalog allows.
    """

    drug_key: str
    monthly_cost_mxn: int
    loading_month_cost_mxn: int
    unit_cost_mxn: int
    source: str
    verified_at: str
    stale: bool


def get_effective_price(drug_key: str, catalog_entry: dict[str, Any], today: date) -> PriceCheck:
    """Resolve the effective price for a drug.

    Args:
        drug_key: The generic name.
        catalog_entry: Its catalog entry.
        today: The navigation date.

    Returns:
        PriceCheck: The price and its freshness.
    """
    verified_at = catalog_entry.get("price_verified_at")
    max_age = catalog_entry.get("price_max_age_days", 30)

    stale = False
    if verified_at:
        try:
            stale = (today - date.fromisoformat(verified_at)).days > max_age
        except ValueError:
            stale = True

    return PriceCheck(
        drug_key=drug_key,
        monthly_cost_mxn=int(catalog_entry["monthly_cost_mxn"]),
        loading_month_cost_mxn=int(catalog_entry["loading_month_cost_mxn"]),
        unit_cost_mxn=int(catalog_entry["unit_cost_mxn"]),
        source=catalog_entry.get("price_source", "catalog baseline"),
        verified_at=verified_at or "unknown",
        stale=stale,
    )
