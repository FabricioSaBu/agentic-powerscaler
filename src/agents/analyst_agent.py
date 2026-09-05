"""
PowerScaling Analyst Agent.
Evaluates every roster member's stats, speed, strength, durability, hax, and cosmological
scaling to declare a winning side -- an exact contender in 1v1, a team in team battles.
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.db.models import DiffTier as DBDiffTier, Verdict as DBVerdict
from sqlalchemy import select
from src.db.models import ResearchQuery as DBResearchQuery
from src.models.matchup import (
    PowerScalingVerdict,
    ContenderStats,
    Feat,
    ResearchTrail,
    TraitEvidence,
)
from src.services.pipeline_state import research_label

_VERDICT_MARKER = re.compile(r"FINAL_VERDICT:\s*(.+?)\s*\|\s*(.+)")
_FACTORS_MARKER = re.compile(r"WINNING_FACTORS:\s*(.+)")
_PROBABILITY_MARKER = re.compile(
    r"WIN_PROBABILITY:\s*A\s*=\s*(\d+)\s*%?\s*\|\s*B\s*=\s*(\d+)\s*%?\s*\|\s*TIE\s*=\s*(\d+)", re.IGNORECASE
)
_MARKER_LINES = re.compile(r"^(FINAL_VERDICT|WINNING_FACTORS|WIN_PROBABILITY):.*$\n?", re.MULTILINE)
_VALID_DIFF_TIERS = {"Low Diff", "Mid Diff", "High Diff", "Extreme Diff"}

# Fallback winner probability when the model skips/bungles the WIN_PROBABILITY marker:
# the diff tier already encodes how decisive the matchup is.
_DIFF_TIER_PROBABILITY = {"Low Diff": 90, "Mid Diff": 75, "High Diff": 62, "Extreme Diff": 53}

# Exact seed.py catalog codes (see seed.py's TraitCatalog rows) -- matched exactly, not by
# substring, so an unrelated code like "time_stop_resistance" can't false-positive into
# "durability" just because it contains the word "resistance".
_SPEED_CODES = {"speed"}
_POWER_CODES = {"attack_potency", "striking_strength"}
_DURABILITY_CODES = {"durability"}


def _team_label(team: List[Dict[str, Any]]) -> str:
    return " & ".join(m["name"] for m in team)


def _build_stats(member: Dict[str, Any], trail: Optional[ResearchTrail] = None) -> ContenderStats:
    """Derives real ContenderStats from the ProfilerAgent's persisted traits/feats, instead of
    fabricated placeholder text -- traits is {trait_code: {"value_label", "confidence"}}."""
    traits: Dict[str, Any] = member.get("traits", {})
    feats: List[Dict[str, Any]] = member.get("feats", [])

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
        name=member["name"],
        origin_universe=member.get("franchise") or "Unknown",
        power_tier=find(_POWER_CODES),
        speed=find(_SPEED_CODES),
        strength=find(_POWER_CODES),
        durability=find(_DURABILITY_CODES),
        hax_abilities=hax_abilities,
        key_feats=[
            Feat(title=f["title"], tier_category="General", description=f["description"])
            for f in feats[:5]
        ],
        trail=trail,
    )


async def _build_trail(session: AsyncSession, member: Dict[str, Any]) -> ResearchTrail:
    """Reconstructs how this contender's numbers were obtained. For a reused profile the
    live run issued no query, so the original run's stored queries/sources are shown."""
    records = member.get("research_records") or []
    query = ""
    sources = []
    if records:
        query = records[0].query_text
        sources = [r.source_url for r in records if r.source_url]
    elif member.get("form_id"):
        stored = (
            await session.execute(
                select(DBResearchQuery)
                .where(DBResearchQuery.character_form_id == member["form_id"])
                .order_by(DBResearchQuery.id.desc())
                .limit(8)
            )
        ).scalars().all()
        if stored:
            query = stored[0].query_text
            sources = [r.source_url for r in stored if r.source_url]

    traits = member.get("traits", {}) or {}
    return ResearchTrail(
        version_label=research_label(member),
        query=query,
        sources=list(dict.fromkeys(sources)),  # de-dupe, keep order
        reused_profile=bool(member.get("is_known")),
        traits=[
            TraitEvidence(
                code=code,
                value_label=str(data.get("value_label", "")),
                confidence=data.get("confidence"),
            )
            for code, data in traits.items()
        ],
    )


