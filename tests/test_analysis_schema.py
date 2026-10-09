"""The analysis contract: only what the navigator uses, and the prompt that asks for it."""

from app.core.config import settings
from app.core.prompts import (
    available_versions,
    load_critique_prompt,
    load_extraction_prompt,
)
from app.schemas.insurance import (
    CAMPO_SECTIONS,
    AnalisisGMM,
)

# Every value the navigation intake form is prefilled from (see the console's
# `navigationIntake.ts`), by schema path.
NAVIGATOR_FIELDS = {
    "identificacion.aseguradora",
    "identificacion.vigencia_inicio",
    "estructura_financiera.deducible",
    "estructura_financiera.coaseguro_porcentaje",
    "estructura_financiera.tope_coaseguro",
    "preexistencias_continuidad.antiguedad",
}


def _campo_paths() -> set[str]:
    analysis = AnalisisGMM()
    return {
        f"{section}.{field}" for section in CAMPO_SECTIONS for field in type(getattr(analysis, section)).model_fields
    }


def test_the_analysis_extracts_exactly_the_navigator_fields():
    assert _campo_paths() == NAVIGATOR_FIELDS
    assert set(AnalisisGMM.model_fields) == {
        *CAMPO_SECTIONS,
        "resumen_es",
        "summary_en",
        "confianza_global",
        "notas_calidad_documento",
    }


def test_a_run_stored_under_the_wider_v2_schema_still_opens():
    stored = {
        "identificacion": {
            "aseguradora": {"valor": "MetLife México", "confianza": "alta", "evidencia": "MetLife México S.A."},
            "registro_cnsf": {"valor": "CNSF-S0025-0123-2019", "confianza": "alta"},
        },
        "alcance_cobertura": {"biologicos_cubiertos": {"valor": "Sí", "confianza": "media"}},
        "hallazgos": [
            {"severidad": "critica", "categoria": "cobertura", "descripcion_es": "x", "description_en": "x"}
        ],
        "resumen_es": "Póliza GMM de MetLife.",
    }
    analysis = AnalisisGMM.model_validate(stored)
    assert analysis.identificacion.aseguradora.valor == "MetLife México"
    assert analysis.resumen_es == "Póliza GMM de MetLife."
    assert "hallazgos" not in analysis.model_dump()


def test_the_configured_prompt_is_runnable_and_names_every_field():
    assert settings.ANALYSIS_PROMPT_VERSION in available_versions()
    extraction = load_extraction_prompt("CARÁTULA", version=settings.ANALYSIS_PROMPT_VERSION)
    critique = load_critique_prompt("CARÁTULA", "{}", version=settings.ANALYSIS_PROMPT_VERSION)
    for path in NAVIGATOR_FIELDS:
        assert path.split(".")[1] in extraction
    # A retired section named in the wording pairs prose for one contract with
    # a schema for another.
    for retired in ("alcance_cobertura", "mecanismos_disputa", "hallazgos", "registro_cnsf"):
        assert retired not in extraction
        assert retired not in critique
