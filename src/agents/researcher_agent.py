"""
Agentic Researcher.

The deterministic Scout runs the first pass: one templated query per contender, which is
fast, cheap and usually right. This agent handles the *retry* path instead -- when a human
rejects a profile at the review gate, the model reads what went wrong and composes its own
search rather than replaying a template.

The search tool wraps ScoutAgent's own retrieval path, so a model-chosen query still writes
the research_queries audit rows that the review screen and research trail read. Bypassing
that (e.g. calling an external MCP server directly) would leave the reviewer with nothing
to inspect.
"""

from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import delete

from src.core.config import settings
from src.core.logging import logger
from src.db.models import Feat as DBFeat
from src.db.repository import persist_research_results
from src.models.parallel import ParallelExtractRequest, ParallelSearchRequest
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


def pending_member(state: Dict[str, Any]) -> Optional[tuple]:
    """The next contender awaiting re-research, as (side, index, member)."""
    for side in ("a", "b"):
        for index, member in enumerate(state.get(f"team_{side}") or []):
            if member.get("needs_research"):
                return side, index, member
    return None


def build_search_tool(parallel_adapter):
    """The tool is built around the live adapter so the model's query still flows through
    our persistence. `config` and `state` are injected -- the model only ever sets `query`
    and `exclude`."""

    @tool
    async def search_character_feats(
        query: str,
        config: RunnableConfig,
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
        exclude: str = "",
    ) -> Command:
        """Search the web for a character's power-scaling feats and extract the pages found.

        Args:
            query: The search to run. Include the exact continuity/era and form, e.g.
                "Majin Vegeta Buu Saga Super Saiyan 2 power level feats".
            exclude: Series, arcs or forms to steer away from, e.g. "Dragon Ball Super,
                Ultra Ego". Leave empty if nothing needs excluding.
        """
        session = config["configurable"]["session"]
        matchup_id = state["matchup_id"]
        target = pending_member(state)
        if target is None:
            return Command(update={"messages": [ToolMessage(
                content="No contender is awaiting re-research.", tool_call_id=tool_call_id)]})

        side, index, member = target
        form_id = member["form_id"]
        full_query = f"{query} -{exclude}" if exclude else query
        logger.info(f"Agentic re-research for '{member['name']}': {full_query}")

        # Replacing a rejected profile: drop its feats so corrections replace rather than
        # accumulate (traits_json is overwritten by the profiler, but feats are appended).
        await session.execute(delete(DBFeat).where(DBFeat.character_form_id == form_id))

        res = await parallel_adapter.search(ParallelSearchRequest(query=full_query, num_results=5))
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
            extracted = await parallel_adapter.extract(
                ParallelExtractRequest(urls=urls[:4], objective=objective)
            )
            docs = [d.content for d in extracted.extracted]

        # Write the results onto the member and clear its pending flag, so the graph can
        # route on to the profiler.
        team = list(state[f"team_{side}"])
        updated = dict(team[index])
        updated.update({
            "research_records": records, "extracted_docs": docs,
            "is_known": False, "needs_research": False,
        })
        team[index] = updated

        return Command(update={
            f"team_{side}": team,
            "messages": [ToolMessage(
                content=(f"Searched '{full_query}'. Retrieved {len(records)} sources and "
                         f"{sum(len(d) for d in docs)} characters of page text for "
                         f"{member['name']}."),
                tool_call_id=tool_call_id)],
        })

    return search_character_feats


class ResearcherAgent:
    """Wraps a tool-calling chat model. Deliberately separate from GeminiService: that class
    owns structured output for the other agents and works well, so it is left untouched --
    only this retry path needs a model that emits tool calls."""

    def __init__(self, parallel_adapter):
        self.search_tool = build_search_tool(parallel_adapter)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key,
            ).bind_tools([self.search_tool])
        return self._model

    async def think(self, state: Dict[str, Any]) -> dict:
        """One turn: either issue a tool call or wrap up. Returns a messages update."""
        messages = list(state.get("messages") or [])
        if not messages:
            target = pending_member(state)
            if target is None:
                return {}
            _side, _index, member = target
            traits = member.get("traits") or {}
            messages = [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content=(
                    f"Character: {research_label(member)}\n"
                    f"Reviewer's note: {member.get('research_hint') or '(none given)'}\n"
                    f"Rejected data: {traits}\n"
                    f"Previous search: {(member.get('research_records') or [{}])[0].get('query_text', 'unknown')}\n"
                    f"Compose a better search."
                )),
            ]
        response = await self.model.ainvoke(messages)
        return {"messages": messages[len(state.get("messages") or []):] + [response]}
