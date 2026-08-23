"""
Idempotent catalog/taxonomy seed data, sourced directly from vsbattles.fandom.com
(Tiering_System, Attack_Potency, Speed, Hax pages fetched 2026-08-20).

This seeds REFERENCE data only (trait_catalog, tier_scales, tier_scale_levels) --
never character/feat/matchup content, which is expected to come from the agent
pipeline at runtime. See init_db() in src/db/base.py for how this gets invoked.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import TierScale, TierScaleLevel, TraitCatalog, TraitCategory, TraitValueType

# Attack Potency / Durability / Striking Strength scale.
# (rank, code, label, low_joules, high_joules) -- ranges above 3-A are open-ended/qualitative
# per the wiki itself, so range_high is left None past that point.
AP_TIER_LEVELS = [
    (1, "11-C", "Low Hypoverse level", None, None),
    (2, "11-B", "Hypoverse level", None, None),
    (3, "11-A", "High Hypoverse level", None, None),
    (4, "10-C", "Below Average Human level", 0, 60),
    (5, "10-B", "Human level", 60, 106),
    (6, "10-A", "Athlete level", 106, 300),
    (7, "9-C", "Street level", 300, 1.5e4),
    (8, "9-B", "Wall level", 1.5e4, 2.092e7),
    (9, "9-A", "Small Building level", 2.092e7, 1.046e9),
    (10, "8-C", "Building level", 1.046e9, 8.368e9),
    (11, "High 8-C", "Large Building level", 8.368e9, 4.6024e10),
    (12, "8-B", "City Block level", 4.6024e10, 4.184e11),
    (13, "8-A", "Multi-City Block level", 4.184e11, 4.184e12),
    (14, "Low 7-C", "Small Town level", 4.184e12, 2.42672e13),
    (15, "7-C", "Town level", 2.42672e13, 4.184e14),
    (16, "High 7-C", "Large Town level", 4.184e14, 4.184e15),
    (17, "Low 7-B", "Small City level", 4.184e15, 2.63592e16),
    (18, "7-B", "City level", 2.63592e16, 4.184e17),
    (19, "7-A", "Mountain level", 4.184e17, 4.184e18),
    (20, "High 7-A", "Large Mountain level", 4.184e18, 1.79912e19),
    (21, "6-C", "Island level", 1.79912e19, 4.184e20),
    (22, "High 6-C", "Large Island level", 4.184e20, 4.184e21),
    (23, "Low 6-B", "Small Country level", 4.184e21, 2.9288e22),
    (24, "6-B", "Country level", 2.9288e22, 4.184e23),
    (25, "High 6-B", "Large Country level", 4.184e23, 3.17984e24),
    (26, "6-A", "Continent level", 3.17984e24, 1.855604e25),
    (27, "High 6-A", "Multi-Continent level", 1.855604e25, 1.24e29),
    (28, "5-C", "Moon level", 1.24e29, 1.81e30),
    (29, "Low 5-B", "Small Planet level", 1.81e30, 2.487e32),
    (30, "5-B", "Planet level", 2.487e32, 1.59e34),
    (31, "5-A", "Large Planet level", 1.59e34, 6.906e37),
    (32, "High 5-A", "Brown Dwarf level", 6.906e37, 3.139e40),
    (33, "Low 4-C", "Small Star level", 3.139e40, 5.693e41),
    (34, "4-C", "Star level", 5.693e41, 3.182e42),
    (35, "High 4-C", "Large Star level", 3.182e42, 2.923e45),
    (36, "4-B", "Solar System level", 2.923e45, 2.008e57),
    (37, "4-A", "Multi-Solar System level", 2.008e57, 1.053e66),
    (38, "3-C", "Galaxy level", 1.053e66, 8.593e68),
    (39, "3-B", "Multi-Galaxy level", 8.593e68, 2.825e92),
    (40, "3-A", "Universe level", 2.825e92, None),
    (41, "High 3-A", "High Universe level", None, None),
    (42, "Low 2-C", "Universe level+", None, None),
    (43, "2-C", "Low Multiverse level", None, None),
    (44, "2-B", "Multiverse level", None, None),
    (45, "2-A", "Multiverse level+", None, None),
    (46, "Low 1-C", "Low Complex Multiverse level", None, None),
    (47, "1-C", "Complex Multiverse level", None, None),
    (48, "High 1-C", "High Complex Multiverse level", None, None),
    (49, "1-B", "Hyperverse level", None, None),
    (50, "High 1-B", "High Hyperverse level", None, None),
    (51, "Low 1-A", "Low Outerverse level", None, None),
    (52, "1-A", "Outerverse level", None, None),
    (53, "High 1-A", "High Outerverse level", None, None),
    (54, "0", "Boundless", None, None),
]

# Speed scale. (rank, label, low_m_s, high_m_s) -- Infinite Speed and Immeasurable have no
# numeric bound by definition. Omnipresence is deliberately NOT included here: the wiki
# itself notes it's "technically a state of being, rather than a speed" -- modeled below
# as its own boolean trait instead of a rung on this ranked scale.
SPEED_TIER_LEVELS = [
    (1, "Immobile", 0, 0),
    (2, "Below Average Human", 0, 5),
    (3, "Average Human", 5, 7.7),
    (4, "Athletic Human", 7.7, 10.03),
    (5, "Peak Human", 10.03, 12.43),
    (6, "Superhuman", 12.43, 34.3),
    (7, "Subsonic", 34.3, 171.5),
    (8, "Subsonic+", 171.5, 308.7),
    (9, "Transonic", 308.7, 377.3),
    (10, "Supersonic", 377.3, 857.5),
    (11, "Supersonic+", 857.5, 1715),
    (12, "Hypersonic", 1715, 3430),
    (13, "Hypersonic+", 3430, 8575),
    (14, "High Hypersonic", 8575, 17150),
    (15, "High Hypersonic+", 17150, 34300),
    (16, "Massively Hypersonic", 34300, 343000),
    (17, "Massively Hypersonic+", 343000, 2997925),
    (18, "Sub-Relativistic", 2997925, 14989621.4),
    (19, "Sub-Relativistic+", 14989621.4, 2.998e7),
    (20, "Relativistic", 2.998e7, 1.499e8),
    (21, "Relativistic+", 1.499e8, 299792458),
    (22, "Speed of Light", 299792458, 299792458),
    (23, "FTL", 299792458, 2.998e9),
    (24, "FTL+", 2.998e9, 2.998e10),
    (25, "Massively FTL", 2.998e10, 2.998e11),
    (26, "Massively FTL+", 2.998e11, None),
    (27, "Infinite Speed", None, None),
    (28, "Immeasurable", None, None),
]

# Lifting Strength scale (rank, label, low_kgf, high_kgf) -- a genuinely separate scale from
# Attack Potency, in kilogram-force, not joules. Striking Strength, by contrast, was confirmed
# to reuse the same tier labels/scale as Attack Potency (unified by the wiki in 2017/2022), so
# it does NOT get its own scale below.
LIFTING_STRENGTH_LEVELS = [
    (1, "Insubstantial", None, None),
    (2, "Below Average Human", 0, 50),
    (3, "Average Human", 50, 80),
    (4, "Above Average Human", 80, 120),
    (5, "Athletic Human", 120, 227),
    (6, "Peak Human", 227, 545.2),
    (7, "Superhuman", None, None),
    (8, "Class 1", 545.2, 1000),
    (9, "Class 5", 1000, 5000),
    (10, "Class 10", 5000, 1e4),
    (11, "Class 25", 1e4, 2.5e4),
    (12, "Class 50", 2.5e4, 5e4),
    (13, "Class 100", 5e4, 1e5),
    (14, "Class K", 1e5, 1e6),
    (15, "Class M", 1e6, 1e9),
    (16, "Class G", 1e9, 1e12),
    (17, "Class T", 1e12, 1e15),
    (18, "Class P", 1e15, 1e18),
    (19, "Class E", 1e18, 1e21),
    (20, "Class Z", 1e21, 1e24),
    (21, "Class Y", 1e24, 1e27),
    (22, "Pre-Stellar", 1e27, 2e29),
    (23, "Stellar", 2e29, 3.977e32),
    (24, "Multi-Stellar", 3.977e32, 1.6e42),
    (25, "Galactic", 1.6e42, 6e43),
    (26, "Multi-Galactic", 6e43, 1.5e53),
    (27, "Universal", 1.5e53, None),
    (28, "Infinite", None, None),
    (29, "Immeasurable", None, None),
    (30, "Inapplicable", None, None),
]

# Range scale (rank, label, low_m, high_m) -- a real numeric scale in meters/light-years,
# open-ended past "Universal" exactly like the other scales.
_LY = 9.4607e15  # meters per light-year
RANGE_TIER_LEVELS = [
    (1, "Below Standard Melee Range", 0, 0.5),
    (2, "Standard Melee Range", 0.5, 1),
    (3, "Extended Melee Range", 1, 3),
    (4, "Several Meters", 3, 10),
    (5, "Tens of Meters", 10, 100),
    (6, "Hundreds of Meters", 100, 1000),
    (7, "Kilometers", 1000, 1e4),
    (8, "Tens of Kilometers", 1e4, 1e5),
    (9, "Hundreds of Kilometers", 1e5, 1e6),
    (10, "Thousands of Kilometers", 1e6, 2.0037e7),
    (11, "Planetary", 2.0037e7, 1.3914e9),
    (12, "Stellar", 1.3914e9, 5.029e10),
    (13, "Interplanetary", 5.029e10, 4.22 * _LY),
    (14, "Interstellar", 4.22 * _LY, 5e4 * _LY),
    (15, "Galactic", 5e4 * _LY, 2.5e6 * _LY),
    (16, "Intergalactic", 2.5e6 * _LY, 4.66e10 * _LY),
    (17, "Universal", 4.66e10 * _LY, None),
    (18, "High Universal", None, None),
    (19, "Universal+", None, None),
    (20, "Interdimensional", None, None),
    (21, "Low Multiversal", None, None),
    (22, "Multiversal", None, None),
    (23, "Multiversal+", None, None),
    (24, "Extradimensional", None, None),
    (25, "Low Complex Multiversal", None, None),
    (26, "Complex Multiversal", None, None),
    (27, "High Complex Multiversal", None, None),
    (28, "Hyperversal", None, None),
    (29, "High Hyperversal", None, None),
    (30, "Low Outerversal", None, None),
    (31, "Outerversal", None, None),
    (32, "Outerversal+", None, None),
    (33, "High Outerversal", None, None),
    (34, "High Outerversal+", None, None),
    (35, "Boundless", None, None),
]

# Stamina scale -- the wiki explicitly discourages numeric quantification ("best to explain
# and source examples... rather than simply state a generalised rating"), so this is an
# ordered label list with no numeric bounds, not a measured scale. "Unknown" is a real
# guideline term (placeholder for missing data), not a power level.
STAMINA_TIER_LEVELS = [
    (1, "Unknown", None, None),
    (2, "Below Average", None, None),
    (3, "Average", None, None),
    (4, "Athletic", None, None),
    (5, "Peak Human", None, None),
    (6, "Superhuman", None, None),
    (7, "Infinite", None, None),
    (8, "Inapplicable", None, None),
]

# Intelligence scale -- also explicitly non-numeric on the wiki (IQ numbers called
# "meaningless" without feats); ordered label list only.
INTELLIGENCE_TIER_LEVELS = [
    (1, "Mindless", None, None),
    (2, "Instinctive", None, None),
    (3, "Animalistic", None, None),
    (4, "High Animalistic", None, None),
    (5, "Below Average", None, None),
    (6, "Average", None, None),
    (7, "Above Average", None, None),
    (8, "Gifted", None, None),
    (9, "Genius", None, None),
    (10, "Extraordinary Genius", None, None),
    (11, "Supergenius", None, None),
    (12, "Nigh-Omniscient", None, None),
    (13, "Omniscient", None, None),
]

# "Hax" catalog entries, sourced from the Hax page's own "Examples" list. Franchise-specific
# energy sources (Ki, Chakra, Nen, ...) are deliberately NOT pre-seeded here -- per the
# original design, those are meant to be inserted organically the first time a relevant
# character is researched, not guessed at up front.
HAX_TRAITS = [
    ("reality_warping", "Reality Warping"),
    ("probability_manipulation", "Probability Manipulation"),
    ("law_manipulation", "Law Manipulation"),
    ("physics_manipulation", "Physics Manipulation"),
    ("conceptual_manipulation", "Conceptual Manipulation"),
    ("void_manipulation", "Void Manipulation"),
    ("mind_manipulation", "Mind Manipulation"),
    ("causality_manipulation", "Causality Manipulation"),
    ("plot_manipulation", "Plot Manipulation"),
]



async def seed_catalog(session: AsyncSession) -> bool:
    """Inserts reference/taxonomy data if it isn't already present. Returns True if it seeded anything."""
    existing = await session.execute(select(TierScale.id))
    if existing.first() is not None:
        return False

    ap_scale = TierScale(
        name="VS Battles Attack Potency / Durability",
        description="Shared energy-based tier scale for Attack Potency, Durability, and (since 2017/2022) Striking Strength.",
    )
    speed_scale = TierScale(name="VS Battles Speed", description="Combat/travel speed scale.")
    lifting_scale = TierScale(
        name="VS Battles Lifting Strength",
        description="Separate kgf-based Class scale -- explicitly not comparable to Attack Potency/Striking Strength.",
    )
    range_scale = TierScale(name="VS Battles Range", description="Meter/light-year based scale.")
    stamina_scale = TierScale(
        name="VS Battles Stamina",
        description="Ordered labels only, no numeric bounds -- the wiki explicitly discourages quantifying this.",
    )
    intelligence_scale = TierScale(
        name="VS Battles Intelligence",
        description="Ordered labels only, no numeric bounds -- IQ numbers are explicitly rejected as meaningless on the wiki.",
    )
    session.add_all([ap_scale, speed_scale, lifting_scale, range_scale, stamina_scale, intelligence_scale])
    await session.flush()

    session.add_all(
        TierScaleLevel(
            tier_scale_id=ap_scale.id, rank=rank, code=code, label=label,
            range_low=low, range_high=high,
        )
        for rank, code, label, low, high in AP_TIER_LEVELS
    )
    session.add_all(
        TierScaleLevel(
            tier_scale_id=speed_scale.id, rank=rank, code=None, label=label,
            range_low=low, range_high=high,
        )
        for rank, label, low, high in SPEED_TIER_LEVELS
    )
    session.add_all(
        TierScaleLevel(
            tier_scale_id=lifting_scale.id, rank=rank, code=None, label=label,
            range_low=low, range_high=high,
        )
        for rank, label, low, high in LIFTING_STRENGTH_LEVELS
    )
    session.add_all(
        TierScaleLevel(
            tier_scale_id=range_scale.id, rank=rank, code=None, label=label,
            range_low=low, range_high=high,
        )
        for rank, label, low, high in RANGE_TIER_LEVELS
    )
    session.add_all(
        TierScaleLevel(
            tier_scale_id=stamina_scale.id, rank=rank, code=None, label=label,
            range_low=low, range_high=high,
        )
        for rank, label, low, high in STAMINA_TIER_LEVELS
    )
    session.add_all(
        TierScaleLevel(
            tier_scale_id=intelligence_scale.id, rank=rank, code=None, label=label,
            range_low=low, range_high=high,
        )
        for rank, label, low, high in INTELLIGENCE_TIER_LEVELS
    )

    session.add_all(
        TraitCatalog(
            code=code, display_name=name, category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, unit="Joules", tier_scale_id=ap_scale.id,
        )
        for code, name in [
            ("attack_potency", "Attack Potency"),
            ("durability", "Durability"),
            ("striking_strength", "Striking Strength"),
        ]
    )
    session.add(
        TraitCatalog(
            code="speed", display_name="Speed", category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, unit="m/s", tier_scale_id=speed_scale.id,
        )
    )
    session.add(
        TraitCatalog(
            code="lifting_strength", display_name="Lifting Strength", category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, unit="kgf", tier_scale_id=lifting_scale.id,
            description="Not comparable to Attack Potency/Striking Strength per the wiki's own explanation.",
        )
    )
    session.add(
        TraitCatalog(
            code="range", display_name="Range", category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, unit="m", tier_scale_id=range_scale.id,
        )
    )
    session.add(
        TraitCatalog(
            code="stamina", display_name="Stamina", category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, tier_scale_id=stamina_scale.id,
            description="Ranked labels only; the wiki explicitly discourages a single generalised numeric rating.",
        )
    )
    session.add(
        TraitCatalog(
            code="intelligence", display_name="Intelligence", category=TraitCategory.PHYSICAL,
            value_type=TraitValueType.TIER, tier_scale_id=intelligence_scale.id,
            description="Ranked labels only; IQ numbers are explicitly rejected as meaningless on the wiki.",
        )
    )
    session.add(
        TraitCatalog(
            code="omnipresence", display_name="Omnipresence", category=TraitCategory.META,
            value_type=TraitValueType.BOOLEAN,
            description='Not a speed rating; "a state of being" per the wiki\'s own Speed page.',
        )
    )
    session.add_all(
        TraitCatalog(
            code=code, display_name=name, category=TraitCategory.HAX,
            value_type=TraitValueType.BOOLEAN,
            description="Sourced from vsbattles.fandom.com/wiki/Hax examples list.",
        )
        for code, name in HAX_TRAITS
    )

    await session.commit()
    return True
