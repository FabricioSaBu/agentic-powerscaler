"""
PowerScaler API Endpoints.
Provides REST endpoints for submitting matchups and generating power scaling reports.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.base import get_session
from src.models.matchup import MAX_TEAM_SIZE, ContenderSpec, PowerScalerMatchupRequest, PowerScalerReport
from src.models.preview import MatchupResolution
from src.services.powerscaler_service import PowerScalerService
from src.core.exceptions import PowerScalerException

router = APIRouter(prefix="/matchup", tags=["PowerScaler"])
powerscaler_service = PowerScalerService()


class MatchupPreviewRequest(BaseModel):
    # Preferred shape: rosters of 1-3 members per side.
    team_a: List[ContenderSpec] = Field(default_factory=list)
    team_b: List[ContenderSpec] = Field(default_factory=list)

    # Legacy 1v1 shape, folded into single-member rosters when the team lists are empty.
    contender_a: Optional[str] = Field(default=None, json_schema_extra={"example": "naruto"})
    contender_b: Optional[str] = Field(default=None, json_schema_extra={"example": "luffy"})
    item_a: str = Field(default="", json_schema_extra={"example": "mjolnir"})
    item_b: str = Field(default="")

    def rosters(self):
        def clean(team):
            return [m for m in team if m.name and m.name.strip()][:MAX_TEAM_SIZE]

        team_a, team_b = clean(self.team_a), clean(self.team_b)
        if not team_a and self.contender_a:
            team_a = [ContenderSpec(name=self.contender_a, item_queries=[self.item_a] if self.item_a else [])]
        if not team_b and self.contender_b:
            team_b = [ContenderSpec(name=self.contender_b, item_queries=[self.item_b] if self.item_b else [])]
        return team_a, team_b


@router.post("/preview", response_model=MatchupResolution, status_code=status.HTTP_200_OK)
async def preview_matchup(request: MatchupPreviewRequest, session: AsyncSession = Depends(get_session)):
    """
    Resolves free-text roster members into concrete, choosable character versions before
    the expensive research pipeline runs -- including whether each version's power development
    is complete (series finished) or ongoing (still publishing). Also resolves each member's
    equipment/artifacts, with disambiguation when an item name is ambiguous.
    """
    try:
        team_a, team_b = request.rosters()
        if not team_a or not team_b:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Both sides need at least one contender.",
            )
        return await powerscaler_service.resolve_versions(team_a, team_b, session)
    except HTTPException:
        raise
    except PowerScalerException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class ScenarioScriptRequest(BaseModel):
    scenario: str = Field(
        default="a_wins",
        json_schema_extra={"example": "b_wins"},
        description="a_wins | b_wins | tie -- which outcome the screenplay should narrate",
    )


@router.post("/{report_id}/script", status_code=status.HTTP_200_OK)
async def scenario_script(
    report_id: str, request: ScenarioScriptRequest, session: AsyncSession = Depends(get_session)
):
    """
    Writes (or replays) the cinematic screenplay for one outcome of an already-evaluated
    matchup -- including counterfactuals: the losing side's victory, or a mutual draw.
    Scripts are stored per (matchup, scenario), so repeat requests cost no LLM call.
    """
    try:
        scenes, from_cache, label = await powerscaler_service.generate_scenario_script(
            report_id, request.scenario, session
        )
        return {
            "report_id": report_id,
            "scenario": request.scenario,
            "scenario_label": label,
            "from_cache": from_cache,
            "scenes": scenes,
        }
    except PowerScalerException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/evaluate", response_model=PowerScalerReport, status_code=status.HTTP_200_OK)
async def evaluate_matchup(request: PowerScalerMatchupRequest, session: AsyncSession = Depends(get_session)):
    """
    Submits a hypothetical battle matchup between contenders.
    Scouts feats via Parallel API, evaluates dimensional scaling, and generates a cinematic battle script.
    """
    try:
        # human_review stays off here: the JSON API is non-interactive, so its runs
        # never pause at the review gate.
        report, _pending, _thread_id = await powerscaler_service.run_matchup_pipeline(request, session)
        return report
    except PowerScalerException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
