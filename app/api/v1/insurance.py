"""The insurance analysis endpoints.

Two calls, with the admin's judgement in between:

    POST /insurance/extract   file    ──▶ text + proposed redactions
                                          (server keeps nothing)
    POST /insurance/analyze   text +  ──▶ redact server-side, gate, call Gemini,
                              approved     store the redacted run
                              spans

The server is stateless between them on purpose. Holding the extracted text in a
cache keyed by a draft id would be more convenient and would quietly turn "the
policy is never stored" into "the policy is stored for five minutes" — which is
not the same promise. The admin's browser holds the text; the admin is
authorised to read the document they just uploaded.

The consequence is that the client sends the text back, and a client is not a
trust boundary. So ``analyze`` does not accept pre-redacted text: it takes the
original text plus the *spans the admin approved*, applies the redaction itself,
and then re-scans the result. A tampered client can only make the redaction
weaker in ways the server-side gate then refuses.
"""

import asyncio
import uuid

from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.api.v1.auth import get_current_admin
from app.core.config import settings
from app.core.langgraph import insurance_agent
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import (
    analysis_duration_seconds,
    analysis_evidence_failures_total,
    analysis_feedback_total,
    analysis_runs_total,
    analysis_tokens_total,
    document_extraction_duration_seconds,
    documents_processed_total,
    redaction_blocked_total,
    redaction_entities_total,
)
from app.models.admin import Admin
from app.models.analysis import (
    AnalysisFeedback,
    AnalysisRun,
    AnalysisStatus,
    FeedbackVerdict,
)
from app.schemas.insurance import (
    AnalisisGMM,
    AnalysisDetailResponse,
    AnalysisListResponse,
    AnalysisSummary,
    AnalyzeRequest,
    AnalyzeResponse,
    ExtractResponse,
    FeedbackRequest,
    FeedbackResponse,
)
from app.services.database import database_service
from app.services.document import (
    DocumentError,
    document_extractor,
)
from app.services.llm import (
    ModelBlockedError,
    ModelCallError,
)
from app.services.redaction import (
    redaction_engine,
    spans_from_payload,
    spans_to_payload,
)

router = APIRouter()
db = database_service


def summarize_run(run: AnalysisRun, verdict) -> AnalysisSummary:
    """Shape one stored run into a list row.

    A list row carries no policy text and no extracted figure beyond the
    insurer's name — enough to recognise the right analysis, not enough to be a
    second copy of it. The full result is one click away, behind its own
    request.

    Args:
        run: The stored run.
        verdict: The reviewer's verdict, or None.

    Returns:
        AnalysisSummary: The row.
    """
    result = run.result or {}
    aseguradora = (result.get("datos_poliza", {}).get("aseguradora") or {}).get("valor")
    hallazgos = result.get("hallazgos", []) or []

    return AnalysisSummary(
        id=str(run.id),
        patient_id=run.patient_id,
        created_at=run.created_at.isoformat(),
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        aseguradora=aseguradora,
        confianza_global=result.get("confianza_global"),
        verdict=verdict.value if verdict is not None and hasattr(verdict, "value") else verdict,
        latency_ms=run.latency_ms,
        hallazgos_criticos=sum(1 for h in hallazgos if h.get("severidad") == "critica"),
    )

