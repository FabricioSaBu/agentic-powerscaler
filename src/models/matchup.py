"""
PowerScaler Domain Models.
Includes Contender, Feat, PowerStats, Verdict, and Battle Scene Script.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class Feat(BaseModel):
    title: str
    tier_category: str = Field(description="Speed, Strength, Durability, Hax/Abilities, Cosmology")
    description: str
    source_reference: Optional[str] = None


class ContenderStats(BaseModel):
    name: str
    origin_universe: str
    power_tier: str = Field(default="Unknown", description="e.g. Multiversal, Solar System, Planetary, Hypersonic")
    speed: str = Field(default="Immeasurable / MFTL+")
    strength: str = Field(default="Universal+")
    durability: str = Field(default="Universal+")
    hax_abilities: List[str] = Field(default_factory=list)
    key_feats: List[Feat] = Field(default_factory=list)


class PowerScalingVerdict(BaseModel):
    winner: str
    diff_tier: str = Field(default="Mid Diff", description="Low Diff, Mid Diff, High Diff, Extreme Diff")
    summary_verdict: str
    winning_factors: List[str] = Field(default_factory=list)
    contender_a_stats: ContenderStats
    contender_b_stats: ContenderStats


class CinematicShot(BaseModel):
    shot_number: int
    camera_angle: str
    action_description: str
    dialogue: Optional[str] = None
    vfx_notes: str


class CinematicBattleScene(BaseModel):
    scene_number: int
    location: str
    atmosphere: str
    shots: List[CinematicShot] = Field(default_factory=list)


class PowerScalerMatchupRequest(BaseModel):
    contender_a: str = Field(..., json_schema_extra={"example": "Goku (Ultra Instinct)"})
    contender_b: str = Field(..., json_schema_extra={"example": "Superman (Prime One Million)"})
    battle_environment: Optional[str] = Field(default="Neutral Multiversal Arena")
    include_cinematic_script: bool = Field(default=True)


class PowerScalerReport(BaseModel):
    report_id: str
    matchup: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    verdict: PowerScalingVerdict
    cinematic_battle_script: Optional[List[CinematicBattleScene]] = None
    parallel_search_queries: List[str] = Field(default_factory=list)
    sources_cited: List[str] = Field(default_factory=list)