def _member_context(team_a: List[Dict[str, Any]], team_b: List[Dict[str, Any]]) -> str:
    """Version, handicap, and equipment context for every member of both sides -- none of
    this lives in the persisted trait profiles, so without these lines the analyst would
    never see it."""
    version_lines, handicap_lines, item_lines = [], [], []
    for member in team_a + team_b:
        name = member["name"]

        version = member.get("version")
        if version:
            label = version.series_label or version.version_era
            status = (version.power_status or "unknown").lower()
            if status == "ongoing":
                note = "power development is ONGOING -- the series is still publishing, so these feats may already be outdated"
            elif status == "complete":
                note = "power development is COMPLETE -- this version's ceiling is final"
            else:
                note = "power development status is UNKNOWN"
            version_lines.append(f"- {name} is the {label} version ({version.form_name}); {note}.")

        for handicap in member.get("handicaps") or []:
            if handicap.strip():
                handicap_lines.append(f"- {name}: {handicap.strip()}")

        for item in member.get("chosen_items") or []:
            detail = f": {item.description}" if item.description else ""
            item_lines.append(f"- {name} wields {item.name}{detail}")

    blocks = []
    if version_lines:
        blocks.append(
            "Version context (factor this into your reasoning, and say so explicitly if one "
            "side is still developing while the other is finished):\n" + "\n".join(version_lines)
        )
    if handicap_lines:
        blocks.append(
            "Handicaps in effect for THIS matchup only (apply them; do not treat them as "
            "permanent traits of the character):\n" + "\n".join(handicap_lines)
        )
    if item_lines:
        blocks.append("Equipment in play:\n" + "\n".join(item_lines))
    return ("\n".join(blocks) + "\n") if blocks else ""


def _roster_block(side_label: str, team: List[Dict[str, Any]]) -> str:
    lines = [f"{side_label} ({_team_label(team)}):"]
    for member in team:
        lines.append(f"* {member['name']}'s known traits: {member.get('traits', {})}")
        lines.append(f"* {member['name']}'s known feats: {member.get('feats', [])}")
    return "\n".join(lines)


