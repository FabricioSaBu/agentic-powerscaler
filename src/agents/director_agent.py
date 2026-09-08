"""
Cinematic Battle Director Agent.
Turns a decided matchup into an epic multi-shot screenplay -- for the canonical outcome, or
for a counterfactual ("what if the loser had won?", "what if it ended in a draw?").
"""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.db.models import (
    SCENARIO_A_WINS,
    SCENARIO_B_WINS,
    SCENARIO_TIE,
    CinematicScene as DBCinematicScene,
)
from src.models.matchup import (
    CinematicBattleScene,
    CinematicShot,
    PowerScalingVerdict,
    ScriptOutline,
)

_SYSTEM_INSTRUCTION = (
    "You are a visionary movie director storyboarding an anime/comic blockbuster fight "
    "sequence. You think in camera angles, visual effects, lighting, and pacing, and you "
    "ground every beat in the fighters' actual established powers."
)


def scenario_label(scenario: str, label_a: str, label_b: str) -> str:
    """Human-readable name for a scenario, used in prompts and headings."""
    if scenario == SCENARIO_TIE:
        return "Mutual destruction / draw"
    return f"{label_a if scenario == SCENARIO_A_WINS else label_b} wins"


def _fallback_scenes(
    scenario: str, label_a: str, label_b: str, environment: str
) -> List[CinematicBattleScene]:
    """Used only when Gemini returns nothing usable (offline mode, parse failure) -- the
    result is generic by construction, so it stays clearly a template, not fake specifics."""
    if scenario == SCENARIO_TIE:
        finisher = f"{label_a} and {label_b} land simultaneous finishers; neither rises."
        closing_line = "Neither of us walks away from this."
    else:
        victor = label_a if scenario == SCENARIO_A_WINS else label_b
        finisher = f"{victor} unleashes their ultimate finisher, overcoming the opponent's defenses to seal victory."
        closing_line = "This is the pinnacle of power!"

    return [
        CinematicBattleScene(
            scene_number=1,
            location=environment,
            atmosphere="Cataclysmic energy storms rending dimensional fabric",
            shots=[
                CinematicShot(
                    shot_number=1,
                    camera_angle="Extreme Wide Angle (Orbiting Camera)",
                    action_description=f"{label_a} and {label_b} stand on opposing shattered stellar platforms. Energy aura crackles across the cosmos.",
                    dialogue="Let's see what you're truly capable of!",
                    vfx_notes="Gravitational lensing and chromatic aberration particle effects",
                ),
                CinematicShot(
                    shot_number=2,
                    camera_angle="High-Speed Tracking Shot",
                    action_description="Both warriors clash at faster-than-light speeds. Impact shockwaves shatter nearby moons.",
                    dialogue=None,
                    vfx_notes="Intense aura bloom, sonic boom rings, distortion waves",
                ),
                CinematicShot(
                    shot_number=3,
                    camera_angle="Slow-Motion Hero Close Up",
                    action_description=finisher,
                    dialogue=closing_line,
                    vfx_notes="Full-screen lens flare, blinding white energy discharge, fading to black",
                ),
            ],
        )
    ]


class DirectorAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="Cinematic Battle Director Agent",
            role="Screenplay Writer & Cinematic Choreographer",
            gemini_service=gemini_service
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        """Pipeline node (JSON API path): scripts the outcome the analyst actually decided."""
        verdict: PowerScalingVerdict = context.get("verdict")
        label_a = " & ".join(m["name"] for m in context.get("team_a", [])) or "Contender A"
        label_b = " & ".join(m["name"] for m in context.get("team_b", [])) or "Contender B"
        env = context.get("battle_environment", "Neutral Multiversal Arena")
        scenario = SCENARIO_B_WINS if getattr(verdict, "winning_side", 1) == 2 else SCENARIO_A_WINS

        scenes = await self.generate(
            session=session,
            matchup_id=context["matchup_id"],
            label_a=label_a,
            label_b=label_b,
            environment=env,
            scenario=scenario,
            verdict_summary=verdict.summary_verdict if verdict else "",
            winning_factors=verdict.winning_factors if verdict else [],
            canonical_winner=verdict.winner if verdict else "",
        )

        context["cinematic_battle_script"] = scenes
        context["director_notes"] = scenario_label(scenario, label_a, label_b)
        return context

    async def generate(
        self,
        session: AsyncSession,
        matchup_id: int,
        label_a: str,
        label_b: str,
        environment: str,
        scenario: str,
        verdict_summary: str = "",
        winning_factors: Optional[List[str]] = None,
        canonical_winner: str = "",
    ) -> List[CinematicBattleScene]:
        """Writes and persists one scenario's screenplay. Called both from the pipeline and
        on demand from the results page, so it owns its own persistence."""
        outcome = scenario_label(scenario, label_a, label_b)
        self.log(f"Choreographing '{outcome}' scenario for {label_a} vs {label_b} in {environment}")

        if scenario == SCENARIO_TIE:
            framing = (
                f"Write the scenario where NEITHER side wins: {label_a} and {label_b} fight to a "
                f"mutual knockout or an unbreakable stalemate. Show why neither can close it out."
            )
        elif (scenario == SCENARIO_A_WINS) == (canonical_winner.strip() == label_a.strip()):
            framing = f"Write the fight as the analysis concluded it: {outcome}."
        else:
            upset_winner = label_a if scenario == SCENARIO_A_WINS else label_b
            framing = (
                f"Write the UPSET: the analysis below concluded otherwise, but show how "
                f"{upset_winner} could plausibly steal this win anyway -- exploiting a specific "
                f"weakness, an environmental factor, or a moment of overconfidence. Do not "
                f"contradict either fighter's established powers; find the narrow path."
            )

        factors = ", ".join(winning_factors or []) or "not specified"
        prompt = (
            f"{framing}\n\n"
            f"Environment: {environment}\n"
            f"Key deciding factors from the power-scaling analysis: {factors}\n"
            f"Analysis excerpt (for grounding -- respect these power levels):\n"
            f"{(verdict_summary or '')[:1500]}\n\n"
            "Produce 2-3 scenes, each with 3-4 shots. For every scene give a scene_number, a "
            "specific location, and a one-line atmosphere. For every shot give a shot_number, a "
            "concrete camera_angle (e.g. 'Low-angle tracking shot'), an action_description that "
            "names the actual techniques/abilities being used, optional dialogue (omit it when "
            "silence hits harder), and vfx_notes. Build the arc: opening clash, mid-battle "
            "escalation or transformation, then the decisive finish."
        )

        outline: ScriptOutline = await self.gemini_service.generate_structured(
            prompt=prompt,
            response_schema=ScriptOutline,
            system_instruction=_SYSTEM_INSTRUCTION,
            # Creative composition across 2-3 scenes of several shots each benefits from
            # some deliberation, and needs more room than a plain extraction call.
            thinking_level="medium",
            max_output_tokens=8192,
        )

        scenes = [s for s in outline.scenes if s.shots]
        if not scenes:
            self.log("Gemini returned no usable scenes; falling back to the template script.")
            scenes = _fallback_scenes(scenario, label_a, label_b, environment)

        # Renumber defensively: scene_number is part of the unique key, and the model
        # occasionally repeats or skips numbers.
        for index, scene in enumerate(scenes, start=1):
            scene.scene_number = index
            session.add(DBCinematicScene(
                matchup_id=matchup_id,
                scenario=scenario,
                scene_number=index,
                location=scene.location or environment,
                atmosphere=scene.atmosphere,
                shots=json.dumps([shot.model_dump() for shot in scene.shots]),
            ))
        await session.flush()

        self.log(f"Cinematic script for '{outcome}' generated and persisted ({len(scenes)} scenes).")
        return scenes
