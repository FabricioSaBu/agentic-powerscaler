"""
PowerScaler API Endpoints.
Provides REST endpoints for submitting matchups and generating power scaling reports.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.base import get_session
from src.models.matchup import PowerScalerMatchupRequest, PowerScalerReport
from src.services.powerscaler_service import PowerScalerService
from src.core.exceptions import PowerScalerException

router = APIRouter(prefix="/matchup", tags=["PowerScaler"])
powerscaler_service = PowerScalerService()


@router.post("/evaluate", response_model=PowerScalerReport, status_code=status.HTTP_200_OK)
async def evaluate_matchup(request: PowerScalerMatchupRequest, session: AsyncSession = Depends(get_session)):
    """
    Submits a hypothetical battle matchup between contenders.
    Scouts feats via Parallel API, evaluates dimensional scaling, and generates a cinematic battle script.
    """
    try:
        report = await powerscaler_service.run_matchup_pipeline(request, session)
        return report
    except PowerScalerException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
