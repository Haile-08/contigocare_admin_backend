"""Prometheus metrics for the insurance analysis console.

The counters here are chosen to answer operational questions, not to be
comprehensive. Two are worth calling out because they are security signals
rather than performance ones:

``redaction_blocked_total`` rising means text is reaching the submit endpoint
with identifiers still in it — either the detector is missing a pattern or the
review UI is letting admins click through. Either way it needs a human.

``analysis_evidence_failures_total`` rising means the model is citing passages
that are not in the document. That is hallucination, measured directly, and it
is the single best early warning that a prompt or model change made the agent
worse.
"""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
)
from starlette_prometheus import (
    PrometheusMiddleware,
    metrics,
)

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

db_connections = Gauge("db_connections", "Number of active database connections")

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

login_attempts_total = Counter(
    "login_attempts_total",
    "Password authentication attempts",
    ["outcome"],  # success | invalid_credentials | locked | inactive
)

mfa_verifications_total = Counter(
    "mfa_verifications_total",
    "TOTP verification attempts",
    ["outcome"],  # success | invalid | replay | recovery_code
)

refresh_token_reuse_total = Counter(
    "refresh_token_reuse_total",
    "Refresh tokens presented after already being exchanged — indicates theft",
)

password_reset_requests_total = Counter(
    "password_reset_requests_total",
    "Password reset links requested",
    ["outcome"],  # sent | unknown_account | inactive | send_failed
)

password_resets_total = Counter(
    "password_resets_total",
    "Password reset links redeemed",
    ["outcome"],  # success | invalid_token | expired | weak_password
)

# ---------------------------------------------------------------------------
# Document intake and redaction
# ---------------------------------------------------------------------------

documents_processed_total = Counter(
    "documents_processed_total",
    "Documents parsed into text",
    ["kind"],  # pdf_text | pdf_ocr | pdf_mixed | image_ocr | plain_text
)

document_extraction_duration_seconds = Histogram(
    "document_extraction_duration_seconds",
    "Time spent parsing and OCRing an upload",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

redaction_entities_total = Counter(
    "redaction_entities_total",
    "Identifiers removed before the model call",
    ["category"],
)

redaction_blocked_total = Counter(
    "redaction_blocked_total",
    "Submissions refused because approved text still contained identifiers",
)

# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

analysis_runs_total = Counter(
    "analysis_runs_total",
    "Completed analysis runs",
    ["status"],  # succeeded | failed | blocked_by_redaction
)

analysis_duration_seconds = Histogram(
    "analysis_duration_seconds",
    "End-to-end model time for one analysis",
    ["model"],
    buckets=[1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0],
)

analysis_tokens_total = Counter(
    "analysis_tokens_total",
    "Tokens billed by the analysis agent",
    ["model", "direction"],  # direction: input | output
)

analysis_evidence_failures_total = Counter(
    "analysis_evidence_failures_total",
    "Extracted fields whose supporting quote could not be found in the document",
)

analysis_self_critique_total = Counter(
    "analysis_self_critique_total",
    "Self-critique repair passes",
    ["outcome"],  # applied | failed
)

analysis_feedback_total = Counter(
    "analysis_feedback_total",
    "Reviewer verdicts recorded",
    ["verdict"],  # correct | partially_correct | incorrect
)

analysis_deletions_total = Counter(
    "analysis_deletions_total",
    "Analysis runs erased at an operator's request",
    ["scope"],  # run | patient
)


def setup_metrics(app):
    """Set up Prometheus metrics middleware and endpoints.

    Args:
        app: FastAPI application instance
    """
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", metrics)
