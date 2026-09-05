"""
Matchup preview / roster resolution contract.

Used as a Gemini `response_schema`, so -- like src/models/extraction.py -- every field
carries a default: generate_structured() returns `response_schema()` in offline mode.
"""

from typing import List
from pydantic import BaseModel, Field


class CharacterVersionOption(BaseModel):
    version_era: str = "Canon"
    """Identity key, stored on CharacterForm.version_era ("Shippuden", "Post-Timeskip")."""

    series_label: str = ""
    """Display-only label ("Naruto: Shippuden"). Never used for identity."""

    form_name: str = "Base"
    """Power state within the era ("Six Paths Sage Mode", "Gear 5")."""

    power_status: str = "unknown"
    """One of PowerStatus: complete | ongoing | unknown."""

    status_note: str = ""
    """Why that status -- "Manga concluded in 2014; power level final"."""

    summary: str = ""
    """One line on what this version can do."""

    is_recommended: bool = False


class ItemOption(BaseModel):
    name: str = ""
    origin_universe: str = "Unknown"
    category: str = "other"
    """One of ItemCategory: weapon | artifact | armor | tool | other."""

    description: str = ""
    """What it does -- fed straight into the analyst's prompt (items aren't independently
    researched, so this is the whole of what the analyst learns about it)."""

    power_status: str = "unknown"
    status_note: str = ""
    is_recommended: bool = False


class ItemResolution(BaseModel):
    """Candidates for one item query a member carries."""

    query: str = ""
    """Echoes back the raw text that was resolved, for display and alias-learning."""

    candidates: List[ItemOption] = Field(default_factory=list)
    ambiguous: bool = False
    """True when the input is a genuine toss-up (e.g. "gauntlet" alone) rather than one
    clear best guess among several named variants."""

    clarifying_question: str = ""
    """Shown to the user when ambiguous, e.g. "Which universe's Gauntlet -- MCU or comics?"."""


class ContenderResolution(BaseModel):
    """One roster member, resolved: canonical identity, choosable versions, and any items."""

    input_name: str = ""
    """Echo of the raw text the user typed for this member ("goku"). Used to merge
    LLM-guessed members back with DB-known ones."""

    canonical_name: str = ""
    """Resolved proper name -- "naruto" -> "Naruto Uzumaki"."""

    franchise: str = "Unknown"
    """Stored on Character.origin_universe ("Naruto", "One Piece")."""

    options: List[CharacterVersionOption] = Field(default_factory=list)

    items: List[ItemResolution] = Field(default_factory=list)
    """This member's item resolutions, in the same order as their raw item queries."""


class MatchupResolution(BaseModel):
    """Both rosters resolved in a single Gemini call (1-3 members per side)."""

    team_a: List[ContenderResolution] = Field(default_factory=list)
    team_b: List[ContenderResolution] = Field(default_factory=list)
