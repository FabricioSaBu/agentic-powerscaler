"""
Cinematic Battle Director Agent.
Converts power scaling verdict and feat calculations into an epic multi-shot screenplay and storyboard.
"""

import json
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.db.models import CinematicScene as DBCinematicScene
from src.models.matchup import (
    CinematicBattleScene,
    CinematicShot,
    PowerScalingVerdict
)


class DirectorAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="Cinematic Battle Director Agent",
            role="Screenplay Writer & Cinematic Choreographer",
            gemini_service=gemini_service
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        verdict: PowerScalingVerdict = context.get("verdict")
        contender_a = context.get("contender_a", "Goku")
        contender_b = context.get("contender_b", "Superman")
        env = context.get("battle_environment", "Neutral Multiversal Arena")

        self.log(f"Choreographing cinematic battle scene for {contender_a} vs {contender_b} in {env}")

        prompt = (
            f"Write a 3-shot dramatic cinematic fight scene based on this verdict:\n"
            f"Winner: {verdict.winner}\n"
            f"Key Winning Factors: {verdict.winning_factors}\n"
            f"Environment: {env}\n"
            f"Show the initial clash, the mid-battle transformation/hax activation, and the final finishing climax."
        )

        system_instruction = (
            "You are a visionary movie director directing an anime/comic blockbuster fight sequence. "
            "Focus on camera angles, visual effects (VFX), lighting, and pacing."
        )

        script_text = await self.gemini_service.generate_text(
            prompt=prompt,
            system_instruction=system_instruction
        )

        # Build structured cinematic scene model
        battle_scenes = [
            CinematicBattleScene(
                scene_number=1,
                location=env,
                atmosphere="Cataclysmic energy storms rending dimensional fabric",
                shots=[
                    CinematicShot(
                        shot_number=1,
                        camera_angle="Extreme Wide Angle (Orbiting Camera)",
                        action_description=f"{contender_a} and {contender_b} stand on opposing shattered stellar platforms. Energy aura crackles across the cosmos.",
                        dialogue="Let's see what you're truly capable of!",
                        vfx_notes="Gravitational lensing and chromatic aberration particle effects"
                    ),
                    CinematicShot(
                        shot_number=2,
                        camera_angle="High-Speed Tracking Shot",
                        action_description=f"Both warriors clash at faster-than-light speeds. Impact shockwaves shatter nearby moons.",
                        dialogue=None,
                        vfx_notes="Intense aura bloom, sonic boom rings, distortion waves"
                    ),
                    CinematicShot(
                        shot_number=3,
                        camera_angle="Slow-Motion Hero Close Up",
                        action_description=f"{verdict.winner} unleashes their ultimate finisher, overcoming the opponent's defenses to seal victory.",
                        dialogue=f"This is the pinnacle of power!",
                        vfx_notes="Full-screen lens flare, blinding white energy discharge, fading to black"
                    )
                ]
            )
        ]

        for scene in battle_scenes:
            session.add(DBCinematicScene(
                matchup_id=context["matchup_id"],
                scene_number=scene.scene_number,
                location=scene.location,
                atmosphere=scene.atmosphere,
                shots=json.dumps([shot.model_dump() for shot in scene.shots]),
            ))
        await session.flush()

        context["cinematic_battle_script"] = battle_scenes
        context["director_notes"] = script_text
        self.log("Cinematic battle script generation complete and persisted.")
        return context
