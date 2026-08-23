"""
Health check endpoint.
"""

from fastapi import APIRouter
from src.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {
        "status": "online",
        "app_name": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "partner_track": settings.partner_track
    }
