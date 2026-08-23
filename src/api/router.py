"""
Main Router Aggregator for API v1.
"""

from fastapi import APIRouter
from src.api.v1.health import router as health_router
from src.api.v1.powerscaler import router as powerscaler_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(powerscaler_router)
