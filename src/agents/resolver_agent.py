"""
Character Version Resolver Agent.

Turns free-text roster input ("naruto", + "gauntlet" as an item) into concrete, choosable
versions ("Naruto Uzumaki -- Shippuden, power development COMPLETE") *before* the expensive
research pipeline runs, so the user can confirm or override which versions are used.

Mirrors ProfilerAgent's known/unknown split: characters/items already in the DB are resolved
from their stored rows at zero LLM cost; all the unknowns across both teams share a single
Gemini call. No Parallel research here -- this step must stay fast.
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.db.models import Character, CharacterForm, Item
from src.db.repository import alias_key
from src.models.matchup import ContenderSpec
from src.models.preview import (
    CharacterVersionOption,
    ContenderResolution,
    ItemOption,
    ItemResolution,
    MatchupResolution,
)

_SYSTEM_INSTRUCTION = (
    "You are a canon expert on fictional characters across manga, anime, comics, and games. "
    "You identify which continuity/series versions of a character exist, whether that "
    "version's power level is final, and what named equipment/artifacts actually do."
)

_CHARACTER_RULES = (
    "For each listed member, return one entry (echoing its input_name exactly) with:\n"
    "- canonical_name: the character's proper full name.\n"
    "- franchise: the series/universe they belong to.\n"
    "- options: 2-4 meaningfully distinct versions, ordered strongest/latest first. Give each "
    "a short version_era key (e.g. 'Shippuden', 'Boruto', 'Post-Timeskip', 'Part I'), a "
    "series_label for display, and the form_name of that version's peak power state.\n"
    "- power_status per version: 'complete' if that series has finished and the version's "
    "power is final; 'ongoing' if the series is still being published and the character may "
    "still grow; 'unknown' if genuinely unclear.\n"
    "- status_note: one short sentence justifying the status (mention the year a series "
    "concluded, or that it is still running).\n"
    "- summary: one short sentence on what that version can actually do. Never leave it empty.\n"
    "- Mark exactly ONE option per member with is_recommended=true: the version most people "
    "mean by default, usually the character's PEAK within their own primary series -- not a "
    "later spin-off where they appear as a supporting or depowered character. (For Naruto "
    "that means Shippuden, not Boruto.)\n"
    "If an input already names a specific version or form (e.g. 'Goku Ultra Instinct'), make "
    "that the recommended option, but still list the other versions as alternatives.\n"
)

_ITEM_RULES = (
    "Where a member lists item queries, also fill that entry's items (one ItemResolution per "
    "query, echoing the query string, in the same order):\n"
    "- 1-3 candidates ordered best-guess first, each with the item's proper name, "
    "origin_universe, category (weapon | artifact | armor | tool | other), and a 1-2 sentence "
    "description of what it actually does or grants -- this description is the ONLY item "
    "information that reaches the power-scaling analysis, so make it count.\n"
    "- power_status / status_note: same meaning as for character versions.\n"
    "- Mark exactly one candidate per query with is_recommended=true.\n"
    "- Set ambiguous=true and fill clarifying_question ONLY when the query is a genuine "
    "toss-up between unrelated items across franchises (e.g. 'gauntlet' alone) -- not merely "
    "because you list multiple candidates.\n"
)


def _fallback_member(spec: ContenderSpec) -> ContenderResolution:
    """Never render an empty preview card: if the LLM omitted a member (or we're offline),
    fall back to the raw name with a single default option -- the legacy identity."""
    return ContenderResolution(
        input_name=spec.name,
        canonical_name=spec.name,
        options=[CharacterVersionOption(is_recommended=True)],
    )


class ResolverAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="Version Resolver Agent",
            role="Character Identity & Continuity Resolver",
            gemini_service=gemini_service,
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        """BaseAgent contract; the resolver runs ahead of the graph via resolve()."""
        context["resolution"] = await self.resolve(
            session, context.get("team_a_specs", []), context.get("team_b_specs", [])
        )
        return context

    async def resolve(
        self,
        session: AsyncSession,
        team_a: List[ContenderSpec],
        team_b: List[ContenderSpec],
    ) -> MatchupResolution:
        # Phase 1: everything the DB already knows, at zero LLM cost.
        known: Dict[str, List[Tuple[Optional[ContenderResolution], List[Optional[ItemResolution]]]]] = {}
        needs_llm: List[Tuple[str, int, ContenderSpec, bool, List[str]]] = []
        for side, team in (("a", team_a), ("b", team_b)):
            known[side] = []
            for index, spec in enumerate(team):
                known_char = await self._from_db(session, spec.name)
                known_items = [await self._item_from_db(session, q) for q in spec.item_queries]
                known[side].append((known_char, known_items))
                missing_items = [q for q, k in zip(spec.item_queries, known_items) if k is None]
                # A version hint ("GT era") forces LLM resolution even for a DB-known
                # character -- the whole point is asking for a version we DON'T have stored.
                resolve_char = known_char is None or bool(spec.version_hint)
                if resolve_char or missing_items:
                    needs_llm.append((side, index, spec, resolve_char, missing_items))

        guessed: Dict[Tuple[str, int], ContenderResolution] = {}
        if needs_llm:
            self.log(f"Resolving {len(needs_llm)} unknown roster member(s)/item(s) via Gemini.")
            guessed = await self._from_llm(needs_llm)
        else:
            self.log("Entire roster (characters + items) resolved from DB.")

        # Phase 2: merge -- stored data wins, the LLM only fills the gaps.
        def build_team(side: str, team: List[ContenderSpec]) -> List[ContenderResolution]:
            members = []
            for index, spec in enumerate(team):
                known_char, known_items = known[side][index]
                llm = guessed.get((side, index))
                if spec.version_hint and llm and known_char:
                    # Hinted re-resolution of a known character: the LLM's options lead
                    # (they honor the hint), stored versions stay available below them, and
                    # the stored canonical identity wins so Character rows never fragment.
                    llm.canonical_name = known_char.canonical_name
                    llm.franchise = known_char.franchise
                    seen = {(o.version_era, o.form_name) for o in llm.options}
                    for option in known_char.options:
                        if (option.version_era, option.form_name) not in seen:
                            llm.options.append(option.model_copy(update={"is_recommended": False}))
                    member = llm
                else:
                    member = known_char or llm or _fallback_member(spec)
                member.input_name = spec.name
                member.items = [
                    stored
                    or self._llm_item(llm, query)
                    or ItemResolution(query=query)
                    for query, stored in zip(spec.item_queries, known_items)
                ]
                members.append(member)
            return members

        return MatchupResolution(
            team_a=build_team("a", team_a),
            team_b=build_team("b", team_b),
        )

    @staticmethod
    def _llm_item(llm: Optional[ContenderResolution], query: str) -> Optional[ItemResolution]:
        if llm is None:
            return None
        for item in llm.items:
            if alias_key(item.query) == alias_key(query):
                return item
        # The model didn't echo the query; take the next unclaimed resolution if any.
        return llm.items[0] if llm.items else None

    async def _from_db(self, session: AsyncSession, raw_name: str) -> Optional[ContenderResolution]:
        """Builds options from previously-stored forms, matching the character name
        case-insensitively. Returns None if this character has never been profiled."""
        key = alias_key(raw_name)
        stmt = (
            select(Character, CharacterForm)
            .join(CharacterForm, CharacterForm.character_id == Character.id)
            .where(
                or_(
                    func.lower(Character.name) == key,
                    # Match what the user typed last time ("naruto" -> "Naruto Uzumaki"),
                    # otherwise canonicalized characters would never be found again and
                    # every run would re-resolve with slightly different version labels.
                    Character.aliases.like(f'%"{key}"%'),
                )
            )
            .order_by(CharacterForm.updated_at.desc())
        )
        rows: List[Tuple[Character, CharacterForm]] = list((await session.execute(stmt)).all())
        if not rows:
            return None

        character = rows[0][0]
        return ContenderResolution(
            input_name=raw_name,
            canonical_name=character.name,
            franchise=character.origin_universe,
            options=[
                CharacterVersionOption(
                    version_era=form.version_era,
                    series_label=form.series_label or character.origin_universe,
                    form_name=form.form_name,
                    power_status=form.power_status.value,
                    status_note=form.status_note or "",
                    summary="Already researched -- stored profile will be reused.",
                    # Most recently updated form wins (ordered above).
                    is_recommended=(index == 0),
                )
                for index, (_, form) in enumerate(rows)
            ],
        )

    async def _item_from_db(self, session: AsyncSession, raw_query: str) -> Optional[ItemResolution]:
        """Alias-aware lookup on the item catalog, mirroring _from_db. Returns None if this
        item has never been resolved before."""
        key = alias_key(raw_query)
        if not key:
            return None
        stmt = select(Item).where(
            or_(func.lower(Item.name) == key, Item.aliases.like(f'%"{key}"%'))
        )
        item = (await session.execute(stmt)).scalars().first()
        if item is None:
            return None
        return ItemResolution(
            query=raw_query,
            candidates=[
                ItemOption(
                    name=item.name,
                    origin_universe=item.origin_universe,
                    category=item.category.value,
                    description=item.description or "",
                    power_status=item.power_status.value,
                    status_note=item.status_note or "",
                    is_recommended=True,
                )
            ],
            ambiguous=False,
        )

    async def _from_llm(
        self, needs_llm: List[Tuple[str, int, ContenderSpec, bool, List[str]]]
    ) -> Dict[Tuple[str, int], ContenderResolution]:
        """One structured Gemini call covering every unresolved member/item across both
        teams. Returns {(side, index): ContenderResolution} for the members that were sent."""
        lines = []
        sent: List[Tuple[str, int]] = []
        for side, index, spec, resolve_char, missing_items in needs_llm:
            sent.append((side, index))
            team_label = "Team A" if side == "a" else "Team B"
            parts = [f"- {team_label} member, input_name: '{spec.name}'"]
            if spec.version_hint:
                parts.append(
                    f"-- the user specifically wants this version: '{spec.version_hint}'; "
                    "include that exact version among the options and mark IT as the "
                    "recommended one (if it genuinely doesn't exist in canon, say so in its "
                    "status_note and recommend the closest real version instead)"
                )
            if not resolve_char:
                parts.append("(character already known -- still echo an entry, options may be minimal)")
            if missing_items:
                quoted = ", ".join(f"'{q}'" for q in missing_items)
                parts.append(f"item queries to resolve: {quoted}")
            lines.append(" ".join(parts))

        prompt = (
            "Identify the canonical character, distinct continuity versions, and any listed "
            "equipment for each roster member below, so a power-scaling matchup can be run on "
            "specific versions. Put Team A members in team_a and Team B members in team_b, in "
            "the order listed.\n\n"
            + "\n".join(lines)
            + "\n\n"
            + _CHARACTER_RULES
            + "\n"
            + _ITEM_RULES
        )
        result = await self.gemini_service.generate_structured(
            prompt=prompt,
            response_schema=MatchupResolution,
            system_instruction=_SYSTEM_INSTRUCTION,
        )

        # Map the model's entries back to (side, index): prefer input_name echo, fall back
        # to the order in which members were sent per side.
        guessed: Dict[Tuple[str, int], ContenderResolution] = {}
        for side_key, returned in (("a", result.team_a), ("b", result.team_b)):
            sent_for_side = [(s, i, spec) for (s, i, spec, _, _) in needs_llm if s == side_key]
            unmatched = list(returned)
            for s, i, spec in sent_for_side:
                match = next(
                    (m for m in unmatched if alias_key(m.input_name) == alias_key(spec.name)),
                    None,
                ) or (unmatched[0] if unmatched else None)
                if match is not None:
                    unmatched.remove(match)
                    guessed[(s, i)] = match
        return guessed
