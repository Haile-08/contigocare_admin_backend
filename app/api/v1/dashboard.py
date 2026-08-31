"""The dashboard endpoint.

Every figure here is computed from stored runs and stored verdicts. There is no
number on this screen the database cannot account for, which is the difference
between a dashboard and a decoration.

The one worth watching is ``accuracy_rate``: the share of *reviewed* analyses
the reviewer marked correct. Volume and latency say the service is running;
accuracy is the only figure that says the agent is any good, and it is the one
that moves when a prompt version changes.
"""

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from app.api.v1.auth import get_current_admin
from app.api.v1.insurance import summarize_run
from app.models.admin import Admin
from app.schemas.insurance import (
    AnalysisSummary,
    DashboardResponse,
)
from app.services.database import database_service

router = APIRouter()
db = database_service


def _ratio(numerator: int, denominator: int) -> float:
    """Divide safely and round for display.

    Args:
        numerator: Top.
        denominator: Bottom.

    Returns:
        float: The ratio, or 0.0 when the denominator is zero — an empty
        console shows 0%, not a crash and not NaN.
    """
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


@router.get("", response_model=DashboardResponse)
async def read_dashboard(
    limit: int = Query(default=15, ge=1, le=50),
    admin: Admin = Depends(get_current_admin),
):
    """Return the console's overview figures.

    Args:
        limit: How many recent runs to list.
        admin: The signed-in operator.

    Returns:
        DashboardResponse: Aggregates and recent activity.
    """
    metrics = await db.dashboard_metrics(recent_limit=limit)
    reviewed, correct = await db.reviewed_counts()

    # Shaped by the same helper the policy list uses, so a row on the dashboard
    # and a row on the policy list cannot drift apart.
    recent: list[AnalysisSummary] = [
        summarize_run(run, verdict) for run, verdict in metrics["recent"]
    ]

    total = metrics["total"]

    return DashboardResponse(
        total_analyses=total,
        analyses_last_7_days=metrics["last_7_days"],
        distinct_patients=metrics["distinct_patients"],
        success_rate=_ratio(metrics["succeeded"], total),
        review_rate=_ratio(reviewed, metrics["succeeded"]),
        accuracy_rate=_ratio(correct, reviewed),
        blocked_count=metrics["blocked"],
        median_latency_ms=metrics["median_latency_ms"],
        redaction_totals=metrics["redaction_totals"],
        verdict_breakdown={
            (key.value if hasattr(key, "value") else str(key)): value
            for key, value in metrics["verdicts"].items()
        },
        recent=recent,
    )
