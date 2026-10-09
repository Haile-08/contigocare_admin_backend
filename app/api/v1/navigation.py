"""The navigation endpoints: InnovaDerm Navigator, run on a stored analysis.

    GET  /insurance/navigator/catalog                 therapies the drug catalog prices
    POST /insurance/analyses/{id}/navigation          intake ──▶ redact free text, gate,
                                                      start the pipeline (202)
    GET  /insurance/navigations/{id}                  poll a run
    GET  /insurance/navigations/{id}/report           the coordinator report (PDF)
    GET  /insurance/navigations/{id}/broker-kit       the broker kit (ZIP)
    POST /insurance/navigations/{id}/feedback         the reviewer's verdict (204)

The pipeline is the handover's: Parser → Planner → Notification → Optimizer →
Adherence → Advocate, one agent after another, which takes minutes. A request
that waited for it would outlive the proxy's timeout, so ``POST`` records the run
as ``running``, starts the pipeline in this process, and returns; the console
polls ``GET`` until the run finishes. The rows are the state — a restart marks
whatever was still running as failed (see ``app.main``).

The parser reads the analysis's *redacted* policy text — the only form of the
document the console keeps — never the upload, which was dropped when the
analysis ran.

The intake's free text (a denial reason, prior treatments, the prescription) is
the one place a person types straight into a prompt. It is redacted here,
server-side, and then put through the same residual gate as ``/analyze``.
"""

