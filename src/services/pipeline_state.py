"""
Shared state schema for the LangGraph-orchestrated matchup pipeline.
Sides are rosters: team_a/team_b are lists of member dicts that agents enrich in place
as the state flows Scout -> Profiler -> Analyst -> Director.

Member dict keys:
  from the request:  name, canonical, franchise, version (CharacterVersionOption | None),
                     handicaps (List[str]), item_queries (List[str]),
                     chosen_items (List[ItemOption])
  added by Scout:    form_id, profile_id, is_known, research_records, extracted_docs
  added by Profiler: traits (Dict), feats (List[Dict])
"""

from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    matchup_id: int
    battle_environment: str
    include_cinematic_script: bool

    team_a: List[Dict[str, Any]]
    team_b: List[Dict[str, Any]]

    parallel_search_queries: List[str]
    scouted_matchup_discussions: List[str]
    sources_cited: List[str]

    verdict: Any
    cinematic_battle_script: Optional[List[Any]]
    director_notes: str


def research_label(member: Dict[str, Any]) -> str:
    """The specific thing being researched/profiled: canonical name plus the confirmed
    era/form when the preview step resolved one, else the raw user input.

    Shared by Scout (search query) and Profiler (extraction prompt) -- if only the search
    were qualified, the Profiler would happily extract another era's feats out of whatever
    generic pages the search returned."""
    if not member.get("version"):
        return member["name"]
    name = member.get("canonical") or member["name"]
    form = member["version"]
    qualifiers = [q for q in (form.version_era, form.form_name) if q and q not in ("Canon", "Base")]
    return f"{name} ({', '.join(qualifiers)})" if qualifiers else name
