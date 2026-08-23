"""
Parallel Data Scout Agent.
Uses the Parallel Search & Extract API to gather power scaling feats, speed, strength, and hax data.
"""

from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.adapters.parallel_adapter import ParallelAdapter
from src.models.parallel import ParallelSearchRequest, ParallelExtractRequest
from src.db.repository import create_contender_profile, get_or_create_character_form, persist_research_results


class ScoutAgent(BaseAgent):
    def __init__(self, gemini_service, parallel_adapter: ParallelAdapter):
        super().__init__(
            name="Parallel Scout Agent",
            role="Information Retrieval & Feat Extractor",
            gemini_service=gemini_service
        )
        self.parallel_adapter = parallel_adapter

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        contender_a = context.get("contender_a", "Goku")
        contender_b = context.get("contender_b", "Superman")
        matchup_id = context["matchup_id"]

        self.log(f"Initiating Parallel web search for: '{contender_a}' vs '{contender_b}'")

        # Resolve (or create) canonical, reusable character records before researching.
        form_a = await get_or_create_character_form(session, contender_a)
        form_b = await get_or_create_character_form(session, contender_b)
        profile_a = await create_contender_profile(session, matchup_id, form_a.id, side_index=1)
        profile_b = await create_contender_profile(session, matchup_id, form_b.id, side_index=2)

        context["character_form_a_id"] = form_a.id
        context["character_form_b_id"] = form_b.id
        context["contender_profile_a_id"] = profile_a.id
        context["contender_profile_b_id"] = profile_b.id

        sources_cited: List[str] = []
        search_queries: List[str] = ["{a} vs {b} power scaling comparison".format(a=contender_a, b=contender_b)]

        for side, contender_name, form in (("a", contender_a, form_a), ("b", contender_b, form_b)):
            # A character already profiled in a prior matchup (traits_json populated) doesn't
            # need re-scouting -- ProfilerAgent will load its existing data from the DB instead.
            if form.traits_json:
                self.log(f"'{contender_name}' already has a profile; skipping fresh research.")
                context[f"is_known_{side}"] = True
                context[f"research_records_{side}"] = []
                continue

            context[f"is_known_{side}"] = False
            query = f"{contender_name} feats power tier speed hax wiki respect thread"
            search_queries.append(query)

            res = await self.parallel_adapter.search(ParallelSearchRequest(query=query, num_results=5))
            records = await persist_research_results(session, matchup_id, form.id, query, res)
            context[f"research_records_{side}"] = records

            urls = [item.url for item in res.results if item.url]
            sources_cited.extend(urls)
            extracted_docs = []
            if urls:
                extract_res = await self.parallel_adapter.extract(ParallelExtractRequest(urls=urls[:4]))
                extracted_docs = [doc.content for doc in extract_res.extracted]
            context[f"extracted_documentation_{side}"] = extracted_docs

        matchup_query = search_queries[0]
        res_matchup = await self.parallel_adapter.search(ParallelSearchRequest(query=matchup_query, num_results=3))
        await persist_research_results(session, matchup_id, None, matchup_query, res_matchup)

        context["parallel_search_queries"] = search_queries
        context["scouted_matchup_discussions"] = [item.snippet for item in res_matchup.results]
        context["sources_cited"] = sources_cited

        self.log("Scouting phase complete.")
        return context
