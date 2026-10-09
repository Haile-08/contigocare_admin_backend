"""Builders and a scripted model for navigation tests."""

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from app.core.navigator import agent_calls
from app.core.navigator.agent_calls import AgentContext
from app.schemas.navigation import NavigationIntake
from app.services.llm import ModelCallError

TODAY = date(2026, 9, 14)  # a Monday


def intake(**overrides: Any) -> NavigationIntake:
    """A complete, unremarkable intake, with overrides.

    Args:
        **overrides: Field values to change.

    Returns:
        NavigationIntake: The intake.
    """
    values: dict[str, Any] = {
        "carrier": "MetLife",
        "policy_year_start": date(2026, 1, 15),
        "months_insured": 28,
        "deducible": 15000,
        "coaseguro_pct": 10,
        "tope_coaseguro": 25300,
        "treatment_rx": "dupilumab",
        "easi_score": 28.0,
        "scorad_score": 62.0,
        "dlqi_score": 18,
        "prior_treatments_failed": ["tacrolimus tópico 0.1%", "ciclosporina oral 3mg/kg"],
        "preexisting": True,
        "dermatologist_name": "Roberto Sánchez Morales",
        "dermatologist_cedula": "7654321",
        "cofepris_registration": "COFEPRIS/2019/042/0001",
        "incidence_date": date(2026, 9, 12),
    }
    values.update(overrides)
    return NavigationIntake(**values)


@dataclass
class _Result:
    parsed: Any
    model_name: str = "gemini-test"
    input_tokens: int = 10
    output_tokens: int = 20
    latency_ms: int = 5


class ScriptedModel:
    """Stands in for ``gemini_service``: one canned answer per agent.

    An answer of ``None`` makes that agent's call fail, so its fallback runs.
    Every call is recorded with its prompts.
    """

    def __init__(self, answers: dict[str, Any]) -> None:
        """Hold the answers.

        Args:
            answers: Agent key to answer.
        """
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    def _answer(self, prompt: str, system: str | None, purpose: str) -> _Result:
        agent = purpose.removeprefix("navigation_")
        self.calls.append({"agent": agent, "prompt": prompt, "system": system})
        answer = self.answers.get(agent)
        if answer is None:
            raise ModelCallError(f"scripted failure for {agent}")
        # A copy, so an agent mutating its answer cannot leak into the next test.
        return _Result(parsed=json.loads(json.dumps(answer)) if not isinstance(answer, str) else answer)

    async def json_call(self, prompt: str, *, system: str | None = None, purpose: str, **_: Any):
        """Answer a JSON call.

        Args:
            prompt: The user prompt.
            system: The system prompt.
            purpose: ``navigation_<agent>``.
            **_: Model and limits, ignored.

        Returns:
            _Result: The canned answer.
        """
        return self._answer(prompt, system, purpose)

    async def text_call(self, prompt: str, *, system: str | None = None, purpose: str, **_: Any):
        """Answer a prose call.

        Args:
            prompt: The user prompt.
            system: The system prompt.
            purpose: ``navigation_<agent>``.
            **_: Model and limits, ignored.

        Returns:
            _Result: The canned answer.
        """
        return self._answer(prompt, system, purpose)

    @property
    def order(self) -> list[str]:
        """Agent keys in call order.

        Returns:
            list[str]: The order.
        """
        return [call["agent"] for call in self.calls]


def scripted(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]) -> ScriptedModel:
    """Replace the model with scripted answers.

    Args:
        monkeypatch: The fixture.
        answers: Agent key to answer.

    Returns:
        ScriptedModel: The stand-in, for inspecting calls.
    """
    model = ScriptedModel(answers)
    monkeypatch.setattr(agent_calls, "gemini_service", model)
    return model


def context() -> AgentContext:
    """A run on :data:`TODAY`.

    Returns:
        AgentContext: The context.
    """
    return AgentContext(today=TODAY)


