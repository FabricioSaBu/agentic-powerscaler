"""
Shared state schema for the LangGraph-orchestrated matchup pipeline.
Mirrors the keys each agent's process(context, session) reads/writes -- agents themselves
are unchanged; this is just what LangGraph uses to type and merge state between nodes.
"""

from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    matchup_id: int
    contender_a: str
    contender_b: str
    battle_environment: str
    include_cinematic_script: bool

    character_form_a_id: int
    character_form_b_id: int
    contender_profile_a_id: int
    contender_profile_b_id: int
    is_known_a: bool
    is_known_b: bool
    research_records_a: List[Any]
    research_records_b: List[Any]
    extracted_documentation_a: List[str]
    extracted_documentation_b: List[str]
    parallel_search_queries: List[str]
    scouted_matchup_discussions: List[str]
    sources_cited: List[str]

    traits_a: Dict[str, Any]
    traits_b: Dict[str, Any]
    feats_a: List[Dict[str, Any]]
    feats_b: List[Dict[str, Any]]

    verdict: Any
    cinematic_battle_script: Optional[List[Any]]
    director_notes: str
