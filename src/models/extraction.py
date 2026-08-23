"""
Structured-output schema for the character extraction (Profiler) step.
Passed directly to Gemini as response_schema, so the shape here IS the API contract.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class TraitAssessment(BaseModel):
    trait_code: str = Field(description="snake_case identifier; reuse a known catalog code when applicable, otherwise invent a new one")
    display_name: str
    category: str = Field(description='One of: "physical", "energy_source", "hax", "resistance", "meta"')
    value_type: str = Field(description='One of: "tier", "numeric", "boolean", "text"')
    value_label: str = Field(description="Human-readable value, e.g. \"Large Star level\", \"Multiversal\", \"True\"")
    confidence: float = Field(description="0-1 confidence in this assessment")
    source_index: Optional[int] = Field(default=None, description="Index into the numbered source list that best supports this")


class FeatAssessment(BaseModel):
    title: str
    description: str
    trait_code: Optional[str] = Field(default=None, description="Which trait this feat is evidence for, if any")
    confidence: float
    source_index: Optional[int] = Field(default=None, description="Index into the numbered source list this feat came from")


class CharacterProfile(BaseModel):
    traits: List[TraitAssessment] = Field(default_factory=list)
    feats: List[FeatAssessment] = Field(default_factory=list)
