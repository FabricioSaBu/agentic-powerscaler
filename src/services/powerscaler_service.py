"""
PowerScaler Orchestration Service.
Coordinates Parallel Scout Agent, Profiler Agent, Analyst Agent, and Director Agent via
a LangGraph state graph. Matchup lifecycle (row creation, status, commit/error handling)
is owned here, outside the graph -- it's a persistence concern, not part of the agent flow.
"""

from datetime import datetime, timezone
import json
import uuid
from sqlalchemy import select
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from src.core.logging import logger
from src.services.gemini_service import GeminiService
from src.services.pipeline_state import PipelineState
from src.adapters.parallel_adapter import ParallelAdapter
from src.agents.scout_agent import ScoutAgent
from src.agents.resolver_agent import ResolverAgent
from src.agents.profiler_agent import ProfilerAgent
from src.agents.analyst_agent import AnalystAgent
from src.agents.director_agent import DirectorAgent, scenario_label
from src.db.models import (
    VALID_SCENARIOS,
    Character as DBCharacter,
    CharacterForm as DBCharacterForm,
    CinematicScene as DBCinematicScene,
    ContenderProfile as DBContenderProfile,
    Matchup as DBMatchup,
    MatchFormat as DBMatchFormat,
    MatchupStatus as DBMatchupStatus,
    Verdict as DBVerdict,
)
from src.models.matchup import (
    CinematicBattleScene,
    CinematicShot,
    ContenderSpec,
    PowerScalerMatchupRequest,
    PowerScalerReport
)
from src.core.exceptions import PowerScalerException
from src.models.preview import MatchupResolution


def _member_state(spec: ContenderSpec) -> dict:
    """A roster member's slice of pipeline state; agents enrich this dict in place."""
    return {
        "name": spec.name,
        "canonical": spec.canonical,
        "franchise": spec.franchise,
        "version": spec.version,
        "handicaps": spec.handicaps,
        "item_queries": spec.item_queries,
        "chosen_items": spec.chosen_items,
    }


def team_label(members: list) -> str:
    """Display name for one side: 'Goku & Vegeta'."""
    return " & ".join(m["name"] if isinstance(m, dict) else m.name for m in members)


class PowerScalerService:
    def __init__(self):
        self.gemini_service = GeminiService()
        self.parallel_adapter = ParallelAdapter()

        self.scout_agent = ScoutAgent(
            gemini_service=self.gemini_service,
            parallel_adapter=self.parallel_adapter
        )
        # Runs ahead of the graph (from /matchup/preview), not as a pipeline node: it exists
        # to let the user confirm versions *before* the expensive research runs.
        self.resolver_agent = ResolverAgent(gemini_service=self.gemini_service)
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

    async def resolve_versions(
        self,
        team_a: list,
        team_b: list,
        session,
    ) -> MatchupResolution:
        """Preview step: which versions of these roster members (and their items) would be
        used, and is each one's power final? Read-only -- nothing is persisted until the
        user confirms."""
        return await self.resolver_agent.resolve(session, team_a, team_b)

    async def generate_scenario_script(self, report_id: str, scenario: str, session):
        """On-demand screenplay for one outcome of an already-decided matchup, returning
        (scenes, from_cache, scenario_label). Cache-first: a scenario already written for
        this matchup is replayed from the DB instead of re-paying for a Gemini call."""
        if scenario not in VALID_SCENARIOS:
            raise PowerScalerException(f"Unknown scenario '{scenario}'.")

        matchup = (
            await session.execute(select(DBMatchup).where(DBMatchup.report_id == report_id))
        ).scalar_one_or_none()
        if matchup is None:
            raise PowerScalerException("That matchup is no longer available -- run it again.")

        stored = (
            await session.execute(
                select(DBCinematicScene)
                .where(
                    DBCinematicScene.matchup_id == matchup.id,
                    DBCinematicScene.scenario == scenario,
                )
                .order_by(DBCinematicScene.scene_number)
            )
        ).scalars().all()

        # Side labels come from the persisted contenders, so a script can be generated long
        # after the request that created the matchup is gone.
        rows = (
            await session.execute(
                select(DBContenderProfile.side_index, DBCharacter.name)
                .join(DBCharacterForm, DBCharacterForm.id == DBContenderProfile.character_form_id)
                .join(DBCharacter, DBCharacter.id == DBCharacterForm.character_id)
                .where(DBContenderProfile.matchup_id == matchup.id)
                .order_by(DBContenderProfile.id)
            )
        ).all()
        label_a = " & ".join(name for side, name in rows if side == 1) or "Contender A"
        label_b = " & ".join(name for side, name in rows if side == 2) or "Contender B"
        label = scenario_label(scenario, label_a, label_b)

        if stored:
            logger.info(f"Serving stored '{scenario}' script for {report_id} (no LLM call).")
            scenes = [
                CinematicBattleScene(
                    scene_number=row.scene_number,
                    location=row.location or matchup.environment,
                    atmosphere=row.atmosphere or "",
                    shots=[CinematicShot(**shot) for shot in json.loads(row.shots)],
                )
                for row in stored
            ]
            return scenes, True, label

        # Explicit query, not matchup.verdict: lazy relationship loads raise MissingGreenlet
        # under asyncio.
        verdict = (
            await session.execute(select(DBVerdict).where(DBVerdict.matchup_id == matchup.id))
        ).scalar_one_or_none()
        scenes = await self.director_agent.generate(
            session=session,
            matchup_id=matchup.id,
            label_a=label_a,
            label_b=label_b,
            environment=matchup.environment,
            scenario=scenario,
            verdict_summary=verdict.summary_verdict if verdict else "",
            winning_factors=json.loads(verdict.winning_factors) if verdict and verdict.winning_factors else [],
            canonical_winner=verdict.winning_team_name if verdict else "",
        )
        await session.commit()
        return scenes, False, label

    async def run_matchup_pipeline(self, request: PowerScalerMatchupRequest, session) -> PowerScalerReport:
        """Executes full autonomous power scaling workflow, persisting each stage as it completes."""
        team_a, team_b = request.rosters()
        if not team_a or not team_b:
            raise ValueError("Both sides need at least one contender.")

        report_id = f"ps-report-{uuid.uuid4().hex[:8]}"
        title = f"{team_label(team_a)} vs {team_label(team_b)}"
        is_team_battle = len(team_a) > 1 or len(team_b) > 1
        logger.info(f"Starting PowerScaler pipeline [{report_id}]: {title}")

        matchup = DBMatchup(
            report_id=report_id,
            title=title,
            match_format=DBMatchFormat.TEAM_BATTLE if is_team_battle else DBMatchFormat.ONE_V_ONE,
            environment=request.battle_environment or "Neutral Multiversal Arena",
            status=DBMatchupStatus.RESEARCHING,
        )
        session.add(matchup)
        await session.flush()

        initial_state: PipelineState = {
            "matchup_id": matchup.id,
            "battle_environment": request.battle_environment or "Neutral Multiversal Arena",
            "include_cinematic_script": request.include_cinematic_script,
            "team_a": [_member_state(m) for m in team_a],
            "team_b": [_member_state(m) for m in team_b],
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
            matchup=title,
            timestamp=datetime.now(timezone.utc),
            verdict=final_state["verdict"],
            cinematic_battle_script=final_state.get("cinematic_battle_script"),
            parallel_search_queries=final_state.get("parallel_search_queries", []),
            sources_cited=final_state.get("sources_cited", [])
        )

        logger.info(f"PowerScaler pipeline [{report_id}] successfully finished.")
        return report