# Read the upload in bounded chunks. `await file.read()` with no argument will
# happily buffer a two-gigabyte body into memory before anyone checks its size.
UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload, refusing anything over the configured ceiling.

    Args:
        file: The uploaded file.

    Returns:
        bytes: The file contents.

    Raises:
        HTTPException: 413 when the upload exceeds the limit.
    """
    limit = settings.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"El archivo excede el límite de {limit / (1024 * 1024):.0f} MB.",
            )
        chunks.append(chunk)

    return b"".join(chunks)


@router.post("/extract", response_model=ExtractResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["extract"][0])
async def extract_document(
    request: Request,
    file: UploadFile = File(...),
    admin: Admin = Depends(get_current_admin),
):
    """Parse an uploaded policy and propose redactions.

    Nothing is written anywhere by this endpoint. The bytes are parsed in
    memory, OCRed in memory when needed, scanned for identifiers, and the result
    is returned to the caller.

    Args:
        request: For rate limiting.
        file: The uploaded policy.
        admin: The signed-in operator.

    Returns:
        ExtractResponse: The text and the proposed redactions.

    Raises:
        HTTPException: 400 for an unreadable or disallowed document.
    """
    content = await _read_upload(file)

    try:
        with document_extraction_duration_seconds.time():
            # Parsing and OCR are CPU-bound and would otherwise stall every
            # other request on the worker for the duration of a scan.
            document = await asyncio.to_thread(
                document_extractor.extract, content, file.content_type
            )
    except DocumentError as exc:
        logger.warning("document_extraction_rejected", reason=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    finally:
        # Drop the reference promptly; there is no reason for a policy to stay
        # reachable while the rest of the handler runs.
        del content

    documents_processed_total.labels(kind=document.kind.value).inc()

    spans = await asyncio.to_thread(redaction_engine.detect, document.text)
    seen_before = await db.document_seen_before(document.sha256)

    logger.info(
        "document_ready_for_review",
        admin_id=str(admin.id),
        kind=document.kind.value,
        pages=document.page_count,
        spans=len(spans),
        previously_analyzed=seen_before,
    )

    return ExtractResponse(
        document_sha256=document.sha256,
        document_kind=document.kind.value,
        page_count=document.page_count,
        ocr_page_count=document.ocr_page_count,
        truncated=document.truncated,
        text=document.text,
        spans=spans_to_payload(spans, document.text),
        previously_analyzed=seen_before,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyze"][0])
async def analyze_policy(
    request: Request,
    payload: AnalyzeRequest,
    admin: Admin = Depends(get_current_admin),
):
    """Redact the approved spans, verify, and run the analysis agent.

    Args:
        request: For rate limiting.
        payload: The document text and the admin's approved redactions.
        admin: The signed-in operator.

    Returns:
        AnalyzeResponse: The structured analysis.

    Raises:
        HTTPException: 400 for malformed spans, 422 when the redaction gate
            refuses the submission, 502 when the model could not answer, 504
            when it did not answer in time.
    """
    try:
        approved = spans_from_payload(
            (span.model_dump() for span in payload.approved_spans),
            len(payload.text),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # The redaction is performed here, by this code, from the original text —
    # never taken on trust from the client as a finished string.
    redacted = redaction_engine.apply(payload.text, approved)

    for category, count in redacted.summary.items():
        redaction_entities_total.labels(category=category).inc(count)

    # The gate. Everything above assumes the client behaved; this assumes it did
    # not.
    residual = redaction_engine.residual_scan(redacted.text)
    if residual and settings.REDACTION_ENFORCE_ON_SUBMIT:
        categories = sorted({span.category.value for span in residual})
        redaction_blocked_total.inc()
        analysis_runs_total.labels(status=AnalysisStatus.BLOCKED_BY_REDACTION.value).inc()

        # Recorded without the offending text, so the blocked attempt is visible
        # on the dashboard without the record becoming a copy of what was
        # blocked.
        await db.create_analysis_run(
            AnalysisRun(
                patient_id=payload.patient_id.strip(),
                admin_id=admin.id,
                document_sha256=payload.document_sha256,
                page_count=payload.page_count,
                redacted_text="",
                redaction_summary=redacted.summary,
                status=AnalysisStatus.BLOCKED_BY_REDACTION,
                error=f"residual identifiers: {', '.join(categories)}",
                prompt_version=settings.ANALYSIS_PROMPT_VERSION,
            )
        )

        logger.error(
            "analysis_blocked_residual_phi",
            admin_id=str(admin.id),
            categories=categories,
            count=len(residual),
        )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "El texto aprobado todavía contiene datos personales identificables "
                f"({', '.join(categories)}). Revise las redacciones antes de continuar."
            ),
        )

    try:
        # The outermost of the three budgets. The model service bounds each of
        # its own calls, but the graph makes more than one of them, and an
        # operator watching a spinner is owed an answer either way: a 504 that
        # says what happened is worth more than a request the browser abandons
        # while the server keeps working on a result nobody will collect.
        state = await asyncio.wait_for(
            insurance_agent.analyze(redacted.text),
            timeout=settings.ANALYSIS_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        analysis_runs_total.labels(status=AnalysisStatus.FAILED.value).inc()
        await _record_failure(payload, admin, redacted, "analysis exceeded the request budget")
        logger.exception(
            "analysis_timed_out",
            admin_id=str(admin.id),
            timeout_seconds=settings.ANALYSIS_TIMEOUT_SECONDS,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "El análisis tardó más de lo permitido y se canceló. "
                "El proveedor del modelo está saturado; intente de nuevo en unos minutos."
            ),
        )
    except ModelBlockedError as exc:
        analysis_runs_total.labels(status=AnalysisStatus.FAILED.value).inc()
        await _record_failure(payload, admin, redacted, str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ModelCallError as exc:
        analysis_runs_total.labels(status=AnalysisStatus.FAILED.value).inc()
        await _record_failure(payload, admin, redacted, str(exc))
        logger.exception("analysis_model_failed", admin_id=str(admin.id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El servicio de análisis no está disponible en este momento. Intente de nuevo.",
        )

    result: AnalisisGMM = state.draft

    analysis_runs_total.labels(status=AnalysisStatus.SUCCEEDED.value).inc()
    # Fields the verify node could not ground in the document. The counter was
    # declared for exactly this and was never fed, which made the product's best
    # hallucination signal a flat line rather than a measurement.
    analysis_evidence_failures_total.inc(len(state.evidence_failures))
    analysis_duration_seconds.labels(model=state.model_name).observe(state.latency_ms / 1000)
    analysis_tokens_total.labels(model=state.model_name, direction="input").inc(state.input_tokens)
    analysis_tokens_total.labels(model=state.model_name, direction="output").inc(state.output_tokens)

    run = await db.create_analysis_run(
        AnalysisRun(
            patient_id=payload.patient_id.strip(),
            admin_id=admin.id,
            document_sha256=payload.document_sha256,
            document_filename_hint=payload.document_kind[:16],
            page_count=payload.page_count,
            redacted_char_count=len(redacted.text),
            redacted_text=redacted.text,
            redaction_summary=redacted.summary,
            result=result.model_dump(mode="json"),
            model_name=state.model_name,
            prompt_version=settings.ANALYSIS_PROMPT_VERSION,
            input_tokens=state.input_tokens,
            output_tokens=state.output_tokens,
            latency_ms=state.latency_ms,
            status=AnalysisStatus.SUCCEEDED,
        )
    )

    logger.info(
        "analysis_completed",
        analysis_id=str(run.id),
        admin_id=str(admin.id),
        model=state.model_name,
        latency_ms=state.latency_ms,
        evidence_failures=len(state.evidence_failures),
        self_critique=state.self_critique_applied,
    )

    return AnalyzeResponse(
        analysis_id=str(run.id),
        patient_id=run.patient_id,
        status=run.status.value,
        result=result,
        redaction_summary=redacted.summary,
        model_name=state.model_name,
        prompt_version=settings.ANALYSIS_PROMPT_VERSION,
        latency_ms=state.latency_ms,
        input_tokens=state.input_tokens,
        output_tokens=state.output_tokens,
        self_critique_applied=state.self_critique_applied,
    )


async def _record_failure(payload: AnalyzeRequest, admin: Admin, redacted, message: str) -> None:
    """Persist a failed run so failures are visible, not silent.

    Args:
        payload: The original request.
        admin: Who ran it.
        redacted: The redaction result.
        message: Failure detail.
    """
    await db.create_analysis_run(
        AnalysisRun(
            patient_id=payload.patient_id.strip(),
            admin_id=admin.id,
            document_sha256=payload.document_sha256,
            page_count=payload.page_count,
            redacted_char_count=len(redacted.text),
            redacted_text=redacted.text,
            redaction_summary=redacted.summary,
            status=AnalysisStatus.FAILED,
            error=message[:2000],
            prompt_version=settings.ANALYSIS_PROMPT_VERSION,
        )
    )


@router.post("/analyses/{analysis_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["feedback"][0])
async def submit_feedback(
    request: Request,
    analysis_id: uuid.UUID,
    payload: FeedbackRequest,
    admin: Admin = Depends(get_current_admin),
):
    """Record — or revise — the reviewer's verdict on an analysis.

    This is the highest-value data the system collects. A run without a verdict
    is a log line; a run with one is a labelled example that the eval harness
    can score against and the next prompt version has to beat.

    Posting again for a run that already has a verdict *replaces* it rather than
    appending a second one. A reviewer correcting their own review should leave
    one judgement on the run: two would double-count the analysis in the golden
    set and inflate the dashboard's reviewed count past the number of analyses
    that were actually reviewed.

    Args:
        request: For rate limiting.
        analysis_id: The run being judged.
        payload: The verdict and any field-level corrections.
        admin: The reviewing operator.

    Raises:
        HTTPException: 404 for an unknown run, 400 for an unknown verdict.
    """
    run = await db.get_analysis_run(analysis_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Análisis no encontrado.")

    try:
        verdict = FeedbackVerdict(payload.verdict)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Veredicto inválido. Use uno de: {', '.join(v.value for v in FeedbackVerdict)}",
        )

    existing = await db.get_feedback_for_run(run.id)

    if existing is None:
        await db.create_feedback(
            AnalysisFeedback(
                analysis_id=run.id,
                admin_id=admin.id,
                verdict=verdict,
                field_corrections=payload.field_corrections,
                notes=payload.notes,
            )
        )
    else:
        await db.update_feedback(
            feedback_id=existing.id,
            admin_id=admin.id,
            verdict=verdict,
            field_corrections=payload.field_corrections,
            notes=payload.notes,
        )

    analysis_feedback_total.labels(verdict=verdict.value).inc()
    logger.info(
        "analysis_feedback_recorded",
        analysis_id=str(run.id),
        verdict=verdict.value,
        revised=existing is not None,
    )


@router.get("/analyses", response_model=AnalysisListResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def list_analyses(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    patient_id: Optional[str] = Query(default=None, max_length=128),
    admin: Admin = Depends(get_current_admin),
):
    """List the policies that have been analysed, newest first.

    Args:
        request: For rate limiting.
        limit: Page size.
        offset: How many rows to skip.
        patient_id: Optional patient filter, matched as a substring.
        admin: The signed-in operator.

    Returns:
        AnalysisListResponse: One page of rows plus the unpaged total.
    """
    rows, total = await db.list_analysis_runs(
        limit=limit,
        offset=offset,
        patient_id=patient_id.strip() if patient_id else None,
    )

    return AnalysisListResponse(
        items=[summarize_run(run, verdict) for run, verdict in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetailResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["analyses"][0])
async def get_analysis(
    request: Request,
    analysis_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
):
    """Re-read a stored analysis, with the redacted policy behind it.

    Args:
        request: For rate limiting.
        analysis_id: The run to fetch.
        admin: The signed-in operator.

    Returns:
        AnalysisDetailResponse: The stored analysis, its redacted policy text,
        and the verdict already on record.

    Raises:
        HTTPException: 404 when the run does not exist.
    """
    run = await db.get_analysis_run(analysis_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Análisis no encontrado.")

    feedback = await db.get_feedback_for_run(run.id)

    return AnalysisDetailResponse(
        analysis_id=str(run.id),
        patient_id=run.patient_id,
        status=run.status.value,
        result=AnalisisGMM.model_validate(run.result) if run.result else None,
        redaction_summary=run.redaction_summary,
        model_name=run.model_name,
        prompt_version=run.prompt_version,
        latency_ms=run.latency_ms,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        created_at=run.created_at.isoformat(),
        page_count=run.page_count,
        redacted_char_count=run.redacted_char_count,
        redacted_text=run.redacted_text,
        feedback=(
            FeedbackResponse(
                verdict=feedback.verdict.value,
                field_corrections=feedback.field_corrections,
                notes=feedback.notes,
                created_at=feedback.created_at.isoformat(),
            )
            if feedback is not None
            else None
        ),
    )
