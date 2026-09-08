"""
PowerScaler Orchestration Service.
Coordinates Parallel Scout Agent, Profiler Agent, Analyst Agent, and Director Agent via a
Google ADK agent tree. Matchup lifecycle (row creation, status, commit/error handling) is
owned here, outside the agents -- it's a persistence concern, not part of the agent flow.

The pipeline runs in two ADK invocations, bridged by our own DB rather than a framework
checkpointer:
  1. "research_and_review" -- Scout+Profiler (first pass) or Researcher-retry+Profiler
     (any later round), for whichever contenders need it right now.
  2. "analysis" -- Analyst, then Director if a cinematic script was requested.
Between rounds of (1), a human-review run pauses: the paused PipelineState is persisted as
JSON on the Matchup row (see Matchup.pending_review_json) and reloaded on the next /resume
request, since an ADK Runner/Session is only alive for the one request that created it.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from google.adk.agents import BaseAgent as ADKBaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from src.agents.adk_common import LegacyAgentStep
from src.agents.analyst_agent import AnalystAgent
from src.agents.director_agent import DirectorAgent, scenario_label
from src.agents.profiler_agent import ProfilerAgent
from src.agents.researcher_agent import ResearcherAgent, pending_member
from src.agents.resolver_agent import ResolverAgent
from src.agents.scout_agent import ScoutAgent
from src.adapters.parallel_adapter import ParallelAdapter
from src.core.exceptions import PowerScalerException
from src.core.logging import logger
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
    PowerScalerReport,
)
from src.models.preview import CharacterVersionOption, ItemOption, MatchupResolution
from src.services.gemini_service import GeminiService
from src.services.pipeline_state import research_label


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


MAX_REVIEW_ROUNDS = 3
"""A rejected contender goes back through research; cap the loop so a user who keeps
rejecting can't cycle forever."""


def _review_card(member: dict) -> dict:
    """One contender's summary for the review screen: what we believe, and what it came
    from. Flagging is presentation only -- a human reads the sources, so there is no
    fragile era-detection heuristic here, just a nudge toward the weak-looking rows."""
    traits = member.get("traits") or {}
    confidences = [
        d.get("confidence") for d in traits.values() if isinstance(d, dict) and d.get("confidence") is not None
    ]
    records = member.get("research_records") or []
    reasons = []
    if confidences and min(confidences) < 0.6:
        reasons.append("low confidence on at least one stat")
    if len(traits) < 2:
        reasons.append("very little was extracted")
    if not records and not member.get("is_known"):
        reasons.append("no sources were retrieved")

    return {
        "name": member["name"],
        "version_label": research_label(member),
        "reused_profile": bool(member.get("is_known")),
        "query": records[0]["query_text"] if records else "",
        "sources": list(dict.fromkeys(r["source_url"] for r in records if r.get("source_url"))),
        "traits": [
            {"code": code, "value_label": str(d.get("value_label", "")), "confidence": d.get("confidence")}
            for code, d in traits.items()
        ],
        "feats": [f.get("title", "") for f in (member.get("feats") or [])],
        "flagged": bool(reasons),
        "flag_reason": "; ".join(reasons),
    }


def team_label(members: list) -> str:
    """Display name for one side: 'Goku & Vegeta'."""
    return " & ".join(m["name"] if isinstance(m, dict) else m.name for m in members)


def _serialize_state(state: Dict[str, Any]) -> str:
    """PipelineState -> JSON, for the pending_review_json column. version/chosen_items are
    pydantic models (not plain-JSON); everything else in a member dict already is."""
    def member_json(member: dict) -> dict:
        out = dict(member)
        if out.get("version") is not None:
            out["version"] = out["version"].model_dump()
        out["chosen_items"] = [item.model_dump() for item in out.get("chosen_items") or []]
        return out

    payload = dict(state)
    payload["team_a"] = [member_json(m) for m in state.get("team_a", [])]
    payload["team_b"] = [member_json(m) for m in state.get("team_b", [])]
    return json.dumps(payload)


def _deserialize_state(raw: str) -> Dict[str, Any]:
    def member_obj(member: dict) -> dict:
        out = dict(member)
        if out.get("version") is not None:
            out["version"] = CharacterVersionOption.model_validate(out["version"])
        out["chosen_items"] = [ItemOption.model_validate(i) for i in out.get("chosen_items") or []]
        return out

    state = json.loads(raw)
    state["team_a"] = [member_obj(m) for m in state.get("team_a", [])]
    state["team_b"] = [member_obj(m) for m in state.get("team_b", [])]
    return state


