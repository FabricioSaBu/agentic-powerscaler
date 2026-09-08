"""
Shared Google ADK plumbing for the PowerScaler pipeline.

Every existing agent in this package (Scout, Profiler, Analyst, Director -- see
agents.base.BaseAgent) is already framework-agnostic: process(context: dict, session) ->
dict. LegacyAgentStep is the one adapter needed to run each of them as a genuine node in an
ADK agent tree, driven by a real google-adk Runner, instead of the old LangGraph StateGraph.
"""

from typing import Any

from google.adk.agents import BaseAgent as ADKBaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from pydantic import Field
from typing_extensions import override


class LegacyAgentStep(ADKBaseAgent):
    """One pipeline phase, running under ADK: delegates to an existing agents.base.BaseAgent
    instance and republishes its return value as an ADK session-state delta, so the next
    step in the tree (and the final session snapshot) sees it."""

    legacy_agent: Any = Field(exclude=True)
    db_session: Any = Field(exclude=True)

    @override
    async def _run_async_impl(self, ctx: InvocationContext):
        context = ctx.session.state
        result = await self.legacy_agent.process(context, self.db_session)
        context.update(result)
        yield Event(author=self.name, actions=EventActions(state_delta=dict(context)))
