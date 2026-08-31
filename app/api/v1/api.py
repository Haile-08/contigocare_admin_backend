"""API v1 router configuration.

Three routers, matching the three things this service does: authenticate an
operator, analyse a policy, and report on what has been analysed.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.insurance import router as insurance_router
from app.core.logging import logger

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(insurance_router, prefix="/insurance", tags=["Insurance"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])


@api_router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        dict: Health status information.
    """
    logger.info("health_check_called")
    return {"status": "healthy"}
