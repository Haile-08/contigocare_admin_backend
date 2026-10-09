"""The navigation routes, with auth, the database and the model stubbed."""

import asyncio
import io
import uuid
import zipfile
from datetime import (
    UTC,
    datetime,
)

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import navigation as navigation_route
from app.api.v1.auth import get_current_admin
from app.main import app
from app.models.analysis import (
    AnalysisRun,
    AnalysisStatus,
)
from app.models.navigation import NavigationFeedback
from tests.navigator.helpers import (
    all_answers,
    scripted,
)

ADMIN_ID = uuid.uuid4()


class _Admin:
    id = ADMIN_ID


def _body(**overrides):
    body = {
        "carrier": "MetLife",
        "policy_year_start": "2026-01-15",
        "months_insured": 28,
        "treatment_rx": "dupilumab",
        "incidence_date": "2026-09-12",
        "easi_score": 28,
        "prior_treatments_failed": ["tacrolimus", "ciclosporina"],
        "dermatologist_name": "Roberto Sánchez Morales",
    }
    body.update(overrides)
    return body


@pytest.fixture
def api(monkeypatch):
    rows: dict = {}
    feedback_rows: dict = {}
    analysis = AnalysisRun(
        id=uuid.uuid4(),
        patient_id="PAC-2026-0001",
        admin_id=ADMIN_ID,
        document_sha256="0" * 64,
        redacted_text="CARÁTULA REDACTADA — MetLife México",
        result={},
        status=AnalysisStatus.SUCCEEDED,
    )
    scheduled: list = []

    async def get_analysis_run(analysis_id):
        return analysis if analysis_id == analysis.id else None

    async def create_navigation_run(record):
        record.id = uuid.uuid4()
        record.created_at = datetime.now(UTC)
        rows[record.id] = record
        return record

    async def get_navigation_run(navigation_id):
        return rows.get(navigation_id)

    async def update_navigation_run(navigation_id, **values):
        record = rows.get(navigation_id)
        if record is None:
            return False
        for key, value in values.items():
            setattr(record, key, value)
        return True

    async def get_navigation_feedback(navigation_id):
        return feedback_rows.get(navigation_id)

    async def save_navigation_feedback(navigation_id, admin_id, verdict, section_feedback, notes):
        revised = navigation_id in feedback_rows
        feedback_rows[navigation_id] = NavigationFeedback(
            navigation_id=navigation_id,
            admin_id=admin_id,
            verdict=verdict,
            section_feedback=section_feedback,
            notes=notes,
            created_at=datetime.now(UTC),
        )
        return feedback_rows[navigation_id], revised

    def start_in_background(pipeline):
        # Held rather than started: the test runs it with `_finish` and then
        # reads the finished row, as the console's poll would.
        scheduled.append(pipeline)

    monkeypatch.setattr(navigation_route.db, "get_analysis_run", get_analysis_run)
    monkeypatch.setattr(navigation_route.db, "create_navigation_run", create_navigation_run)
    monkeypatch.setattr(navigation_route.db, "get_navigation_run", get_navigation_run)
    monkeypatch.setattr(navigation_route.db, "update_navigation_run", update_navigation_run)
    monkeypatch.setattr(navigation_route.db, "get_navigation_feedback", get_navigation_feedback)
    monkeypatch.setattr(navigation_route.db, "save_navigation_feedback", save_navigation_feedback)
    monkeypatch.setattr(navigation_route, "_start_in_background", start_in_background)
    model = scripted(monkeypatch, all_answers())
    app.dependency_overrides[get_current_admin] = lambda: _Admin()
    client = TestClient(app)
    client.feedback_rows = feedback_rows
    yield client, analysis, rows, scheduled, model
    app.dependency_overrides.clear()


def _finish(scheduled):
    for coroutine in scheduled:
        asyncio.run(coroutine)
    scheduled.clear()


def test_starts_a_run_then_finishes_it(api):
    client, analysis, rows, scheduled, model = api
    response = client.post(f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body())

    assert response.status_code == 202, response.text
    started = response.json()
    assert started["status"] == "running"
    assert started["current_agent"] == "parser"

    _finish(scheduled)
    polled = client.get(f"/api/v1/insurance/navigations/{started['navigation_id']}").json()
    assert polled["status"] == "succeeded"
    assert polled["current_agent"] is None
    assert polled["result"]["carrier"] == "MetLife"
    assert set(polled["model_names"]) == {"parser", "planner", "notification", "optimizer", "adherence"}
    # The parser read the analysis's redacted policy.
    assert "CARÁTULA REDACTADA — MetLife México" in model.calls[0]["prompt"]


def test_redacts_the_denial_before_the_model_sees_it(api):
    client, analysis, rows, scheduled, model = api
    response = client.post(
        f"/api/v1/insurance/analyses/{analysis.id}/navigation",
        json=_body(denial_reason="Negada al Sr. Juan Pérez por preexistencia; monto $25,300.00"),
    )
    assert response.status_code == 202, response.text
    _finish(scheduled)

    stored = next(iter(rows.values()))
    assert "Juan Pérez" not in stored.intake["denial_reason"]
    assert "$25,300.00" in stored.intake["denial_reason"]
    assert stored.redaction_summary
    assert all("Juan Pérez" not in call["prompt"] for call in model.calls)


