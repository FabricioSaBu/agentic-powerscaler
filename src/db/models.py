"""
SQLAlchemy ORM models mirroring the PowerScaler DBML schema:
trait catalog + ranked scales -> canonical characters/forms -> feats (evidence)
-> matchups -> contender profiles -> verdicts / cinematic scenes / research queries.
"""

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sa_enum(enum_cls: type[PyEnum]) -> SAEnum:
    """Persists the enum's string .value (e.g. "1v1"), not its Python .name (e.g. "ONE_V_ONE")."""
    return SAEnum(enum_cls, values_callable=lambda cls: [member.value for member in cls])


class TraitCategory(str, PyEnum):
    PHYSICAL = "physical"
    ENERGY_SOURCE = "energy_source"
    HAX = "hax"
    RESISTANCE = "resistance"
    META = "meta"


class TraitValueType(str, PyEnum):
    TIER = "tier"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    TEXT = "text"


class ItemCategory(str, PyEnum):
    WEAPON = "weapon"
    ARTIFACT = "artifact"
    ARMOR = "armor"
    TOOL = "tool"
    OTHER = "other"


class PowerStatus(str, PyEnum):
    """Whether a character's power development is finished, per continuity. Lives on the
    form (not the character) because the answer differs by series: Naruto in Shippuden is
    COMPLETE while Naruto in Boruto is ONGOING."""
    COMPLETE = "complete"   # series concluded; this version's power level is final
    ONGOING = "ongoing"     # still publishing; feats may be superseded
    UNKNOWN = "unknown"


class MatchFormat(str, PyEnum):
    ONE_V_ONE = "1v1"
    TEAM_BATTLE = "team_battle"
    FREE_FOR_ALL = "free_for_all"
    GAUNTLET = "gauntlet"
    RAID = "raid"


class MatchupStatus(str, PyEnum):
    PENDING = "pending"
    RESEARCHING = "researching"
    SCALING = "scaling"
    SCRIPTING = "scripting"
    COMPLETED = "completed"
    FAILED = "failed"


class DiffTier(str, PyEnum):
    LOW = "Low Diff"
    MID = "Mid Diff"
    HIGH = "High Diff"
    EXTREME = "Extreme Diff"
    INCONCLUSIVE = "Inconclusive"


class SceneType(str, PyEnum):
    INTRO = "intro"
    TEAM_COMBO = "team_combo"
    ELIMINATION = "elimination"
    CLIMAX = "climax"
    AFTERMATH = "aftermath"


class TierScale(Base):
    __tablename__ = "tier_scales"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    levels: Mapped[list["TierScaleLevel"]] = relationship(
        back_populates="tier_scale", order_by="TierScaleLevel.rank"
    )