import asyncio
import time
import uuid
from typing import (
    Any,
    Coroutine,
    Optional,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from app.api.v1.auth import get_current_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import (
    analysis_tokens_total,
    navigation_duration_seconds,
    navigation_feedback_total,
    navigation_runs_total,
    redaction_blocked_total,
    redaction_entities_total,
)
from app.core.navigator.broker_kit import (
    broker_kit_filename,
    build_broker_kit,
)
from app.core.navigator.drug_catalog import DRUG_CATALOG
from app.core.navigator.orchestrator import run_pipeline
from app.core.navigator.privacy import redact_free_text
from app.core.navigator.report import (
    PDF_MEDIA_TYPE,
    render_report,
    report_filename,
)
from app.models.admin import Admin
from app.models.analysis import (
    AnalysisStatus,
    FeedbackVerdict,
)
from app.models.navigation import (
    NavigationFeedback,
    NavigationRun,
)
from app.schemas.navigation import (
    DrugCatalogItem,
    DrugCatalogResponse,
    NavigationFeedbackRequest,
    NavigationFeedbackResponse,
    NavigationIntake,
    NavigationResponse,
    SectionFeedback,
)
from app.services.database import database_service
from app.services.redaction import redaction_engine

router = APIRouter()
db = database_service

RULES_VERSION = "innovaderm-v2-2026-06-01/contigocare-2"

# Strong references to the running pipelines. The event loop holds tasks only
# weakly, and a task nothing references can be collected mid-run.
_running: set[asyncio.Task[None]] = set()


def navigation_to_response(run: NavigationRun, feedback: Optional[NavigationFeedback] = None) -> NavigationResponse:
    """Shape a stored navigation for the client.

    Args:
        run: The stored run.
        feedback: The reviewer's verdict on it, when one is on record.

    Returns:
        NavigationResponse: The response.
    """
    return NavigationResponse(
        navigation_id=str(run.id),
        analysis_id=str(run.analysis_id),
        patient_id=run.patient_id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        current_agent=run.current_agent,
        created_at=run.created_at.isoformat(),
        intake=run.intake,
        result=run.result,
        error=run.error,
        prompt_version=run.prompt_version,
        model_names=run.model_names,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        latency_ms=run.latency_ms,
        degraded_agents=run.degraded_agents,
        feedback=(
            NavigationFeedbackResponse(
                verdict=feedback.verdict.value if hasattr(feedback.verdict, "value") else str(feedback.verdict),
                sections={
                    key: SectionFeedback.model_validate(value)
                    for key, value in (feedback.section_feedback or {}).items()
                    if isinstance(value, dict)
                },
                notes=feedback.notes,
                created_at=feedback.created_at.isoformat(),
            )
            if feedback is not None
            else None
        ),
    )


def _redact_intake(intake: NavigationIntake) -> tuple[NavigationIntake, dict[str, int], list[str]]:
    """Redact every free-text field of an intake a patient identifier could be typed into.

    The dermatologist's name and cédula are not redacted: they are the
    professional credentials the handover's appeal letters cite, not the
    patient's data.

    Args:
        intake: The validated intake.

    Returns:
        tuple: The redacted intake, counts per category, and the residual
        blocking categories still present (empty when clean).
    """
    summary: dict[str, int] = {}

    def redact(text: str) -> str:
        result = redact_free_text(text)
        for category, count in result.summary.items():
            summary[category] = summary.get(category, 0) + count
        return result.text

    updates = {
        "denial_reason": redact(intake.denial_reason) if intake.denial_reason else None,
        "prior_treatments_failed": [redact(entry) for entry in intake.prior_treatments_failed],
        "treatment_rx": redact(intake.treatment_rx),
        "diagnosis": redact(intake.diagnosis),
    }
    redacted = intake.model_copy(update=updates)

    joined = "\n".join(
        [
            redacted.denial_reason or "",
            redacted.treatment_rx,
            redacted.diagnosis,
            *redacted.prior_treatments_failed,
        ]
    )
    residual = sorted({span.category.value for span in redaction_engine.residual_scan(joined)})
    return redacted, summary, residual


def _intake_without_free_text(intake: NavigationIntake) -> dict[str, Any]:
    """The intake as stored for a refused run: structured fields only.

    Args:
        intake: The intake.

    Returns:
        dict: JSON-ready intake with free text removed.
    """
    return intake.model_dump(
        mode="json",
        exclude={"denial_reason", "prior_treatments_failed", "treatment_rx", "diagnosis"},
    )


async def _execute(navigation_id: uuid.UUID, policy_text: str, intake: NavigationIntake, patient_id: str) -> None:
    """Run the pipeline for one stored navigation and record how it ended.

    Args:
        navigation_id: The run, already stored as ``running``.
        policy_text: The analysis's redacted policy text.
        intake: The intake, free text redacted.
        patient_id: The analysis's patient id.
    """
    started = time.perf_counter()

    async def on_agent(agent: str) -> None:
        await db.update_navigation_run(navigation_id, current_agent=agent)

    try:
        outcome = await asyncio.wait_for(
            run_pipeline(policy_text, intake, patient_id, on_agent=on_agent),
            timeout=settings.NAVIGATION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        navigation_runs_total.labels(status=AnalysisStatus.FAILED.value).inc()
        reason = (
            "navigation exceeded its time budget" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}"
        )
        logger.exception("navigation_failed", navigation_id=str(navigation_id), error_type=type(exc).__name__)
        try:
            await db.update_navigation_run(
                navigation_id,
                status=AnalysisStatus.FAILED,
                current_agent=None,
                error=reason[:2000],
                latency_ms=latency_ms,
            )
        except Exception:
            logger.exception("navigation_failure_not_recorded", navigation_id=str(navigation_id))
        return

    latency_ms = int((time.perf_counter() - started) * 1000)
    input_tokens = sum(usage.input_tokens for usage in outcome.usage)
    output_tokens = sum(usage.output_tokens for usage in outcome.usage)
    model_names = {usage.agent: usage.model_name for usage in outcome.usage if usage.model_name}

    stored = await db.update_navigation_run(
        navigation_id,
        status=AnalysisStatus.SUCCEEDED,
        current_agent=None,
        result=outcome.summary,
        model_names=model_names,
        degraded_agents=outcome.degraded_agents,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
    if not stored:
        # Erased while it ran. The summary goes with it.
        logger.info("navigation_erased_while_running", navigation_id=str(navigation_id))
        return

    navigation_runs_total.labels(status=AnalysisStatus.SUCCEEDED.value).inc()
    navigation_duration_seconds.observe(latency_ms / 1000)
    for usage in outcome.usage:
        if usage.model_name:
            analysis_tokens_total.labels(model=usage.model_name, direction="input").inc(usage.input_tokens)
            analysis_tokens_total.labels(model=usage.model_name, direction="output").inc(usage.output_tokens)

    logger.info(
        "navigation_completed",
        navigation_id=str(navigation_id),
        carrier=outcome.summary.get("carrier"),
        urgency=outcome.summary.get("urgency_level"),
        alerts=len(outcome.summary.get("carrier_alerts") or []),
        degraded_agents=outcome.degraded_agents,
        latency_ms=latency_ms,
    )


def _start_in_background(pipeline: Coroutine[Any, Any, None]) -> None:
    """Run a pipeline in this process, holding a reference until it ends.

    Args:
        pipeline: The coroutine to run.
    """
    task = asyncio.create_task(pipeline)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def cancel_running_navigations() -> None:
    """Cancel pipelines still running at shutdown.

    Their rows stay ``running`` and are marked failed on the next startup.
    """
    for task in list(_running):
        task.cancel()
    if _running:
        await asyncio.gather(*_running, return_exceptions=True)


@router.get("/navigator/catalog", response_model=DrugCatalogResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def get_drug_catalog(
    request: Request,
    admin: Admin = Depends(get_current_admin),
):
    """List the therapies the drug catalog prices.

    Args:
        request: For rate limiting.
        admin: The signed-in operator.

    Returns:
        DrugCatalogResponse: The catalog.
    """
    return DrugCatalogResponse(
        items=[
            DrugCatalogItem(
                clave=key,
                nombre_generico=entry["generic_name"],
                marca=entry["brand_name"],
                fabricante=entry["manufacturer"],
                indicacion=entry["indication"],
                via=entry["route"],
                frecuencia_dias=int(entry["frequency_days"]),
                dosis_carga=int(entry.get("loading_doses", 0)),
                costo_mensual_mxn=float(entry["monthly_cost_mxn"]),
                registro_cofepris=str(entry.get("cofepris_registration", "")),
                biologico=bool(entry.get("biologic")),
            )
            for key, entry in DRUG_CATALOG.items()
        ]
    )


@router.post(
    "/analyses/{analysis_id}/navigation",
    response_model=NavigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["navigate"][0])
async def navigate_analysis(
    request: Request,
    analysis_id: uuid.UUID,
    payload: NavigationIntake,
    admin: Admin = Depends(get_current_admin),
):
    """Start InnovaDerm Navigator on a stored analysis.

    Args:
        request: For rate limiting.
        analysis_id: The analysis to navigate.
        payload: The patient intake.
        admin: The signed-in operator.

    Returns:
        NavigationResponse: The run, ``running``.

    Raises:
        HTTPException: 404 for an unknown analysis or disabled navigation, 409
            for an analysis without a result or without policy text, 422 when
            the free text still holds identifiers.
    """
    if not settings.NAVIGATION_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La navegación no está habilitada.")

    analysis_run = await db.get_analysis_run(analysis_id)
    if analysis_run is None:
        logger.warning(
            "analysis_not_found",
            operation="navigate_analysis",
            analysis_id=str(analysis_id),
            admin_id=str(admin.id),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Análisis no encontrado.")

    if analysis_run.status != AnalysisStatus.SUCCEEDED or not analysis_run.redacted_text:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este análisis no tiene una póliza redactada guardada; vuelva a analizar la póliza antes de navegar el caso.",
        )

    intake, redaction_summary, residual = _redact_intake(payload)
    for category, count in redaction_summary.items():
        redaction_entities_total.labels(category=category).inc(count)

    base_record = {
        "analysis_id": analysis_run.id,
        "patient_id": analysis_run.patient_id,
        "admin_id": admin.id,
        "redaction_summary": redaction_summary,
        "prompt_version": settings.NAVIGATION_PROMPT_VERSION,
        "rules_version": RULES_VERSION,
    }

    if residual and settings.REDACTION_ENFORCE_ON_SUBMIT:
        redaction_blocked_total.inc()
        navigation_runs_total.labels(status=AnalysisStatus.BLOCKED_BY_REDACTION.value).inc()
        await db.create_navigation_run(
            NavigationRun(
                **base_record,
                intake=_intake_without_free_text(intake),
                status=AnalysisStatus.BLOCKED_BY_REDACTION,
                error=f"residual identifiers: {', '.join(residual)}",
            )
        )
        logger.error(
            "navigation_blocked_residual_phi",
            analysis_id=str(analysis_run.id),
            admin_id=str(admin.id),
            categories=residual,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "El texto capturado todavía contiene datos personales identificables "
                f"({', '.join(residual)}). Elimínelos del motivo de negativa, del tratamiento o de los "
                "tratamientos previos."
            ),
        )

    run = await db.create_navigation_run(
        NavigationRun(
            **base_record,
            intake=intake.model_dump(mode="json"),
            status=AnalysisStatus.RUNNING,
            current_agent="parser",
        )
    )

    _start_in_background(_execute(run.id, analysis_run.redacted_text, intake, analysis_run.patient_id))

    logger.info(
        "navigation_started",
        navigation_id=str(run.id),
        analysis_id=str(analysis_run.id),
        admin_id=str(admin.id),
    )
    return navigation_to_response(run)


async def _stored_navigation(navigation_id: uuid.UUID, admin: Admin, operation: str) -> NavigationRun:
    """A navigation run, or a 404.

    Args:
        navigation_id: The run.
        admin: The signed-in operator.
        operation: For the log line.

    Returns:
        NavigationRun: The run.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    run = await db.get_navigation_run(navigation_id)
    if run is None:
        logger.warning(
            "navigation_not_found", operation=operation, navigation_id=str(navigation_id), admin_id=str(admin.id)
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Navegación no encontrada.")
    return run


def _finished_summary(run: NavigationRun) -> dict[str, Any]:
    """The summary of a finished InnovaDerm run, or a 409.

    Args:
        run: The run.

    Returns:
        dict: The summary.

    Raises:
        HTTPException: 409 while running, after a failure, or for a run stored
            before the InnovaDerm port.
    """
    summary = run.result or {}
    if run.status != AnalysisStatus.SUCCEEDED or "action_plan" not in summary:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta navegación no tiene un resultado de InnovaDerm; vuelva a navegar el caso.",
        )
    return summary


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    """A download that is not cached anywhere.

    Args:
        content: The bytes.
        media_type: The content type.
        filename: The download name.

    Returns:
        Response: The response.
    """
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/navigations/{navigation_id}", response_model=NavigationResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def get_navigation(
    request: Request,
    navigation_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
):
    """Read one navigation — the console polls this while it runs.

    Args:
        request: For rate limiting.
        navigation_id: The run.
        admin: The signed-in operator.

    Returns:
        NavigationResponse: The run.
    """
    run = await _stored_navigation(navigation_id, admin, "get_navigation")
    # A running navigation cannot have been reviewed; skip the query while polling.
    feedback = await db.get_navigation_feedback(run.id) if run.status == AnalysisStatus.SUCCEEDED else None
    return navigation_to_response(run, feedback)


@router.get("/navigations/{navigation_id}/report")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def download_report(
    request: Request,
    navigation_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
):
    """The coordinator report, built in memory.

    Args:
        request: For rate limiting.
        navigation_id: The run.
        admin: The signed-in operator.

    Returns:
        Response: The PDF.
    """
    run = await _stored_navigation(navigation_id, admin, "download_report")
    summary = _finished_summary(run)
    content = await asyncio.to_thread(render_report, summary, run.created_at.astimezone())
    logger.info("navigation_report_downloaded", navigation_id=str(run.id), admin_id=str(admin.id))
    return _attachment(content, PDF_MEDIA_TYPE, report_filename(summary))


@router.get("/navigations/{navigation_id}/broker-kit")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def download_broker_kit(
    request: Request,
    navigation_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
):
    """The broker kit, zipped in memory.

    Args:
        request: For rate limiting.
        navigation_id: The run.
        admin: The signed-in operator.

    Returns:
        Response: The ZIP.
    """
    run = await _stored_navigation(navigation_id, admin, "download_broker_kit")
    summary = _finished_summary(run)
    content = await asyncio.to_thread(build_broker_kit, summary, run.created_at.astimezone())
    logger.info("navigation_broker_kit_downloaded", navigation_id=str(run.id), admin_id=str(admin.id))
    return _attachment(content, "application/zip", broker_kit_filename(summary))


@router.post("/navigations/{navigation_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["feedback"][0])
async def submit_navigation_feedback(
    request: Request,
    navigation_id: uuid.UUID,
    payload: NavigationFeedbackRequest,
    admin: Admin = Depends(get_current_admin),
):
    """Record — or revise — the reviewer's verdict on a navigation.

    Only a finished navigation can be judged: there is no report to judge while
    it runs, and a failed or blocked run produced nothing a section flag could
    point at. Posting again replaces the verdict on record rather than adding a
    second one.

    Args:
        request: For rate limiting.
        navigation_id: The run being judged.
        payload: The verdict, section flags and notes.
        admin: The reviewing operator.

    Raises:
        HTTPException: 404 for an unknown run, 409 for one without a finished
            InnovaDerm result.
    """
    run = await _stored_navigation(navigation_id, admin, "submit_navigation_feedback")
    _finished_summary(run)

    verdict = FeedbackVerdict(payload.verdict)
    _, revised = await db.save_navigation_feedback(
        navigation_id=run.id,
        admin_id=admin.id,
        verdict=verdict,
        section_feedback={key: section.model_dump() for key, section in payload.sections.items()},
        notes=payload.notes,
    )

    navigation_feedback_total.labels(verdict=verdict.value).inc()
    logger.info(
        "navigation_feedback_recorded",
        navigation_id=str(run.id),
        verdict=verdict.value,
        flagged_sections=sorted(key for key, section in payload.sections.items() if section.flagged),
        revised=revised,
    )
