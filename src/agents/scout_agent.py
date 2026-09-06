"""
Parallel Data Scout Agent.
Uses the Parallel Search & Extract API to gather power scaling feats, speed, strength, and
hax data for every roster member on both sides.
"""

from typing import Any, Dict, List
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.db.models import Feat as DBFeat
from src.adapters.parallel_adapter import ParallelAdapter
from src.models.parallel import ParallelSearchRequest, ParallelExtractRequest
from src.services.pipeline_state import research_label
from src.db.repository import (
    create_contender_item,
    create_contender_profile,
    get_or_create_character_form,
    get_or_create_item,
    persist_research_results,
)


class ScoutAgent(BaseAgent):
    def __init__(self, gemini_service, parallel_adapter: ParallelAdapter):
        super().__init__(
            name="Parallel Scout Agent",
            role="Information Retrieval & Feat Extractor",
            gemini_service=gemini_service
        )
        self.parallel_adapter = parallel_adapter

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        team_a: List[Dict[str, Any]] = context["team_a"]
        team_b: List[Dict[str, Any]] = context["team_b"]
        matchup_id = context["matchup_id"]
        is_team_battle = len(team_a) > 1 or len(team_b) > 1

        label_a = " & ".join(m["name"] for m in team_a)
        label_b = " & ".join(m["name"] for m in team_b)
        self.log(f"Initiating Parallel web search for: '{label_a}' vs '{label_b}'")

        sources_cited: List[str] = []
        search_queries: List[str] = [f"{label_a} vs {label_b} power scaling comparison"]

        for side_index, side_label, team in ((1, "Team A", team_a), (2, "Team B", team_b)):
            for member in team:
                # Resolve (or create) the canonical, reusable character record before
                # researching. Version info (when present) came from the confirmed preview.
                form = await get_or_create_character_form(
                    session,
                    member["name"],
                    version=member.get("version"),
                    canonical_name=member.get("canonical"),
                    franchise=member.get("franchise"),
                )
                profile = await create_contender_profile(
                    session,
                    matchup_id,
                    form.id,
                    side_index=side_index,
                    custom_modifiers=" | ".join(member.get("handicaps") or []) or None,
                    team_name=side_label if is_team_battle else None,
                )
                member["form_id"] = form.id
                member["profile_id"] = profile.id

                # Items are reusable across matchups (like characters) but never
                # independently researched -- their resolved description is all the
                # analyst learns about them.
                item_queries = member.get("item_queries") or []
                for i, item_option in enumerate(member.get("chosen_items") or []):
                    raw_query = item_queries[i] if i < len(item_queries) else item_option.name
                    item = await get_or_create_item(session, item_option, raw_query=raw_query)
                    await create_contender_item(session, profile.id, item.id)

                # A character already profiled in a prior matchup (traits_json populated)
                # doesn't need re-scouting -- ProfilerAgent loads its stored data instead.
                # needs_research overrides the cache: the reviewer rejected this profile,
                # so the stored data is exactly what we're replacing.
                if form.traits_json and not member.get("needs_research"):
                    self.log(f"'{member['name']}' already has a profile; skipping fresh research.")
                    member["is_known"] = True
                    member["research_records"] = []
                    member["extracted_docs"] = []
                    continue

                member["is_known"] = False
                # Search the *resolved* version, not the raw input -- otherwise picking
                # "Naruto (Part I)" over "Shippuden" would research identical sources.
                label = research_label(member)
                hint = (member.get("research_hint") or "").strip()
                if member.get("needs_research"):
                    # Replacing a rejected profile: drop its feats first. traits_json is
                    # overwritten by the profiler, but feats are appended, so without this
                    # the discarded ones would linger alongside the corrections.
                    await session.execute(delete(DBFeat).where(DBFeat.character_form_id == form.id))
                    self.log(f"Re-researching '{label}' after review" + (f": {hint}" if hint else "."))
                    member["needs_research"] = False

                query = f"{label} feats power tier speed hax wiki respect thread"
                if hint:
                    query = f"{label} {hint} feats power tier speed hax"
                search_queries.append(query)

                res = await self.parallel_adapter.search(ParallelSearchRequest(query=query, num_results=5))
                rows = await persist_research_results(session, matchup_id, form.id, query, res)
                # Plain dicts, not ORM rows: graph state is checkpointed to SQLite for the
                # human-review pause, and SQLAlchemy instances are not serializable.
                member["research_records"] = [
                    {"id": r.id, "query_text": r.query_text,
                     "source_url": r.source_url, "snippet": r.snippet}
                    for r in rows
                ]

                urls = [item.url for item in res.results if item.url]
                sources_cited.extend(urls)
                extracted_docs = []
                if urls:
                    # The objective scopes extraction to the confirmed version -- a general
                    # "Vegeta" page otherwise yields whichever era it emphasises most.
                    extract_res = await self.parallel_adapter.extract(ParallelExtractRequest(
                        urls=urls[:4],
                        objective=(
                            f"{label} power level, attack potency, speed, durability, "
                            f"abilities and notable feats"
                            + (f". Focus specifically on: {hint}" if hint else "")
                        ),
                    ))
                    extracted_docs = [doc.content for doc in extract_res.extracted]
                member["extracted_docs"] = extracted_docs

        matchup_query = search_queries[0]
        res_matchup = await self.parallel_adapter.search(ParallelSearchRequest(query=matchup_query, num_results=3))
        await persist_research_results(session, matchup_id, None, matchup_query, res_matchup)

        context["parallel_search_queries"] = search_queries
        context["scouted_matchup_discussions"] = [item.snippet for item in res_matchup.results]
        context["sources_cited"] = sources_cited

        self.log("Scouting phase complete.")
        return context
