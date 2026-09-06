"""
Character Profiler Agent.
Turns one character's raw scouted research into structured, catalog-grounded traits and
feats -- or, if the character is already known, loads their existing profile from the DB
instead of re-extracting. Novel power sources/abilities not yet in trait_catalog are
auto-registered rather than dropped or forced into an existing (wrong) category.
"""

import json
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.db.models import CharacterForm, Feat as DBFeat, TraitCatalog
from src.db.repository import get_or_create_trait_catalog, normalize_trait_code
from src.models.extraction import CharacterProfile
from src.services.pipeline_state import research_label


class ProfilerAgent(BaseAgent):
    def __init__(self, gemini_service):
        super().__init__(
            name="Character Profiler Agent",
            role="Structured Trait & Feat Extractor",
            gemini_service=gemini_service
        )

    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        for team in (context["team_a"], context["team_b"]):
            for member in team:
                name = member["name"]
                form_id = member["form_id"]

                if member.get("is_known"):
                    self.log(f"'{name}' already profiled; loading existing data.")
                    member["traits"], member["feats"] = await self._load_existing(session, form_id)
                    continue

                # The version-qualified label, not the bare name: search results are
                # generic ("Vegeta" pages cover every era), so without this the extraction
                # happily mixes in another era's feats.
                label = research_label(member)
                self.log(f"Extracting structured profile for '{label}'.")
                member["traits"], member["feats"] = await self._extract_and_persist(
                    session,
                    form_id,
                    label,
                    member.get("research_records", []),
                    member.get("extracted_docs", []),
                )

        return context

    async def _load_existing(self, session: AsyncSession, form_id: int):
        form = await session.get(CharacterForm, form_id)
        traits = json.loads(form.traits_json) if form.traits_json else {}
        feats_res = await session.execute(select(DBFeat).where(DBFeat.character_form_id == form_id))
        feats = [{"title": f.title, "description": f.description} for f in feats_res.scalars().all()]
        return traits, feats

    async def _extract_and_persist(
        self, session: AsyncSession, form_id: int, contender_name: str, records: List, extracted_docs: List[str]
    ):
        known_traits = (await session.execute(select(TraitCatalog))).scalars().all()
        catalog_hint = "\n".join(f"- {t.code}: {t.display_name} ({t.category.value}, {t.value_type.value})" for t in known_traits)

        numbered_sources = "\n".join(
            f"[{i}] {r['snippet']} (from {r['source_url']})" for i, r in enumerate(records)
        )
        if extracted_docs:
            # Full page text now (~17k chars each), where this used to be a 200-char stub, so
            # budget by characters rather than document count: all pages get represented, and
            # the prompt stays within a sane size.
            budget = 60_000 // max(len(extracted_docs), 1)
            numbered_sources += "\n\nExtracted document excerpts:\n" + "\n---\n".join(
                doc[:budget] for doc in extracted_docs
            )

        prompt = (
            f"Extract a structured power-scaling profile for '{contender_name}' from the numbered sources below.\n\n"
            f"CRITICAL -- profile ONLY that exact version. The sources are general-purpose pages "
            f"that usually cover the character's whole history, including later series, forms, and "
            f"power-ups this version never had. Ignore any feat, transformation, or power source "
            f"that belongs to a different era or a form beyond the one named above, even when the "
            f"page presents it prominently. If the sources don't establish a stat for THIS version, "
            f"omit it or give it low confidence rather than borrowing a stronger version's number.\n\n"
            f"Known trait catalog (reuse one of these codes whenever it genuinely applies):\n{catalog_hint}\n\n"
            f"If '{contender_name}' has a genuinely novel power source, hax ability, or stat not covered by the "
            f"known catalog above, invent a new descriptive snake_case trait_code for it and classify its own "
            f"category and value_type -- do not force it into an existing code that doesn't really fit.\n\n"
            f"Numbered sources:\n{numbered_sources or '(no sources found)'}\n\n"
            f"Cite the source_index for each trait/feat when the sources support it."
        )
        system_instruction = (
            "You are a meticulous power-scaling researcher compiling a character dossier. "
            "Only assert traits/feats with reasonable support from the given sources; use lower confidence "
            "for anything speculative rather than omitting it."
        )

        profile: CharacterProfile = await self.gemini_service.generate_structured(
            prompt=prompt, response_schema=CharacterProfile, system_instruction=system_instruction
        )

        merged_traits: Dict[str, Dict[str, Any]] = {}
        code_to_catalog_id: Dict[str, int] = {}
        for trait in profile.traits:
            catalog_row = await get_or_create_trait_catalog(
                session, trait.trait_code, trait.display_name, trait.category, trait.value_type
            )
            merged_traits[catalog_row.code] = {
                "value_label": trait.value_label,
                "confidence": trait.confidence,
            }
            code_to_catalog_id[catalog_row.code] = catalog_row.id

        form = await session.get(CharacterForm, form_id)
        form.traits_json = json.dumps(merged_traits)

        feat_dicts = []
        for feat in profile.feats:
            trait_catalog_id = code_to_catalog_id.get(normalize_trait_code(feat.trait_code)) if feat.trait_code else None
            source = records[feat.source_index] if feat.source_index is not None and 0 <= feat.source_index < len(records) else (records[0] if records else None)
            if source is None:
                continue  # feats.source_research_id is NOT NULL; skip feats we can't attribute to a real source
            session.add(DBFeat(
                character_form_id=form_id,
                trait_catalog_id=trait_catalog_id,
                title=feat.title,
                description=feat.description,
                confidence=feat.confidence,
                source_research_id=source["id"],
            ))
            feat_dicts.append({"title": feat.title, "description": feat.description})

        await session.flush()
        return merged_traits, feat_dicts
