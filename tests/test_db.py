import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import (
    Character,
    CharacterForm,
    ContenderProfile,
    DiffTier,
    Feat,
    MatchFormat,
    Matchup,
    ResearchQuery,
    Verdict,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def test_schema_round_trips_a_full_matchup(db_session):
    character = Character(name="Goku", origin_universe="Dragon Ball Super")
    form = CharacterForm(character=character, form_name="Ultra Instinct")
    db_session.add_all([character, form])
    await db_session.flush()

    matchup = Matchup(report_id="ps-rep-test1", title="Goku vs Superman", match_format=MatchFormat.ONE_V_ONE)
    db_session.add(matchup)
    await db_session.flush()

    research = ResearchQuery(matchup_id=matchup.id, character_form_id=form.id, query_text="Goku feats")
    db_session.add(research)
    await db_session.flush()

    contender = ContenderProfile(matchup_id=matchup.id, character_form_id=form.id, side_index=1)
    feat = Feat(
        character_form_id=form.id,
        title="Destroyed a moon-sized meteor",
        source_research_id=research.id,
    )
    verdict = Verdict(
        matchup_id=matchup.id,
        diff_tier=DiffTier.HIGH,
        summary_verdict="Goku wins.",
        winning_factors="[]",
    )
    db_session.add_all([contender, feat, verdict])
    await db_session.commit()

    assert feat.trait_catalog_id is None
    assert verdict.matchup_id == matchup.id
    assert contender.character_form_id == form.id


async def test_match_format_persists_as_value_not_enum_name(db_session):
    matchup = Matchup(report_id="ps-rep-test2", title="Team battle", match_format=MatchFormat.TEAM_BATTLE)
    db_session.add(matchup)
    await db_session.commit()

    raw = await db_session.get(Matchup, matchup.id)
    assert raw.match_format == MatchFormat.TEAM_BATTLE
    assert raw.match_format.value == "team_battle"