class TierScaleLevel(Base):
    __tablename__ = "tier_scale_levels"
    __table_args__ = (UniqueConstraint("tier_scale_id", "rank", name="idx_scale_rank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tier_scale_id: Mapped[int] = mapped_column(ForeignKey("tier_scales.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, nullable=False)
    # Bounds in whatever unit the owning TraitCatalog rows declare (joules for AP/Durability,
    # m/s for Speed). Open-ended tiers (e.g. "Universe level" and above) leave these null.
    range_low: Mapped[Optional[float]] = mapped_column(Float)
    range_high: Mapped[Optional[float]] = mapped_column(Float)

    tier_scale: Mapped["TierScale"] = relationship(back_populates="levels")


class TraitCatalog(Base):
    __tablename__ = "trait_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[TraitCategory] = mapped_column(sa_enum(TraitCategory), nullable=False)
    value_type: Mapped[TraitValueType] = mapped_column(sa_enum(TraitValueType), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32))
    tier_scale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tier_scales.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tier_scale: Mapped[Optional["TierScale"]] = relationship()


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("name", "origin_universe", name="idx_character_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    origin_universe: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    forms: Mapped[list["CharacterForm"]] = relationship(back_populates="character")


class CharacterForm(Base):
    __tablename__ = "character_forms"
    __table_args__ = (
        UniqueConstraint("character_id", "version_era", "form_name", name="idx_form_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False)
    # Sentinel defaults (not NULL): SQLite treats NULLs as distinct, which would silently
    # defeat idx_form_identity for repeated base-form inserts.
    version_era: Mapped[str] = mapped_column(String, nullable=False, default="Canon")
    form_name: Mapped[str] = mapped_column(String, nullable=False, default="Base")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    traits_json: Mapped[Optional[str]] = mapped_column(Text)
    power_status: Mapped[PowerStatus] = mapped_column(
        sa_enum(PowerStatus), nullable=False, default=PowerStatus.UNKNOWN
    )
    status_note: Mapped[Optional[str]] = mapped_column(Text)
    # Display-only ("Naruto: Shippuden"); version_era stays the identity key in
    # idx_form_identity so a prettier label can never fragment character identity.
    series_label: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    character: Mapped["Character"] = relationship(back_populates="forms")
    feats: Mapped[list["Feat"]] = relationship(back_populates="character_form")
    contender_profiles: Mapped[list["ContenderProfile"]] = relationship(back_populates="character_form")


class Feat(Base):
    __tablename__ = "feats"
    __table_args__ = (Index("idx_feats_by_trait", "character_form_id", "trait_catalog_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_form_id: Mapped[int] = mapped_column(ForeignKey("character_forms.id"), nullable=False)
    # Nullable: raw evidence can be captured before classification, and a compound feat
    # proving multiple stats needs one row per trait it supports.
    trait_catalog_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trait_catalog.id"))

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    quote_excerpt: Mapped[Optional[str]] = mapped_column(Text)

    implied_numeric_value: Mapped[Optional[float]] = mapped_column(Float)
    implied_tier_scale_level_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tier_scale_levels.id"))
    scaling_note: Mapped[Optional[str]] = mapped_column(Text)

    is_low_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    story_context: Mapped[Optional[str]] = mapped_column(String)

    source_research_id: Mapped[int] = mapped_column(ForeignKey("research_queries.id"), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    character_form: Mapped["CharacterForm"] = relationship(back_populates="feats")
    trait: Mapped[Optional["TraitCatalog"]] = relationship()
    implied_tier_level: Mapped[Optional["TierScaleLevel"]] = relationship()
    source_research: Mapped["ResearchQuery"] = relationship(back_populates="feats")


class Item(Base):
    """A reusable equipment/artifact catalog (Mjolnir, Infinity Gauntlet, Potara earrings),
    resolved and disambiguated the same way Character/CharacterForm are: free-text input
    collapses onto one row instead of a fresh fuzzy string every matchup."""

    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("name", "origin_universe", name="idx_item_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    origin_universe: Mapped[str] = mapped_column(String, nullable=False, default="Unknown")
    aliases: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[ItemCategory] = mapped_column(sa_enum(ItemCategory), nullable=False, default=ItemCategory.OTHER)
    # What it does -- fed straight into the analyst's prompt. Items aren't independently
    # Parallel-researched (no ItemFeat table); this description is the whole of what the
    # analyst learns about the item.
    description: Mapped[Optional[str]] = mapped_column(Text)
    power_status: Mapped[PowerStatus] = mapped_column(
        sa_enum(PowerStatus), nullable=False, default=PowerStatus.UNKNOWN
    )
    status_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Matchup(Base):
    __tablename__ = "matchups"
    __table_args__ = (
        Index("idx_matchup_status", "status"),
        Index("idx_matchup_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    match_format: Mapped[MatchFormat] = mapped_column(
        sa_enum(MatchFormat), nullable=False, default=MatchFormat.ONE_V_ONE
    )
    environment: Mapped[str] = mapped_column(String, nullable=False, default="Neutral Multiversal Arena")
    rules: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[MatchupStatus] = mapped_column(
        sa_enum(MatchupStatus), nullable=False, default=MatchupStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    contenders: Mapped[list["ContenderProfile"]] = relationship(back_populates="matchup")
    verdict: Mapped[Optional["Verdict"]] = relationship(back_populates="matchup", uselist=False)
    scenes: Mapped[list["CinematicScene"]] = relationship(
        back_populates="matchup", order_by="CinematicScene.scene_number"
    )
    research_queries: Mapped[list["ResearchQuery"]] = relationship(back_populates="matchup")


class ContenderProfile(Base):
    __tablename__ = "contender_profiles"
    __table_args__ = (
        Index("idx_contender_matchup", "matchup_id"),
        Index("idx_contender_team", "matchup_id", "side_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("matchups.id"), nullable=False)
    character_form_id: Mapped[int] = mapped_column(ForeignKey("character_forms.id"), nullable=False)
    side_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    team_name: Mapped[Optional[str]] = mapped_column(String)
    custom_modifiers: Mapped[Optional[str]] = mapped_column(Text)

    matchup: Mapped["Matchup"] = relationship(back_populates="contenders")
    character_form: Mapped["CharacterForm"] = relationship(back_populates="contender_profiles")
    items: Mapped[list["ContenderItem"]] = relationship(back_populates="contender_profile")


class ContenderItem(Base):
    """Links a matchup side to a reusable Item. Many-to-many at the DB level (an Item can be
    wielded across many matchups), but each row's usage_note is scoped to this matchup only --
    same relationship handicaps have to ContenderProfile.custom_modifiers."""

    __tablename__ = "contender_items"
    __table_args__ = (Index("idx_contender_item_profile", "contender_profile_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contender_profile_id: Mapped[int] = mapped_column(ForeignKey("contender_profiles.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    usage_note: Mapped[Optional[str]] = mapped_column(Text)

    contender_profile: Mapped["ContenderProfile"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("matchups.id"), unique=True, nullable=False)
    winning_side: Mapped[Optional[int]] = mapped_column(Integer)
    winning_team_name: Mapped[Optional[str]] = mapped_column(String)
    winning_contender_ids: Mapped[Optional[str]] = mapped_column(Text)

    diff_tier: Mapped[DiffTier] = mapped_column(sa_enum(DiffTier), nullable=False)
    summary_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    winning_factors: Mapped[str] = mapped_column(Text, nullable=False)
    elimination_order: Mapped[Optional[str]] = mapped_column(Text)

    # Outcome distribution in whole percent, summing to 100. Nullable because verdicts
    # predating this column have no distribution (see _COLUMN_MIGRATIONS in db/base.py).
    win_probability_a: Mapped[Optional[int]] = mapped_column(Integer)
    win_probability_b: Mapped[Optional[int]] = mapped_column(Integer)
    tie_probability: Mapped[Optional[int]] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    matchup: Mapped["Matchup"] = relationship(back_populates="verdict")


# Which outcome a stored script narrates. The canonical winner's scenario and the two
# counterfactuals coexist per matchup, so scripts are keyed on (matchup, scenario).
SCENARIO_A_WINS = "a_wins"
SCENARIO_B_WINS = "b_wins"
SCENARIO_TIE = "tie"
VALID_SCENARIOS = {SCENARIO_A_WINS, SCENARIO_B_WINS, SCENARIO_TIE}


class CinematicScene(Base):
    __tablename__ = "cinematic_scenes"
    __table_args__ = (
        UniqueConstraint("matchup_id", "scenario", "scene_number", name="idx_scene_scenario_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    matchup_id: Mapped[int] = mapped_column(ForeignKey("matchups.id"), nullable=False)
    scenario: Mapped[str] = mapped_column(String, nullable=False, default=SCENARIO_A_WINS)
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_type: Mapped[Optional[SceneType]] = mapped_column(sa_enum(SceneType))
    location: Mapped[Optional[str]] = mapped_column(String)
    atmosphere: Mapped[Optional[str]] = mapped_column(Text)
    dialogue: Mapped[Optional[str]] = mapped_column(Text)
    shots: Mapped[str] = mapped_column(Text, nullable=False)

    matchup: Mapped["Matchup"] = relationship(back_populates="scenes")


class ResearchQuery(Base):
    __tablename__ = "research_queries"
    __table_args__ = (
        Index("idx_research_matchup", "matchup_id"),
        Index("idx_research_character", "character_form_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: null when researched via offline pre-seeding (no matchup exists yet),
    # populated when researched live during a user-triggered matchup.
    matchup_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matchups.id"))
    character_form_id: Mapped[Optional[int]] = mapped_column(ForeignKey("character_forms.id"))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    matchup: Mapped[Optional["Matchup"]] = relationship(back_populates="research_queries")
    character_form: Mapped[Optional["CharacterForm"]] = relationship()
    feats: Mapped[list["Feat"]] = relationship(back_populates="source_research")