def _parse_probabilities(analysis_text: str, winning_side: int, diff_tier: str) -> Tuple[int, int, int]:
    """(win_a, win_b, tie) in whole percent, summing to 100. Uses the model's own
    WIN_PROBABILITY marker when it's present, normalizes, and is consistent with the
    declared winner; otherwise derives a distribution from the winner + diff tier so the
    bar never contradicts the banner."""
    match = _PROBABILITY_MARKER.search(analysis_text)
    if match:
        a, b, tie = (int(g) for g in match.groups())
        total = a + b + tie
        if total > 0:
            a = round(a * 100 / total)
            b = round(b * 100 / total)
            tie = 100 - a - b
            favors_winner = (a >= b) if winning_side == 1 else (b >= a)
            if tie >= 0 and favors_winner:
                return a, b, tie

    win = _DIFF_TIER_PROBABILITY.get(diff_tier, 75)
    tie = max(2, (100 - win) // 5)
    lose = 100 - win - tie
    return (win, lose, tie) if winning_side == 1 else (lose, win, tie)


def _parse_winning_factors(analysis_text: str, winner_name: str) -> List[str]:
    """Extracts the pipe-separated WINNING_FACTORS marker line, falling back to a generic,
    non-fabricated statement if the model didn't follow the format."""
    match = _FACTORS_MARKER.search(analysis_text)
    if match:
        factors = [f.strip() for f in match.group(1).split("|") if f.strip()]
        if factors:
            return factors
    return [f"{winner_name} prevails based on the power scaling analysis above."]


def _parse_verdict_1v1(analysis_text: str, contender_a: str, contender_b: str) -> Tuple[str, str]:
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


def _parse_verdict_team(
    analysis_text: str, team_a: List[Dict[str, Any]], team_b: List[Dict[str, Any]]
) -> Tuple[int, str]:
    """Team battles: (winning_side, diff_tier). The marker names 'Team A' or 'Team B';
    any member name mentioned in the marker works as a fallback."""
    match = _VERDICT_MARKER.search(analysis_text)
    if match:
        winner_raw, diff_raw = match.group(1).strip().lower(), match.group(2).strip()
        diff_tier = diff_raw if diff_raw in _VALID_DIFF_TIERS else "Mid Diff"
        if "team a" in winner_raw:
            return 1, diff_tier
        if "team b" in winner_raw:
            return 2, diff_tier
        for side, team in ((1, team_a), (2, team_b)):
            if any(m["name"].lower() in winner_raw for m in team):
                return side, diff_tier

    # Fallback: whichever side's members are mentioned more in the closing text.
    tail = analysis_text[-800:].lower()
    mentions_a = sum(tail.count(m["name"].lower()) for m in team_a)
    mentions_b = sum(tail.count(m["name"].lower()) for m in team_b)
    return (1 if mentions_a >= mentions_b else 2), "Mid Diff"


class AnalystAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="PowerScaling Analyst Agent",
            role="Dimensional Tiering & Battle Evaluator",
            gemini_service=gemini_service
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        team_a: List[Dict[str, Any]] = context["team_a"]
        team_b: List[Dict[str, Any]] = context["team_b"]
        is_team_battle = len(team_a) > 1 or len(team_b) > 1
        label_a, label_b = _team_label(team_a), _team_label(team_b)

        self.log(f"Analyzing power scaling matchup: {label_a} vs {label_b}")

        if is_team_battle:
            verdict_format = (
                f"FINAL_VERDICT: <\"Team A\" or \"Team B\"> | <Low Diff, Mid Diff, High Diff, or Extreme Diff>"
            )
            framing = (
                f"Perform a rigorous VS Battles style power scaling evaluation of a TEAM BATTLE: "
                f"Team A ({label_a}) versus Team B ({label_b}). Consider teamwork, ability synergy, "
                f"and whether one member can neutralize multiple opponents.\n"
            )
        else:
            verdict_format = (
                f"FINAL_VERDICT: <winner's exact name, either \"{team_a[0]['name']}\" or "
                f"\"{team_b[0]['name']}\"> | <Low Diff, Mid Diff, High Diff, or Extreme Diff>"
            )
            framing = (
                f"Perform a rigorous VS Battles style power scaling evaluation between "
                f"{team_a[0]['name']} and {team_b[0]['name']}.\n"
            )

        prompt = (
            framing
            + _member_context(team_a, team_b)
            + _roster_block("Team A", team_a) + "\n"
            + _roster_block("Team B", team_b) + "\n"
            + "Determine speed scaling, attack potency (AP), durability, hax resistances, and state a definitive winner.\n"
            + "End your response with exactly these three lines, in this exact format (used for automated parsing):\n"
            + verdict_format + "\n"
            + "WINNING_FACTORS: <2-4 short phrases, separated by \" | \", naming the SPECIFIC traits/feats above that decided this matchup>\n"
            + f"WIN_PROBABILITY: A=<chance {label_a} wins, whole %> | B=<chance {label_b} wins, whole %> | "
            + "TIE=<chance of a tie or inconclusive outcome, whole %>  (three integers summing to 100, "
            + "consistent with your FINAL_VERDICT and its diff tier)"
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
        team_a_stats = [_build_stats(m, await _build_trail(session, m)) for m in team_a]
        team_b_stats = [_build_stats(m, await _build_trail(session, m)) for m in team_b]

        if is_team_battle:
            winning_side, diff_tier = _parse_verdict_team(analysis_text, team_a, team_b)
            winner_name = label_a if winning_side == 1 else label_b
        else:
            winner_name, diff_tier = _parse_verdict_1v1(
                analysis_text, team_a[0]["name"], team_b[0]["name"]
            )
            winning_side = 1 if winner_name == team_a[0]["name"] else 2

        winning_factors = _parse_winning_factors(analysis_text, winner_name)
        win_a, win_b, tie = _parse_probabilities(analysis_text, winning_side, diff_tier)
        # Parse markers first (above), then strip them so the displayed text reads cleanly.
        display_text = _MARKER_LINES.sub("", analysis_text).strip()

        verdict = PowerScalingVerdict(
            winner=winner_name,
            winning_side=winning_side,
            diff_tier=diff_tier,
            summary_verdict=display_text or f"{winner_name} takes the victory due to superior speed tiering, conceptual resistance, and higher cosmological scale.",
            winning_factors=winning_factors,
            win_probability_a=win_a,
            win_probability_b=win_b,
            tie_probability=tie,
            team_a_stats=team_a_stats,
            team_b_stats=team_b_stats,
        )

        winning_team = team_a if winning_side == 1 else team_b
        session.add(DBVerdict(
            matchup_id=context["matchup_id"],
            winning_side=winning_side,
            winning_team_name=winner_name,
            winning_contender_ids=json.dumps([m["profile_id"] for m in winning_team]),
            diff_tier=DBDiffTier(diff_tier),
            summary_verdict=verdict.summary_verdict,
            winning_factors=json.dumps(winning_factors),
            win_probability_a=win_a,
            win_probability_b=win_b,
            tie_probability=tie,
        ))
        await session.flush()

        context["verdict"] = verdict
        self.log(f"Power scaling analysis complete. Declared winner: {winner_name}")
        return context
