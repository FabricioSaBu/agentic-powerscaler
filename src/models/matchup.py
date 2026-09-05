"""
PowerScaler Domain Models.
Includes Contender, Feat, PowerStats, Verdict, and Battle Scene Script.
"""

from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime

from src.models.preview import CharacterVersionOption, ItemOption

MAX_TEAM_SIZE = 3
"""Each extra unknown member costs a Parallel search + extract + Gemini profile pass,
and every member grows the analyst prompt -- capped to keep latency and cost sane."""


class Feat(BaseModel):
    title: str
    tier_category: str = Field(description="Speed, Strength, Durability, Hax/Abilities, Cosmology")
    description: str
    source_reference: Optional[str] = None


class TraitEvidence(BaseModel):
    """One extracted trait, with the confidence the profiler assigned it."""
    code: str
    value_label: str
    confidence: Optional[float] = None


class ResearchTrail(BaseModel):
    """How this contender's numbers were actually obtained -- surfaced in the UI so a wrong
    result (e.g. a Super-era feat on a Buu-saga form) is visible instead of buried in the DB."""
    version_label: str = ""
    """The exact identity researched, e.g. "Vegeta (Dragon Ball Z, Super Saiyan 2)"."""

    query: str = ""
    """The Parallel search query that was issued."""

    sources: List[str] = Field(default_factory=list)
    reused_profile: bool = False
    """True when a stored profile was reused instead of researching fresh -- in which case
    the query/sources shown are the ones from the run that originally created it."""

    traits: List[TraitEvidence] = Field(default_factory=list)


class ContenderStats(BaseModel):
    name: str
    origin_universe: str
    power_tier: str = Field(default="Unknown", description="e.g. Multiversal, Solar System, Planetary, Hypersonic")
    speed: str = Field(default="Immeasurable / MFTL+")
    strength: str = Field(default="Universal+")
    durability: str = Field(default="Universal+")
    hax_abilities: List[str] = Field(default_factory=list)
    key_feats: List[Feat] = Field(default_factory=list)
    trail: Optional[ResearchTrail] = None


class PowerScalingVerdict(BaseModel):
    winner: str = Field(description="1v1: the exact raw contender name; teams: the winning side's joined member names")
    winning_side: int = Field(default=0, description="1 = Team A, 2 = Team B")
    diff_tier: str = Field(default="Mid Diff", description="Low Diff, Mid Diff, High Diff, Extreme Diff")
    summary_verdict: str
    winning_factors: List[str] = Field(default_factory=list)
    # Outcome distribution in whole percent; the three always sum to 100.
    win_probability_a: int = Field(default=0, description="Chance Team A / contender A wins, %")
    win_probability_b: int = Field(default=0, description="Chance Team B / contender B wins, %")
    tie_probability: int = Field(default=0, description="Chance of a tie/inconclusive outcome, %")
    team_a_stats: List[ContenderStats] = Field(default_factory=list)
    team_b_stats: List[ContenderStats] = Field(default_factory=list)


class ContenderSpec(BaseModel):
    """One roster member as submitted by the client -- and, after the preview step confirms
    selections, enriched with the resolved identity the pipeline should persist."""

    name: str
    handicaps: List[str] = Field(default_factory=list)
    item_queries: List[str] = Field(default_factory=list)
    # Free-text version request from the preview's "version not listed?" box ("GT era",
    # "pre-timeskip"). Forces re-resolution through Gemini even for DB-known characters,
    # with the hinted version recommended.
    version_hint: Optional[str] = None

    # Filled in from the confirmed preview resolution; None/empty on the raw legacy path.
    version: Optional[CharacterVersionOption] = None
    canonical: Optional[str] = None
    franchise: Optional[str] = None
    chosen_items: List[ItemOption] = Field(default_factory=list)


class CinematicShot(BaseModel):
    shot_number: int = 1
    camera_angle: str = ""
    action_description: str = ""
    dialogue: Optional[str] = None
    vfx_notes: str = ""


class CinematicBattleScene(BaseModel):
    scene_number: int = 1
    location: str = ""
    atmosphere: str = ""
    shots: List[CinematicShot] = Field(default_factory=list)