class _ResearchAndReviewStage(ADKBaseAgent):
    """One review round's research: the deterministic first pass (Scout+Profiler) when
    nothing has been rejected yet, or the agentic retry (Researcher+Profiler) for whichever
    contenders a human just rejected."""

    scout: Any = Field(exclude=True)
    profiler: Any = Field(exclude=True)
    researcher: Any = Field(exclude=True)
    db_session: Any = Field(exclude=True)
    first_pass: bool = True

    @override
    async def _run_async_impl(self, ctx: InvocationContext):
        if self.first_pass:
            async for ev in self.scout.run_async(ctx):
                yield ev
        else:
            context = ctx.session.state
            while (target := pending_member(context)) is not None:
                _side, _index, member = target
                await self.researcher.research(member, self.db_session, context["matchup_id"])

        async for ev in self.profiler.run_async(ctx):
            yield ev


class _AnalysisStage(ADKBaseAgent):
    """Analyst, then Director if a cinematic script was requested. Owns the matchup's status
    transitions for this half of the pipeline."""

    analyst: Any = Field(exclude=True)
    director: Any = Field(exclude=True)
    matchup: Any = Field(exclude=True)

    @override
    async def _run_async_impl(self, ctx: InvocationContext):
        self.matchup.status = DBMatchupStatus.SCALING
        async for ev in self.analyst.run_async(ctx):
            yield ev

        if ctx.session.state.get("include_cinematic_script"):
            self.matchup.status = DBMatchupStatus.SCRIPTING
            async for ev in self.director.run_async(ctx):
                yield ev


