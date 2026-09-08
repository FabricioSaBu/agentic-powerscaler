"""
Agentic Researcher (Google ADK).

The deterministic Scout runs the first pass: one templated query per contender, which is
fast, cheap and usually right. This agent handles the *retry* path instead -- when a human
rejects a profile at the review gate, the model reads what went wrong and composes its own
search rather than replaying a template.

The search tool wraps ScoutAgent's own retrieval path, so a model-chosen query still writes
the research_queries audit rows that the review screen and research trail read. Bypassing
that (e.g. calling an external MCP server directly) would leave the reviewer with nothing
to inspect.

Built on google-adk's LlmAgent + FunctionTool: the model calls the tool directly (no
InjectedState/Command indirection needed, since the tool closure just mutates the `member`
dict this module already holds a reference to), and ADK's own tool-calling loop replaces
LangGraph's manual ToolNode routing.
"""

import uuid
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from sqlalchemy import delete

from src.core.config import settings
from src.core.logging import logger
from src.db.models import Feat as DBFeat
from src.db.repository import persist_research_results
from src.models.parallel import ParallelExtractRequest, ParallelSearchRequest
from src.services.gemini_service import GeminiService
from src.services.pipeline_state import research_label

_SYSTEM = (
    "You are a power-scaling researcher. A human reviewer rejected the data collected for a "
    "character and explained what was wrong. Compose ONE better web search to fix it.\n"
    "Think about why the previous attempt failed: the wrong era or continuity, a later "
    "power-up that this version never had, or sources about a different character entirely. "
    "Put the distinguishing terms in the query, and use `exclude` for the series or forms "
    "that kept polluting the results.\n"
    "Call search_character_feats exactly once, then briefly state what you changed and stop."
)

_MAX_TURNS = 3
"""Bounds the retry conversation if the model doesn't call the tool on its first turn --
mirrors the old graph's implicit loop, but can't run forever."""


def pending_member(state: Dict[str, Any]) -> Optional[tuple]:
    """The next contender awaiting re-research, as (side, index, member)."""
    for side in ("a", "b"):
        for index, member in enumerate(state.get(f"team_{side}") or []):
            if member.get("needs_research"):
                return side, index, member
    return None


class ResearcherAgent:
    """Wraps an ADK LlmAgent bound to one search tool. Deliberately separate from
    GeminiService: that class owns structured output for the other agents and works well, so
    it is left untouched -- only this retry path needs a model that emits tool calls."""

    def __init__(self, parallel_adapter, gemini_service: Optional[GeminiService] = None):
        self.parallel_adapter = parallel_adapter
        # Reuses GeminiService's client construction (Vertex AI vs. AI Studio key) so the
        # ADK model authenticates exactly the same way as the rest of the pipeline.
        self.gemini_service = gemini_service or GeminiService()

    async def _search_and_apply(
        self, member: Dict[str, Any], session, matchup_id: int, query: str, exclude: str = ""
    ) -> str:
        """The tool body: runs Search + Extract for the model's chosen query and writes the
        results directly onto `member` (a dict this closure holds by reference)."""
        form_id = member["form_id"]
        full_query = f"{query} -{exclude}" if exclude else query
        logger.info(f"Agentic re-research for '{member['name']}': {full_query}")

        # Replacing a rejected profile: drop its feats so corrections replace rather than
        # accumulate (traits_json is overwritten by the profiler, but feats are appended).
        await session.execute(delete(DBFeat).where(DBFeat.character_form_id == form_id))

        res = await self.parallel_adapter.search(ParallelSearchRequest(query=full_query, num_results=5))
        rows = await persist_research_results(session, matchup_id, form_id, full_query, res)
        records = [
            {"id": r.id, "query_text": r.query_text, "source_url": r.source_url, "snippet": r.snippet}
            for r in rows
        ]

        urls = [item.url for item in res.results if item.url]
        docs: List[str] = []
        if urls:
            objective = f"{research_label(member)} power level, attack potency, speed, durability, feats"
            if exclude:
                objective += f". Ignore anything from: {exclude}"
            extracted = await self.parallel_adapter.extract(
                ParallelExtractRequest(urls=urls[:4], objective=objective)
            )
            docs = [d.content for d in extracted.extracted]

        member.update({
            "research_records": records, "extracted_docs": docs,
            "is_known": False, "needs_research": False,
        })
        return (
            f"Searched '{full_query}'. Retrieved {len(records)} sources and "
            f"{sum(len(d) for d in docs)} characters of page text for {member['name']}."
        )

    async def research(self, member: Dict[str, Any], session, matchup_id: int) -> None:
        """Runs the retry search for one rejected contender, mutating `member` in place.
        Offline (no Gemini credentials): skips the model and replays the reviewer's hint as
        a plain query, so the app still runs end-to-end without an API key."""
        hint = (member.get("research_hint") or "").strip()

        if not settings.use_vertex_ai and not settings.gemini_api_key:
            label = research_label(member)
            query = f"{label} {hint} feats power tier speed hax" if hint else f"{label} feats power tier speed hax"
            await self._search_and_apply(member, session, matchup_id, query)
            return

        async def search_character_feats(query: str, exclude: str = "") -> str:
            """Search the web for a character's power-scaling feats and extract the pages found.

            Args:
                query: The search to run. Include the exact continuity/era and form, e.g.
                    "Majin Vegeta Buu Saga Super Saiyan 2 power level feats".
                exclude: Series, arcs or forms to steer away from, e.g. "Dragon Ball Super,
                    Ultra Ego". Leave empty if nothing needs excluding.
            """
            return await self._search_and_apply(member, session, matchup_id, query, exclude)

        agent = LlmAgent(
            name="researcher",
            model=Gemini(model=settings.gemini_model, client=self.gemini_service.client),
            instruction=_SYSTEM,
            tools=[FunctionTool(search_character_feats)],
        )
        session_service = InMemorySessionService()
        user_id, session_id = "powerscaler", f"research-{uuid.uuid4().hex[:8]}"
        await session_service.create_session(app_name="powerscaler", user_id=user_id, session_id=session_id)

        traits = member.get("traits") or {}
        prompt = (
            f"Character: {research_label(member)}\n"
            f"Reviewer's note: {hint or '(none given)'}\n"
            f"Rejected data: {traits}\n"
            f"Previous search: {(member.get('research_records') or [{}])[0].get('query_text', 'unknown')}\n"
            f"Compose a better search."
        )
        message = types.Content(role="user", parts=[types.Part(text=prompt)])

        runner = Runner(agent=agent, app_name="powerscaler", session_service=session_service)
        for turn in range(_MAX_TURNS):
            async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
                pass
            if not member.get("needs_research"):
                return
            message = types.Content(
                role="user",
                parts=[types.Part(text="You haven't called search_character_feats yet. Call it now.")],
            )

        if member.get("needs_research"):
            logger.warning(f"Researcher gave up on '{member['name']}' without calling the search tool.")
            await self._search_and_apply(member, session, matchup_id, research_label(member) + " " + hint)
