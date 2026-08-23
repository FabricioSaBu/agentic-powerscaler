"""
PowerScaler Orchestration Service.
Coordinates Parallel Scout Agent, Profiler Agent, Analyst Agent, and Director Agent via
a LangGraph state graph. Matchup lifecycle (row creation, status, commit/error handling)
is owned here, outside the graph -- it's a persistence concern, not part of the agent flow.
"""

from datetime import datetime, timezone
import uuid
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from src.core.logging import logger
from src.services.gemini_service import GeminiService
from src.services.pipeline_state import PipelineState
from src.adapters.parallel_adapter import ParallelAdapter
from src.agents.scout_agent import ScoutAgent
from src.agents.profiler_agent import ProfilerAgent
from src.agents.analyst_agent import AnalystAgent
from src.agents.director_agent import DirectorAgent
from src.db.models import Matchup as DBMatchup, MatchFormat as DBMatchFormat, MatchupStatus as DBMatchupStatus
from src.models.matchup import (
    PowerScalerMatchupRequest,
    PowerScalerReport
)


class PowerScalerService:
    def __init__(self):
        self.gemini_service = GeminiService()
        self.parallel_adapter = ParallelAdapter()

        self.scout_agent = ScoutAgent(
            gemini_service=self.gemini_service,
            parallel_adapter=self.parallel_adapter
        )
        self.profiler_agent = ProfilerAgent(gemini_service=self.gemini_service)
        self.analyst_agent = AnalystAgent(gemini_service=self.gemini_service)
        self.director_agent = DirectorAgent(gemini_service=self.gemini_service)

        self.graph = self._build_graph()

    def _build_graph(self):
        """Scout -> Profiler -> Analyst -> (Director, if requested) -> END.
        Session/matchup are per-request, so they travel via config["configurable"]
        rather than graph state (which is meant to be the agents' shared data, not
        request-scoped dependencies)."""

        async def scout_node(state: PipelineState, config: RunnableConfig) -> dict:
            return await self.scout_agent.process(state, config["configurable"]["session"])

        async def profiler_node(state: PipelineState, config: RunnableConfig) -> dict:
            return await self.profiler_agent.process(state, config["configurable"]["session"])

        async def analyst_node(state: PipelineState, config: RunnableConfig) -> dict:
            config["configurable"]["matchup"].status = DBMatchupStatus.SCALING
            return await self.analyst_agent.process(state, config["configurable"]["session"])

        async def director_node(state: PipelineState, config: RunnableConfig) -> dict:
            config["configurable"]["matchup"].status = DBMatchupStatus.SCRIPTING
            return await self.director_agent.process(state, config["configurable"]["session"])

        def route_after_analyst(state: PipelineState) -> str:
            return "director" if state.get("include_cinematic_script") else END

        graph = StateGraph(PipelineState)
        graph.add_node("scout", scout_node)
        graph.add_node("profiler", profiler_node)
        graph.add_node("analyst", analyst_node)
        graph.add_node("director", director_node)

        graph.set_entry_point("scout")
        graph.add_edge("scout", "profiler")
        graph.add_edge("profiler", "analyst")
        graph.add_conditional_edges("analyst", route_after_analyst, {"director": "director", END: END})
        graph.add_edge("director", END)

        return graph.compile()

    async def run_matchup_pipeline(self, request: PowerScalerMatchupRequest, session) -> PowerScalerReport:
        """Executes full autonomous power scaling workflow, persisting each stage as it completes."""
        report_id = f"ps-report-{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting PowerScaler pipeline [{report_id}]: {request.contender_a} vs {request.contender_b}")

        matchup = DBMatchup(
            report_id=report_id,
            title=f"{request.contender_a} vs {request.contender_b}",
            match_format=DBMatchFormat.ONE_V_ONE,
            environment=request.battle_environment or "Neutral Multiversal Arena",
            status=DBMatchupStatus.RESEARCHING,
        )
        session.add(matchup)
        await session.flush()

        initial_state: PipelineState = {
            "matchup_id": matchup.id,
            "contender_a": request.contender_a,
            "contender_b": request.contender_b,
            "battle_environment": request.battle_environment or "Neutral Multiversal Arena",
            "include_cinematic_script": request.include_cinematic_script,
        }

        try:
            final_state = await self.graph.ainvoke(
                initial_state,
                config={"configurable": {"session": session, "matchup": matchup}},
            )
            matchup.status = DBMatchupStatus.COMPLETED
            await session.commit()
        except Exception as e:
            # Deliberately not rolling back: whatever research/profiles were already flushed
            # (e.g. Scout succeeded but Analyst failed) are kept rather than discarded.
            matchup.status = DBMatchupStatus.FAILED
            matchup.error_message = str(e)
            await session.commit()
            raise

        report = PowerScalerReport(
            report_id=report_id,
            matchup=f"{request.contender_a} vs {request.contender_b}",
            timestamp=datetime.now(timezone.utc),
            verdict=final_state["verdict"],
            cinematic_battle_script=final_state.get("cinematic_battle_script"),
            parallel_search_queries=final_state.get("parallel_search_queries", []),
            sources_cited=final_state.get("sources_cited", [])
        )

        logger.info(f"PowerScaler pipeline [{report_id}] successfully finished.")
        return report
