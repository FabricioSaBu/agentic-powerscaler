"""
PowerScaling Analyst Agent.
Evaluates contender stats, speed, strength, durability, hax, and cosmological scaling to declare a winner.
"""

import json
import re
from typing import Dict, Any, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.db.models import DiffTier as DBDiffTier, Verdict as DBVerdict
from src.models.matchup import (
    PowerScalingVerdict,
    ContenderStats,
    Feat
)

_VERDICT_MARKER = re.compile(r"FINAL_VERDICT:\s*(.+?)\s*\|\s*(.+)")
_FACTORS_MARKER = re.compile(r"WINNING_FACTORS:\s*(.+)")
_VALID_DIFF_TIERS = {"Low Diff", "Mid Diff", "High Diff", "Extreme Diff"}

# Exact seed.py catalog codes (see seed.py's TraitCatalog rows) -- matched exactly, not by
# substring, so an unrelated code like "time_stop_resistance" can't false-positive into
# "durability" just because it contains the word "resistance".
_SPEED_CODES = {"speed"}
_POWER_CODES = {"attack_potency", "striking_strength"}
_DURABILITY_CODES = {"durability"}


def _build_stats(name: str, traits: Dict[str, Any], feats: List[Dict[str, Any]]) -> ContenderStats:
    """Derives real ContenderStats from the ProfilerAgent's persisted traits/feats, instead of
    fabricated placeholder text -- traits is {trait_code: {"value_label", "confidence"}}."""

    def find(codes: set) -> str:
        for code in codes:
            if code in traits:
                return traits[code].get("value_label", "Unrated")
        return "Unrated"

    known_physical_codes = _SPEED_CODES | _POWER_CODES | _DURABILITY_CODES
    hax_abilities = [
        code.replace("_", " ").title()
        for code in traits
        if code not in known_physical_codes
    ]

    return ContenderStats(
        name=name,
        origin_universe="Unknown",
        power_tier=find(_POWER_CODES),
        speed=find(_SPEED_CODES),
        strength=find(_POWER_CODES),
        durability=find(_DURABILITY_CODES),
        hax_abilities=hax_abilities,
        key_feats=[
            Feat(title=f["title"], tier_category="General", description=f["description"])
            for f in feats[:5]
        ]
    )


def _parse_winning_factors(analysis_text: str, winner_name: str) -> List[str]:
    """Extracts the pipe-separated WINNING_FACTORS marker line, falling back to a generic,
    non-fabricated statement if the model didn't follow the format."""
    match = _FACTORS_MARKER.search(analysis_text)
    if match:
        factors = [f.strip() for f in match.group(1).split("|") if f.strip()]
        if factors:
            return factors
    return [f"{winner_name} prevails based on the power scaling analysis above."]


def _parse_verdict(analysis_text: str, contender_a: str, contender_b: str) -> Tuple[str, str]:
    """Extracts (winner, diff_tier) from the analyst's structured marker line, falling back
    to a loose heuristic if the model didn't follow the format. Always returns one of the two
    exact input names, never a paraphrase, so downstream DB/API consumers can trust it."""
    match = _VERDICT_MARKER.search(analysis_text)
    if match:
        winner_raw, diff_raw = match.group(1).strip().lower(), match.group(2).strip()
        for name in (contender_a, contender_b):
            if name.lower() in winner_raw or winner_raw in name.lower():
                diff_tier = diff_raw if diff_raw in _VALID_DIFF_TIERS else "Mid Diff"
                return name, diff_tier

    # Fallback heuristic (pre-existing behavior) for when the model ignores the format.
    winner = contender_a if "wins" in analysis_text.lower() and contender_a.lower() in analysis_text.lower() else contender_b
    return winner, "Mid Diff"


class AnalystAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="PowerScaling Analyst Agent",
            role="Dimensional Tiering & Battle Evaluator",
            gemini_service=gemini_service
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        contender_a_name = context.get("contender_a", "Goku")
        contender_b_name = context.get("contender_b", "Superman")
        # Structured, catalog-grounded data compiled by ProfilerAgent (from fresh extraction
        # or an existing profile) -- not raw scraped snippets.
        traits_a = context.get("traits_a", {})
        traits_b = context.get("traits_b", {})
        feats_a = context.get("feats_a", [])
        feats_b = context.get("feats_b", [])

        self.log(f"Analyzing power scaling matchup: {contender_a_name} vs {contender_b_name}")

        prompt = (
            f"Perform a rigorous VS Battles style power scaling evaluation between {contender_a_name} and {contender_b_name}.\n"
            f"{contender_a_name}'s known traits: {traits_a}\n"
            f"{contender_a_name}'s known feats: {feats_a}\n"
            f"{contender_b_name}'s known traits: {traits_b}\n"
            f"{contender_b_name}'s known feats: {feats_b}\n"
            f"Determine speed scaling, attack potency (AP), durability, hax resistances, and state a definitive winner.\n"
            f"End your response with exactly these two lines, in this exact format (used for automated parsing):\n"
            f"FINAL_VERDICT: <winner's exact name, either \"{contender_a_name}\" or \"{contender_b_name}\"> | <Low Diff, Mid Diff, High Diff, or Extreme Diff>\n"
            f"WINNING_FACTORS: <2-4 short phrases, separated by \" | \", naming the SPECIFIC traits/feats above that decided this matchup>"
        )

        system_instruction = (
            "You are an expert power scaling analyst well-versed in dimensional tiering, speed feats (MFTL, Immeasurable, Inaccessible), "
            "existential hax, conceptual manipulation, and cosmic cosmology."
        )

        analysis_text = await self.gemini_service.generate_text(
            prompt=prompt,
            system_instruction=system_instruction
        )

        # Build structured domain verdict from the real, persisted profile data.
        stats_a = _build_stats(contender_a_name, traits_a, feats_a)
        stats_b = _build_stats(contender_b_name, traits_b, feats_b)

        winner_name, diff_tier = _parse_verdict(analysis_text, contender_a_name, contender_b_name)
        winning_factors = _parse_winning_factors(analysis_text, winner_name)

        verdict = PowerScalingVerdict(
            winner=winner_name,
            diff_tier=diff_tier,
            summary_verdict=analysis_text or f"{winner_name} takes the victory due to superior speed tiering, conceptual resistance, and higher cosmological scale.",
            winning_factors=winning_factors,
            contender_a_stats=stats_a,
            contender_b_stats=stats_b
        )

        winning_side = 1 if winner_name == contender_a_name else 2
        winning_profile_id = context["contender_profile_a_id"] if winning_side == 1 else context["contender_profile_b_id"]
        session.add(DBVerdict(
            matchup_id=context["matchup_id"],
            winning_side=winning_side,
            winning_team_name=winner_name,
            winning_contender_ids=json.dumps([winning_profile_id]),
            diff_tier=DBDiffTier(diff_tier),
            summary_verdict=verdict.summary_verdict,
            winning_factors=json.dumps(winning_factors),
        ))
        await session.flush()

        context["verdict"] = verdict
        self.log(f"Power scaling analysis complete. Declared winner: {winner_name}")
        return context