class ScriptOutline(BaseModel):
    """Gemini response_schema for a scenario screenplay. Like the other structured contracts,
    every field defaults so generate_structured() can return an empty instance offline."""
    scenes: List[CinematicBattleScene] = Field(default_factory=list)


class PowerScalerMatchupRequest(BaseModel):
    # Preferred shape: full rosters, 1-3 members per side.
    team_a: List[ContenderSpec] = Field(default_factory=list)
    team_b: List[ContenderSpec] = Field(default_factory=list)

    # Legacy 1v1 shape -- kept so the JSON API works without rosters (and the test contract:
    # verdict.winner must be one of these exact strings on this path).
    contender_a: Optional[str] = Field(default=None, json_schema_extra={"example": "Goku (Ultra Instinct)"})
    contender_b: Optional[str] = Field(default=None, json_schema_extra={"example": "Superman (Prime One Million)"})
    battle_environment: Optional[str] = Field(default="Neutral Multiversal Arena")
    include_cinematic_script: bool = Field(default=True)

    # Supplied by the /matchup/preview step once the user confirms which versions to use.
    # When omitted, the raw contender strings are used as the character identity (legacy
    # behavior), so the JSON API still works without a preview round-trip.
    contender_a_version: Optional[CharacterVersionOption] = None
    contender_b_version: Optional[CharacterVersionOption] = None
    contender_a_canonical: Optional[str] = None
    contender_b_canonical: Optional[str] = None
    contender_a_franchise: Optional[str] = None
    contender_b_franchise: Optional[str] = None

    # Free-text, one-off battle constraint per side (e.g. "no Instant Transmission",
    # "starts at 50% stamina"). Unlike character data, a handicap is scoped to this single
    # matchup -- it is never looked up or reused, only stored for provenance and fed to the
    # analyst's reasoning.
    contender_a_handicap: Optional[str] = Field(default=None, json_schema_extra={"example": "No access to Super Saiyan forms"})
    contender_b_handicap: Optional[str] = None

    # Reusable equipment/artifact per side, resolved (and disambiguated) by the same preview
    # step as versions. When omitted, this side simply has no item.
    contender_a_item: Optional[ItemOption] = None
    contender_b_item: Optional[ItemOption] = None
    # The raw text the user typed ("gauntlet") -- recorded as an alias on the resolved Item so
    # the same free text hits the DB path directly next time, without this the alias would
    # only ever be the already-canonical resolved name.
    contender_a_item_query: Optional[str] = None
    contender_b_item_query: Optional[str] = None

    def rosters(self) -> Tuple[List[ContenderSpec], List[ContenderSpec]]:
        """Normalizes to (team_a, team_b) member lists. Rosters win when supplied; otherwise
        the legacy flat 1v1 fields are folded into single-member teams, so old JSON callers
        (and the test suite) behave exactly as before."""

        def clean(team: List[ContenderSpec]) -> List[ContenderSpec]:
            return [m for m in team if m.name and m.name.strip()][:MAX_TEAM_SIZE]

        team_a, team_b = clean(self.team_a), clean(self.team_b)
        if team_a and team_b:
            return team_a, team_b

        def legacy(side: str) -> List[ContenderSpec]:
            name = getattr(self, f"contender_{side}")
            if not name:
                return []
            handicap = getattr(self, f"contender_{side}_handicap")
            item = getattr(self, f"contender_{side}_item")
            return [ContenderSpec(
                name=name,
                handicaps=[handicap] if handicap else [],
                version=getattr(self, f"contender_{side}_version"),
                canonical=getattr(self, f"contender_{side}_canonical"),
                franchise=getattr(self, f"contender_{side}_franchise"),
                chosen_items=[item] if item else [],
                item_queries=[q for q in [getattr(self, f"contender_{side}_item_query")] if q],
            )]

        return team_a or legacy("a"), team_b or legacy("b")


class PowerScalerReport(BaseModel):
    report_id: str
    matchup: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    verdict: PowerScalingVerdict
    cinematic_battle_script: Optional[List[CinematicBattleScene]] = None
    parallel_search_queries: List[str] = Field(default_factory=list)
    sources_cited: List[str] = Field(default_factory=list)
