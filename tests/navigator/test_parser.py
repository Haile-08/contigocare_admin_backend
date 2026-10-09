"""The parser: the handover's prompt, input and carrier flags."""

import asyncio

from app.core.navigator.carriers import normalize_carrier
from app.core.navigator.parser_agent import (
    SCHEMA_TEMPLATE,
    apply_carrier_flags,
    build_policy_text,
    parse_policy,
)
from tests.navigator.helpers import (
    PARSED_METLIFE,
    context,
    scripted,
)


def test_carrier_names_map_onto_the_handover_spellings():
    assert normalize_carrier("MetLife México, S.A. de C.V.") == "MetLife"
    assert normalize_carrier("Seguros Monterrey New York Life") == "SMNYL"
    assert normalize_carrier("Grupo Nacional Provincial, S.A.B.") == "GNP"
    assert normalize_carrier("AXA Seguros") == "AXA"
    assert normalize_carrier("Zurich") == "Zurich"
    assert normalize_carrier("  ") is None


def test_policy_text_is_the_caratula_plus_the_carrier_cg_digest():
    text = build_policy_text("CARÁTULA REDACTADA", "MetLife")
    assert text.startswith("# FUENTE 1 — CARÁTULA\n\nCARÁTULA REDACTADA")
    assert "# FUENTE 2 — CONDICIONES GENERALES METLIFE" in text
    assert "InnovaDerm Digest — MetLife" in text
    # No digest was produced for SMNYL.
    assert "FUENTE 2" not in build_policy_text("x", "SMNYL")


def test_axa_biologics_flag():
    policy = apply_carrier_flags({"meta": {"carrier": "AXA Seguros, S.A. de C.V."}, "dermatology": {}})
    assert policy["meta"]["carrier"] == "AXA"
    assert policy["dermatology"]["biologics_excluded"] is True
    assert policy["_flags"] == ["AXA: biologics_excluded set to True per Phase 0 CG analysis"]


def test_metlife_and_smnyl_flags():
    metlife = apply_carrier_flags({"meta": {"carrier": "MetLife"}, "coverage": {}})
    assert metlife["_flags"] == ["MetLife: verify programación pago directo 0% coaseguro clause"]
    smnyl = apply_carrier_flags({"meta": {"carrier": "SMNYL"}, "financial": {"tope_coaseguro": None}})
    assert smnyl["_flags"] == ["SMNYL: tope_coaseguro expected $100,000 MXN — verify in carátula"]


def test_parse_sends_the_handover_prompts(monkeypatch):
    model = scripted(monkeypatch, {"parser": PARSED_METLIFE})
    policy = asyncio.run(parse_policy(context(), "POLICY BODY", carrier_hint="MetLife"))

    call = model.calls[0]
    assert call["system"].startswith("Eres el Parser de Pólizas InnovaDerm")
    assert "Extract all 45 fields from this GMM policy document." in call["prompt"]
    assert "Carrier hint: MetLife" in call["prompt"]
    assert "Policy number:" not in call["prompt"]
    assert "Set extraction_date to today: 2026-09-14" in call["prompt"]
    assert call["prompt"].endswith("POLICY TEXT:\nPOLICY BODY")
    assert policy["meta"]["carrier"] == "MetLife"


def test_failed_parse_returns_the_empty_template_with_the_hint(monkeypatch):
    scripted(monkeypatch, {"parser": None})
    policy = asyncio.run(parse_policy(context(), "POLICY BODY", carrier_hint="GNP"))
    assert policy["meta"]["confidence_score"] == 0.0
    assert policy["meta"]["carrier"] == "GNP"
    assert policy["_error"] == "JSON parsing failed — manual review required"
    # The template itself is untouched for the next run.
    assert SCHEMA_TEMPLATE["meta"]["carrier"] is None
