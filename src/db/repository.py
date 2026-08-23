"""
Small DB helpers shared by the agent pipeline. Kept deliberately thin: agents call these
instead of writing raw SQLAlchemy queries inline.
"""

import re
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Character, CharacterForm, ContenderProfile, ResearchQuery, TraitCatalog, TraitCategory, TraitValueType
from src.models.parallel import ParallelSearchResponse

_VALID_CATEGORIES = {c.value for c in TraitCategory}
_VALID_VALUE_TYPES = {v.value for v in TraitValueType}


def normalize_trait_code(raw_code: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "_", raw_code.strip().lower())
    return code.strip("_")


async def get_or_create_character_form(session: AsyncSession, contender_name: str) -> CharacterForm:
    """Resolves free-text contender input (e.g. "Goku (Ultra Instinct)") to a canonical,
    reusable CharacterForm, creating it if new. Simplification: the full input string is
    used as the character identity for now (no name/form-state parsing yet), so "Goku" and
    "Goku (Ultra Instinct)" are treated as distinct characters until that's built."""
    stmt = (
        select(CharacterForm)
        .join(Character)
        .where(Character.name == contender_name, Character.origin_universe == "Unknown")
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    character = Character(name=contender_name, origin_universe="Unknown")
    session.add(character)
    await session.flush()

    form = CharacterForm(character_id=character.id, is_default=True)
    session.add(form)
    await session.flush()
    return form


async def create_contender_profile(
    session: AsyncSession, matchup_id: int, character_form_id: int, side_index: int
) -> ContenderProfile:
    profile = ContenderProfile(matchup_id=matchup_id, character_form_id=character_form_id, side_index=side_index)
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
