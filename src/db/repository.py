"""
Small DB helpers shared by the agent pipeline. Kept deliberately thin: agents call these
instead of writing raw SQLAlchemy queries inline.
"""

import json
import re
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Character,
    CharacterForm,
    ContenderItem,
    ContenderProfile,
    Item,
    ItemCategory,
    PowerStatus,
    ResearchQuery,
    TraitCatalog,
    TraitCategory,
    TraitValueType,
)
from src.models.parallel import ParallelSearchResponse
from src.models.preview import CharacterVersionOption, ItemOption

_VALID_CATEGORIES = {c.value for c in TraitCategory}
_VALID_VALUE_TYPES = {v.value for v in TraitValueType}
_VALID_POWER_STATUSES = {s.value for s in PowerStatus}
_VALID_ITEM_CATEGORIES = {c.value for c in ItemCategory}


def normalize_trait_code(raw_code: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "_", raw_code.strip().lower())
    return code.strip("_")


def alias_key(raw_name: str) -> str:
    """Aliases are stored lowercased in a JSON list so a free-text input can be matched back
    to its canonical character. Shared with ResolverAgent's lookup."""
    return raw_name.strip().lower()


def _add_alias(character: Character, raw_name: str) -> None:
    key = alias_key(raw_name)
    if not key or key == alias_key(character.name):
        return
    try:
        aliases = json.loads(character.aliases) if character.aliases else []
    except json.JSONDecodeError:
        aliases = []
    if key not in aliases:
        aliases.append(key)
        character.aliases = json.dumps(aliases)


def _coerce_power_status(raw: Optional[str]) -> PowerStatus:
    """The status comes from LLM free text, so anything unexpected degrades to UNKNOWN
    rather than raising."""
    if raw and raw.strip().lower() in _VALID_POWER_STATUSES:
        return PowerStatus(raw.strip().lower())
    return PowerStatus.UNKNOWN


def _coerce_item_category(raw: Optional[str]) -> ItemCategory:
    if raw and raw.strip().lower() in _VALID_ITEM_CATEGORIES:
        return ItemCategory(raw.strip().lower())
    return ItemCategory.OTHER


async def get_or_create_character_form(
    session: AsyncSession,
    contender_name: str,
    version: Optional[CharacterVersionOption] = None,
    canonical_name: Optional[str] = None,
    franchise: Optional[str] = None,
) -> CharacterForm:
    """Resolves contender input to a canonical, reusable CharacterForm, creating it if new.

    With `version` (supplied by ResolverAgent via the preview step), the character is keyed on
    the resolved identity -- (canonical_name, franchise) + (version_era, form_name) -- so
    "Goku" and "Goku (Ultra Instinct)" collapse onto one Character with two forms, and the
    version's power_status is persisted.

    Without it, the legacy behavior applies: the raw input string is the character identity.
    That keeps the JSON API usable without a preview round-trip."""
    name = canonical_name or contender_name
    universe = franchise or "Unknown"
    era = version.version_era if version else "Canon"
    form_name = version.form_name if version else "Base"

    stmt = (
        select(CharacterForm)
        .join(Character)
        .where(
            Character.name == name,
            Character.origin_universe == universe,
            CharacterForm.version_era == era,
            CharacterForm.form_name == form_name,
        )
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    character = (
        await session.execute(
            select(Character).where(Character.name == name, Character.origin_universe == universe)
        )
    ).scalar_one_or_none()
    if character is None:
        character = Character(name=name, origin_universe=universe)
        session.add(character)
        await session.flush()
    # Record what the user actually typed, so the next "naruto" resolves to the stored
    # "Naruto Uzumaki" instead of re-resolving and inventing fresh version labels.
    _add_alias(character, contender_name)

    form = CharacterForm(
        character_id=character.id,
        version_era=era,
        form_name=form_name,
        is_default=True,
        power_status=_coerce_power_status(version.power_status if version else None),
        status_note=version.status_note if version else None,
        series_label=version.series_label if version else None,
    )
    session.add(form)
    await session.flush()
    return form


async def get_or_create_item(session: AsyncSession, item: ItemOption, raw_query: str) -> Item:
    """Resolves an item to a reusable Item row, creating it if new -- same identity pattern as
    get_or_create_character_form: (name, origin_universe) is the key, and the raw text the user
    typed ("gauntlet") is recorded as an alias so the next lookup hits the DB path for free."""
    name = item.name or raw_query
    universe = item.origin_universe or "Unknown"

    existing = (
        await session.execute(select(Item).where(Item.name == name, Item.origin_universe == universe))
    ).scalar_one_or_none()
    if existing is not None:
        _add_alias(existing, raw_query)
        return existing

    created = Item(
        name=name,
        origin_universe=universe,
        category=_coerce_item_category(item.category),
        description=item.description or None,
        power_status=_coerce_power_status(item.power_status),
        status_note=item.status_note or None,
    )
    session.add(created)
    await session.flush()
    _add_alias(created, raw_query)
    return created


async def create_contender_item(
    session: AsyncSession, contender_profile_id: int, item_id: int, usage_note: Optional[str] = None
) -> ContenderItem:
    link = ContenderItem(contender_profile_id=contender_profile_id, item_id=item_id, usage_note=usage_note)
    session.add(link)
    await session.flush()
    return link


async def create_contender_profile(
    session: AsyncSession,
    matchup_id: int,
    character_form_id: int,
    side_index: int,
    custom_modifiers: Optional[str] = None,
    team_name: Optional[str] = None,
) -> ContenderProfile:
    """`custom_modifiers` holds one-off handicaps for this matchup only (e.g. "no Instant
    Transmission") -- they live on the profile, not the reusable CharacterForm, since a
    handicap is almost never reused across matchups the way a character is. `team_name`
    is set ("Team A"/"Team B") only for team battles."""
    profile = ContenderProfile(
        matchup_id=matchup_id,
        character_form_id=character_form_id,
        side_index=side_index,
        custom_modifiers=custom_modifiers,
        team_name=team_name,
    )
    session.add(profile)
    await session.flush()
    return profile


async def persist_research_results(
    session: AsyncSession,
    matchup_id: int,
    character_form_id: Optional[int],
    query_text: str,
    response: ParallelSearchResponse,
) -> List[ResearchQuery]:
    records = [
        ResearchQuery(
            matchup_id=matchup_id,
            character_form_id=character_form_id,
            query_text=query_text,
            source_url=item.url,
            snippet=item.snippet,
        )
        for item in response.results
    ]
    session.add_all(records)
    await session.flush()
    return records


async def get_or_create_trait_catalog(
    session: AsyncSession, raw_code: str, display_name: str, category: str, value_type: str
) -> TraitCatalog:
    """Looks up a trait by normalized code, auto-registering it if it's genuinely novel
    (e.g. a franchise-specific power source never seen before). Falls back to safe defaults
    if the LLM proposed an invalid category/value_type."""
    code = normalize_trait_code(raw_code)
    existing = (await session.execute(select(TraitCatalog).where(TraitCatalog.code == code))).scalar_one_or_none()
    if existing is not None:
        return existing

    safe_category = TraitCategory(category if category in _VALID_CATEGORIES else "meta")
    safe_value_type = TraitValueType(value_type if value_type in _VALID_VALUE_TYPES else "text")
    trait = TraitCatalog(
        code=code,
        display_name=display_name,
        category=safe_category,
        value_type=safe_value_type,
        description="Auto-registered by the character extraction pipeline.",
    )
    session.add(trait)
    await session.flush()
    return trait