class PowerScalerService:
    def __init__(self):
        self.gemini_service = GeminiService()
        self.parallel_adapter = ParallelAdapter()

        self.scout_agent = ScoutAgent(
            gemini_service=self.gemini_service,
            parallel_adapter=self.parallel_adapter
        )
        # Runs ahead of the ADK pipeline (from /matchup/preview), not as a pipeline stage: it
        # exists to let the user confirm versions *before* the expensive research runs.
        self.resolver_agent = ResolverAgent(gemini_service=self.gemini_service)
        self.profiler_agent = ProfilerAgent(gemini_service=self.gemini_service)
        self.analyst_agent = AnalystAgent(gemini_service=self.gemini_service)
        self.director_agent = DirectorAgent(gemini_service=self.gemini_service)
        # Handles the retry path only: the model composes its own query instead of
        # replaying Scout's template.
        self.researcher_agent = ResearcherAgent(
            parallel_adapter=self.parallel_adapter, gemini_service=self.gemini_service
        )

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

    async def _run_adk(self, root_agent: ADKBaseAgent, state: Dict[str, Any], thread_id: str) -> Dict[str, Any]:
        """Runs one ADK invocation to completion and returns the final session state."""
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name="powerscaler", user_id="powerscaler", session_id=thread_id, state=state
        )
        runner = Runner(agent=root_agent, app_name="powerscaler", session_service=session_service)
        message = types.Content(role="user", parts=[types.Part(text="run")])
        async for _event in runner.run_async(user_id="powerscaler", session_id=thread_id, new_message=message):
            pass
        final = await session_service.get_session(app_name="powerscaler", user_id="powerscaler", session_id=thread_id)
        return final.state

    def _research_review_stage(self, session: AsyncSession, first_pass: bool) -> _ResearchAndReviewStage:
        return _ResearchAndReviewStage(
            name="research_and_review",
            scout=LegacyAgentStep(name="scout", legacy_agent=self.scout_agent, db_session=session),
            profiler=LegacyAgentStep(name="profiler", legacy_agent=self.profiler_agent, db_session=session),
            researcher=self.researcher_agent,
            db_session=session,
            first_pass=first_pass,
        )

    def _analysis_stage(self, session: AsyncSession, matchup: DBMatchup) -> _AnalysisStage:
        return _AnalysisStage(
            name="analysis",
            analyst=LegacyAgentStep(name="analyst", legacy_agent=self.analyst_agent, db_session=session),
            director=LegacyAgentStep(name="director", legacy_agent=self.director_agent, db_session=session),
            matchup=matchup,
        )

    def _review_payload(self, state: Dict[str, Any], round_no: int) -> Dict[str, Any]:
        return {
            "round": round_no,
            "max_rounds": MAX_REVIEW_ROUNDS,
            "team_a": [_review_card(m) for m in state["team_a"]],
            "team_b": [_review_card(m) for m in state["team_b"]],
        }

    def _build_report(self, matchup: DBMatchup, state: Dict[str, Any]) -> PowerScalerReport:
        return PowerScalerReport(
            report_id=matchup.report_id,
            matchup=matchup.title,
            timestamp=datetime.now(timezone.utc),
            verdict=state["verdict"],
            cinematic_battle_script=state.get("cinematic_battle_script"),
            parallel_search_queries=state.get("parallel_search_queries", []),
            sources_cited=state.get("sources_cited", []),
        )

    async def _finish_with_analysis(
        self, state: Dict[str, Any], session: AsyncSession, matchup: DBMatchup, thread_id: str
    ) -> PowerScalerReport:
        try:
            state = await self._run_adk(self._analysis_stage(session, matchup), state, f"{thread_id}-analysis")
            matchup.status = DBMatchupStatus.COMPLETED
            matchup.pending_review_json = None
            await session.commit()
        except Exception as e:
            matchup.status = DBMatchupStatus.FAILED
            matchup.error_message = str(e)
            await session.commit()
            raise
        return self._build_report(matchup, state)

    async def run_matchup_pipeline(
        self, request: PowerScalerMatchupRequest, session, human_review: bool = False
    ):
        """Executes the full power scaling workflow, persisting each stage as it completes.

        With human_review=True the run pauses at the review gate and returns
        (None, review_payload, thread_id); otherwise it returns (report, None, thread_id)."""
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

        state: Dict[str, Any] = {
            "matchup_id": matchup.id,
            "battle_environment": request.battle_environment or "Neutral Multiversal Arena",
            "include_cinematic_script": request.include_cinematic_script,
            "team_a": [_member_state(m) for m in team_a],
            "team_b": [_member_state(m) for m in team_b],
        }

        try:
            state = await self._run_adk(self._research_review_stage(session, first_pass=True), state, report_id)
            await session.commit()
        except Exception as e:
            matchup.status = DBMatchupStatus.FAILED
            matchup.error_message = str(e)
            await session.commit()
            raise

        if human_review:
            matchup.pending_review_json = _serialize_state(state)
            await session.commit()
            return None, self._review_payload(state, round_no=0), report_id

        report = await self._finish_with_analysis(state, session, matchup, report_id)
        logger.info(f"PowerScaler pipeline [{report_id}] successfully finished.")
        return report, None, report_id

    async def resume_review(self, thread_id: str, decision: dict, session):
        """Continues a run paused at the review gate. The paused PipelineState lives on the
        Matchup row (pending_review_json); the request-scoped session is supplied fresh."""
        matchup = (
            await session.execute(select(DBMatchup).where(DBMatchup.report_id == thread_id))
        ).scalar_one_or_none()
        if matchup is None or not matchup.pending_review_json:
            raise PowerScalerException("That run has expired -- start the matchup again.")

        state = _deserialize_state(matchup.pending_review_json)
        round_no = state.get("review_round", 0)

        for side, team in (("a", state["team_a"]), ("b", state["team_b"])):
            for index, member in enumerate(team):
                verdicts = (decision or {}).get(side) or []
                choice = verdicts[index] if index < len(verdicts) else {}
                if choice.get("approved", True):
                    member["needs_research"] = False
                else:
                    member["needs_research"] = True
                    member["research_hint"] = (choice.get("hint") or "").strip()

        if pending_member(state) is None:
            report = await self._finish_with_analysis(state, session, matchup, thread_id)
            return report, None, thread_id

        try:
            state = await self._run_adk(
                self._research_review_stage(session, first_pass=False), state, f"{thread_id}-r{round_no}"
            )
            await session.commit()
        except Exception as e:
            matchup.status = DBMatchupStatus.FAILED
            matchup.error_message = str(e)
            await session.commit()
            raise

        round_no += 1
        if pending_member(state) is None or round_no >= MAX_REVIEW_ROUNDS:
            report = await self._finish_with_analysis(state, session, matchup, thread_id)
            return report, None, thread_id

        state["review_round"] = round_no
        matchup.pending_review_json = _serialize_state(state)
        await session.commit()
        return None, self._review_payload(state, round_no=round_no), thread_id