def test_downloads_the_report_and_kit_once_finished(api):
    client, analysis, rows, scheduled, _ = api
    navigation_id = client.post(f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body()).json()[
        "navigation_id"
    ]

    early = client.get(f"/api/v1/insurance/navigations/{navigation_id}/report")
    assert early.status_code == 409

    _finish(scheduled)
    report = client.get(f"/api/v1/insurance/navigations/{navigation_id}/report")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert report.content.startswith(b"%PDF-")
    assert 'filename="InnovaDerm-PAC-2026-0001-MetLife-' in report.headers["content-disposition"]
    assert report.headers["cache-control"].startswith("no-store")

    kit = client.get(f"/api/v1/insurance/navigations/{navigation_id}/broker-kit")
    assert kit.status_code == 200
    assert "README.txt" in zipfile.ZipFile(io.BytesIO(kit.content)).namelist()


def test_refuses_unknown_fields_like_a_patient_name(api):
    client, analysis, rows, scheduled, _ = api
    response = client.post(
        f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body(patient_name="Juan Pérez")
    )
    assert response.status_code == 422
    assert rows == {}
    assert scheduled == []


def test_blocks_residual_identifiers(api, monkeypatch):
    client, analysis, rows, scheduled, _ = api
    # Simulate an identifier the automatic redaction could not remove.
    monkeypatch.setattr(
        navigation_route, "redact_free_text", lambda text: type("R", (), {"text": text, "summary": {}})()
    )
    response = client.post(
        f"/api/v1/insurance/analyses/{analysis.id}/navigation",
        json=_body(denial_reason="RFC del asegurado: PEGJ850315HN2"),
    )
    assert response.status_code == 422
    assert scheduled == []
    stored = next(iter(rows.values()))
    assert stored.status == AnalysisStatus.BLOCKED_BY_REDACTION
    assert "denial_reason" not in stored.intake


def test_a_failed_pipeline_is_recorded(api, monkeypatch):
    client, analysis, rows, scheduled, _ = api

    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(navigation_route, "run_pipeline", explode)
    navigation_id = client.post(f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body()).json()[
        "navigation_id"
    ]
    _finish(scheduled)
    polled = client.get(f"/api/v1/insurance/navigations/{navigation_id}").json()
    assert polled["status"] == "failed"
    assert "RuntimeError" in polled["error"]


def test_unknown_analysis_and_navigation_are_404(api):
    client, _, _, _, _ = api
    assert client.post(f"/api/v1/insurance/analyses/{uuid.uuid4()}/navigation", json=_body()).status_code == 404
    assert client.get(f"/api/v1/insurance/navigations/{uuid.uuid4()}").status_code == 404


def test_catalog_lists_therapies(api):
    client, _, _, _, _ = api
    response = client.get("/api/v1/insurance/navigator/catalog")
    assert response.status_code == 200
    items = {item["clave"]: item for item in response.json()["items"]}
    assert set(items) == {"nemolizumab", "dupilumab", "upadacitinib", "abrocitinib"}
    assert items["upadacitinib"]["biologico"] is False


def _finished_navigation(api) -> str:
    client, analysis, rows, scheduled, _ = api
    navigation_id = client.post(f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body()).json()[
        "navigation_id"
    ]
    _finish(scheduled)
    return navigation_id


def test_records_and_revises_navigation_feedback(api):
    client = api[0]
    navigation_id = _finished_navigation(api)

    first = client.post(
        f"/api/v1/insurance/navigations/{navigation_id}/feedback",
        json={
            "verdict": "partially_correct",
            "sections": {
                "action_plan": {"flagged": True, "comment": "  El paso 2 no aplica a MetLife  "},
                "deadlines": {"flagged": False, "comment": ""},
            },
            "notes": "Revisar la fecha de preautorización",
        },
    )
    assert first.status_code == 204, first.text

    polled = client.get(f"/api/v1/insurance/navigations/{navigation_id}").json()
    assert polled["feedback"]["verdict"] == "partially_correct"
    # An untouched section is not stored; a comment is trimmed.
    assert polled["feedback"]["sections"] == {
        "action_plan": {"flagged": True, "comment": "El paso 2 no aplica a MetLife"}
    }
    assert polled["feedback"]["notes"] == "Revisar la fecha de preautorización"

    second = client.post(f"/api/v1/insurance/navigations/{navigation_id}/feedback", json={"verdict": "correct"})
    assert second.status_code == 204
    assert len(client.feedback_rows) == 1
    assert client.get(f"/api/v1/insurance/navigations/{navigation_id}").json()["feedback"]["verdict"] == "correct"


def test_navigation_feedback_refuses_unknown_sections_and_verdicts(api):
    client = api[0]
    navigation_id = _finished_navigation(api)
    url = f"/api/v1/insurance/navigations/{navigation_id}/feedback"

    assert client.post(url, json={"verdict": "maybe"}).status_code == 422
    assert (
        client.post(url, json={"verdict": "correct", "sections": {"horoscope": {"flagged": True}}}).status_code == 422
    )
    assert client.feedback_rows == {}


def test_navigation_feedback_needs_a_finished_run(api):
    client, analysis, rows, scheduled, _ = api
    navigation_id = client.post(f"/api/v1/insurance/analyses/{analysis.id}/navigation", json=_body()).json()[
        "navigation_id"
    ]
    url = f"/api/v1/insurance/navigations/{navigation_id}/feedback"
    assert client.post(url, json={"verdict": "correct"}).status_code == 409
    assert (
        client.post(f"/api/v1/insurance/navigations/{uuid.uuid4()}/feedback", json={"verdict": "correct"}).status_code
        == 404
    )
    assert client.feedback_rows == {}
    for coroutine in scheduled:
        coroutine.close()
