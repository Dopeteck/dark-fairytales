"""Strict visual-role policy for the Rumpelstiltskin review.

This module deliberately does not use CLIP scores to establish story identity.
The resolver still owns rights, format, size, OCR, duplicate, period and CLIP
threshold gates; this module only classifies the metadata of candidates that
have already passed those gates.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

STORY_ALIASES = (
    "Rumpelstiltskin",
    "Rumpelstilzchen",
    "Rumpel-Stilts-Kin",
    "Rumpel-Stiltskin",
    "Rumpelstiltzkin",
    "Rumpel-Stilts-Ken",
)

# Edition-specific Commons categories missed by the first review search.
# Commons page membership is useful provenance; pages still have to pass OCR,
# rights, dimensions, duplicate, CLIP and human-review gates.
STORY_COMMONS_CATEGORIES = (
    "Rumpelstilzchen (1812, Grimm)",
    "Grimm's Goblins/Rumpel-Stilts-Kin",
    "Blue Fairy Book/Rumpelstiltzkin",
    "Grimm's Household Tales (Edwardes, Bell)/Rumpel-Stilts-Ken",
)

UNRELATED_SUBJECT_MARKERS = (
    "king lear", "queen victoria", "mary queen of scots",
    "madonna", "virgin mary", "jesus", "christ child", "nativity",
    "holy family", "saint", "eagle", "peacock", "owl", "pigeon",
    "falcon", "parrot", "bird", "portrait",
)
UNSUITABLE_PHOTO_MARKERS = (
    "photograph", "photographic", "photo", "newspaper",
    "albumen print", "gelatin silver print", "cabinet card",
    "daguerreotype", "ambrotype", "carte de visite",
)

# Every group must have at least one metadata match. These are deliberately
# conservative; an empty result is preferable to using unrelated historical art.
EXACT_SCENE_REQUIREMENTS: dict[str, list[list[str]]] = {
    "beat-01-threat": [["king", "king's room", "king threatens"], ["daughter", "miller's daughter"]],
    "beat-02-boast": [["father", "miller"], ["boast", "brag", "claims his daughter can spin"]],
    "beat-03-first-bargains": [["spinning wheel", "spinning-wheel", "spinnrad"], ["dwarf", "little man", "imp"]],
    "beat-04-king-demands": [["king", "könig"], ["straw", "spinning wheel", "spinnrad"]],
    "beat-05-child-pact": [["first child", "child bargain", "promise of the child", "promises her child"]],
    "beat-06-claim": [["queen", "königin"], ["infant", "baby", "newborn", "child"]],
    "beat-07-three-days": [["name", "guess his name", "naming"], ["messenger", "herald", "courier", "bote"]],
    "beat-08-forest-fire": [["forest", "woods", "woodland", "wald"], ["fire", "bonfire", "flames", "feuer"], ["dancing", "dance", "dancing on one leg"]],
    "beat-09-foot-revelation": [["foot", "feet", "fuß"], ["floor", "floorboards", "wooden floor", "boden"]],
}


SYMBOLIC_REQUIREMENTS: dict[str, list[list[str]]] = {
    "beat-01-threat": [
        ["straw", "straw bundle", "Stroh"],
        ["spinning wheel", "spinning-wheel", "spinnrad", "spindle wheel"],
    ],
    "beat-02-boast": [
        ["miller", "miller's daughter", "Müller"],
        ["daughter", "Tochter"],
    ],
    "beat-03-first-bargains": [
        ["spinning wheel", "spinning-wheel", "spinnrad"],
        ["straw", "Stroh", "gold", "golden"],
    ],
    "beat-04-king-demands": [
        ["king", "König"],
        ["straw", "Stroh", "spinning wheel", "spinnrad"],
    ],
    "beat-05-child-pact": [
        ["cradle", "crib", "baby basket"],
        ["infant", "baby", "newborn", "child", "Kind"],
    ],
    "beat-06-claim": [
        ["queen", "Königin"],
        ["infant", "baby", "newborn", "cradle", "Kind"],
    ],
    "beat-07-three-days": [
        ["messenger", "herald", "courier", "Bote"],
        ["forest", "woods", "woodland", "Wald"],
    ],
    "beat-08-forest-fire": [
        ["fire", "bonfire", "flames", "Feuer"],
        ["forest", "woods", "woodland", "Wald"],
    ],
    "beat-09-foot-revelation": [
        ["foot", "feet", "Fuß", "footprint"],
        ["floor", "floorboards", "wooden floor", "Boden"],
    ],
}

SYMBOLIC_SEARCH_TERMS: dict[str, list[str]] = {
    "beat-01-threat": ["antique straw bundle spinning wheel engraving", "historical spinning wheel straw illustration"],
    "beat-02-boast": ["historical miller and daughter engraving", "antique miller daughter illustration"],
    "beat-03-first-bargains": ["antique spinning wheel straw gold illustration", "historical spinning wheel golden straw engraving"],
    "beat-04-king-demands": ["antique king straw spinning chamber illustration", "historical royal chamber straw spinning wheel"],
    "beat-05-child-pact": ["antique cradle infant historical illustration", "antique wooden cradle baby engraving"],
    "beat-06-claim": ["historical queen infant cradle illustration", "antique queen with child engraving"],
    "beat-07-three-days": ["antique messenger forest illustration", "historical courier woodland engraving"],
    "beat-08-forest-fire": ["antique forest fire bonfire illustration", "historical woodland fire engraving"],
    "beat-09-foot-revelation": ["antique foot wooden floor illustration", "historical foot floorboards engraving"],
}

EXACT_SEARCH_TERMS = [
    "Rumpelstiltskin historical storybook illustration",
    "Rumpelstilzchen historical fairy tale illustration",
    "Rumpel-Stilts-Kin Grimm illustration",
    "Rumpelstiltzkin Blue Fairy Book illustration",
    "Rumpel-Stilts-Ken Grimm household tales illustration",
]


def _normalise(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _contains(text: str, term: str) -> bool:
    needle = _normalise(term)
    return bool(needle and f" {needle} " in f" {text} ")


def candidate_metadata_text(candidate: dict[str, Any]) -> str:
    visual = candidate.get("visual_metadata") or {}
    values = [
        candidate.get("title", ""),
        candidate.get("description", ""),
        *candidate.get("categories", []),
        *candidate.get("facets", []),
        *visual.get("categories", []),
        *visual.get("facets", []),
        visual.get("date_text", ""),
    ]
    return _normalise(" ".join(str(v) for v in values if v is not None))


def exact_scene_match_status(candidate: dict[str, Any], beat_id: str) -> tuple[str, list[str]]:
    """Check whether exact-story metadata also identifies this beat's visual.

    Story identity and beat identity are different facts. A book-category hit
    proves tale provenance, but a generic category alone cannot place an image
    in a particular narrated scene.
    """
    text = candidate_metadata_text(candidate)
    groups = EXACT_SCENE_REQUIREMENTS.get(beat_id, [])
    missing = [
        " / ".join(group)
        for group in groups
        if not any(_contains(text, term) for term in group)
    ]
    return ("metadata_scene_match", []) if not missing else ("story_identity_only_unplaced", missing)


def classify_candidate(candidate: dict[str, Any], beat_id: str) -> str:
    """Return exact, relevant-symbolic, or unrelated based on source metadata.

    CLIP, a licence, historical age, and a generic scene keyword are not proof
    that an image illustrates this story. A story alias in source metadata is
    the minimum exact-story provenance anchor.
    """
    text = candidate_metadata_text(candidate)
    if any(_contains(text, alias) for alias in STORY_ALIASES):
        return "exact_story_illustration"
    if any(_contains(text, marker) for marker in UNRELATED_SUBJECT_MARKERS):
        return "unrelated_contextual_art"
    if any(_contains(text, marker) for marker in UNSUITABLE_PHOTO_MARKERS):
        return "unrelated_contextual_art"
    groups = SYMBOLIC_REQUIREMENTS.get(beat_id, [])
    if groups and all(any(_contains(text, term) for term in group) for group in groups):
        return "symbolic_contextual_asset"
    return "unrelated_contextual_art"


def build_review_scene(raw: dict[str, Any], index: int, visual_mode: str, seed_files: list[str] | None = None) -> dict[str, Any]:
    sid = str(raw["id"])
    requirement = raw.get("asset_requirement") or {}
    visual = str(requirement.get("must_show", ""))
    if visual_mode not in ("exact", "symbolic"):
        raise ValueError(f"Unknown visual mode: {visual_mode}")

    if visual_mode == "exact":
        return {
            "id": f"{sid}-exact",
            "title": raw.get("title", sid),
            "image_type": "historic",
            "named_entities": ["Rumpelstiltskin"],
            "identity_aliases": list(STORY_ALIASES[1:]),
            "identity_fallback_to_clip": False,
            "commons_categories": list(STORY_COMMONS_CATEGORIES),
            "image_search_terms": list(dict.fromkeys([*EXACT_SEARCH_TERMS, *requirement.get("search_terms", [])])),
            "visual_tags": [visual, "Rumpelstiltskin exact historical fairy-tale illustration"],
            "visual_caption": f"An actual historical illustration from the Rumpelstiltskin tale showing {visual}",
            "narration_intent": f"{raw.get('evidence', '')} Tale identity is required in source metadata. Scene: {visual}",
            "required_keywords": [],
            "required_keyword_groups": [],
            "identity_keyword_groups": [],
            "seed_commons_files": list(seed_files or []),
            "max_queries": 8,
            "max_queries_per_provider": 3,
        }

    return {
        "id": f"{sid}-symbolic",
        "title": raw.get("title", sid),
        "image_type": "historic",
        "image_search_terms": list(SYMBOLIC_SEARCH_TERMS.get(sid, [])),
        "visual_tags": [visual, "antique symbolic object or setting illustration"],
        "visual_caption": f"A genuine antique visual specifically showing {visual}",
        "narration_intent": f"Symbolic contextual asset only; it must depict the required objects/settings: {visual}",
        "required_keywords": [],
        "required_keyword_groups": SYMBOLIC_REQUIREMENTS.get(sid, []),
        "identity_keyword_groups": [],
        "banned_keywords": list(UNRELATED_SUBJECT_MARKERS),
        "max_queries": 6,
        "max_queries_per_provider": 2,
    }


def summarize_visual_coverage(beats: list[dict[str, Any]]) -> dict[str, Any]:
    exact_ids: list[str] = []
    symbolic_ids: list[str] = []
    any_ids: list[str] = []
    uncovered: list[str] = []
    for beat in beats:
        beat_id = str(beat.get("scene_id") or beat.get("id") or "")
        candidates = [
            c for c in beat.get("candidates", [])
            if c.get("review_status") != "rejected_duplicate" and c.get("approved") is False
        ]
        exact_usable = any(
            c.get("visual_role") == "exact_story_illustration"
            and c.get("scene_match_status") == "metadata_scene_match"
            for c in candidates
        )
        symbolic_usable = any(c.get("visual_role") == "symbolic_contextual_asset" for c in candidates)
        if exact_usable:
            exact_ids.append(beat_id)
        if symbolic_usable:
            symbolic_ids.append(beat_id)
        if exact_usable or symbolic_usable:
            any_ids.append(beat_id)
        else:
            uncovered.append(beat_id)
    unplaced_exact = [
        c for beat in beats for c in beat.get("candidates", [])
        if c.get("visual_role") == "exact_story_illustration"
        and c.get("scene_match_status") == "story_identity_only_unplaced"
        and c.get("review_status") != "rejected_duplicate"
    ]
    return {
        "story_identified_illustrations_without_verified_beat_placement": len(unplaced_exact),
        "unplaced_story_illustration_titles": list(dict.fromkeys(
            str(c.get("title") or c.get("candidate_title") or "Untitled") for c in unplaced_exact
        )),
        "beats_with_exact_story_illustrations": len(exact_ids),
        "exact_story_illustration_beat_ids": exact_ids,
        "beats_with_suitable_symbolic_assets": len(symbolic_ids),
        "symbolic_asset_beat_ids": symbolic_ids,
        "beats_with_any_automatic_candidates": len(any_ids),
        "beats_lacking_usable_visual": len(uncovered),
        "uncovered_beat_ids": uncovered,
    }