PARSED_METLIFE: dict[str, Any] = {
    "meta": {
        "carrier": "MetLife México, S.A. de C.V.",
        "policy_number": "[NUM_POLIZA_1]",
        "policy_type": "Gastos Médicos Mayores Individual",
        "extraction_date": "2026-09-14",
        "confidence_score": 0.82,
    },
    "financial": {"deducible_amount": None, "coaseguro_pct": 10, "tope_coaseguro": None, "moneda": "MXN"},
    "coverage": {"biologics_covered": None, "pago_directo_meds": True, "coaseguro_meds_outpatient": 0},
    "preauthorization": {"segunda_valoracion_required": True, "segunda_valoracion_triggers": [], "docs_required": []},
    "preexisting": {"excluded": True, "coverage_after_months": 24},
    "dermatology": {"biologics_excluded": None, "derm_products_excluded": False},
    "appeals": {"notification_deadline_days": 5, "une_suspends_statute": True},
    "waiting_periods": {"maternity_months": None, "hiv_months": None, "custom": []},
}

PLAN: dict[str, Any] = {
    "carrier": "MetLife",
    "urgency_level": "high",
    "summary": "Paciente MetLife con dermatitis atópica y Rx de dupilumab.",
    "steps": [
        {
            "step": 1,
            "title": "Enviar notificación de siniestro",
            "action": "Enviar aviso por escrito.",
            "deadline": "2026-09-17",
            "owner": "psp_coordinator",
            "docs_needed": ["Aviso de siniestro"],
            "carrier_specific_note": "5 días naturales.",
        }
    ],
    "deadlines": {"notification": "2026-09-17", "preauth_submit": "2026-09-19", "first_dose_earliest": "2026-09-28"},
    "docs_checklist": {"clinical": ["EASI documentado"], "insurance": [], "carrier_specific": []},
    "carrier_alerts": ["Alerta del planificador"],
    "cost_projection": {"deducible": "from carátula", "monthly_drug_cost_estimate_mxn": 99999},
    "appeal_pathway": None,
}

STRATEGY: dict[str, Any] = {
    "strategic_summary": "Programar pago directo antes de la primera dosis.",
    "optimization_tips": [{"id": "OPT-001", "title": "Programación", "action": "Agendar.", "owner": "coordinator"}],
    "bundling_opportunities": [],
    "renewal_projection": {"premium_increase_estimate_pct": 8, "negotiation_tactics": ["Negociar"]},
    "tax_deduction_note": "Art. 151 LISR.",
    "utilization_score": 60,
    "utilization_score_explanation": "Uso parcial.",
}

ADHERENCE: dict[str, Any] = {
    "most_urgent_action": {
        "title": "Ordenar dosis",
        "action": "Pedir.",
        "deadline": "2026-09-21",
        "owner": "coordinator",
    },
    "adherence_score": 72,
    "adherence_score_factors": [],
    "next_30_days_actions": [],
    "reauthorization_status": {},
    "continuity_risk_assessment": {"risk_level": "medium", "risk_factors": ["Inicio"], "mitigation_actions": []},
    "patient_engagement_tips": ["Mantener calendario"],
}

LETTER = (
    "Ciudad de México, a 14 de septiembre de 2026\n\nUnidad Especializada de MetLife México\n\n"
    "Por medio de la presente, [NOMBRE_COMPLETO_PACIENTE], titular de la póliza [NÚMERO_DE_PÓLIZA], notifica..."
)

APPEAL: dict[str, Any] = {
    "appeal_type": "preexisting_denial",
    "carrier": "MetLife",
    "pathway": "UNE MetLife",
    "carta_apelacion": {
        "destinatario": "UNE MetLife",
        "asunto": "Inconformidad",
        "cuerpo": "[NOMBRE_COMPLETO_PACIENTE], póliza [NÚMERO_DE_PÓLIZA], [FECHA_DE_NACIMIENTO], [ID_PACIENTE]. "
        "Dermatólogo Dr. Roberto Sánchez Morales (Cédula Profesional: 7654321).",
        "cierre": "Atentamente",
        "firma_block": "[NOMBRE_COMPLETO_PACIENTE]",
    },
    "carta_condusef": {"aplica": True, "cuerpo": "Queja"},
    "docs_adicionales": [],
    "argumentos_clave": ["EASI 28"],
    "probabilidad_exito": "media",
    "notas_estrategicas": "",
}


def all_answers(**overrides: Any) -> dict[str, Any]:
    """A successful answer for every agent.

    Args:
        **overrides: Agent key to a different answer, or None to fail it.

    Returns:
        dict: The answers.
    """
    answers: dict[str, Any] = {
        "parser": PARSED_METLIFE,
        "planner": PLAN,
        "notification": LETTER,
        "optimizer": STRATEGY,
        "adherence": ADHERENCE,
        "advocate": APPEAL,
    }
    answers.update(overrides)
    return answers
