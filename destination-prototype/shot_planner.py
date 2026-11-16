"""Shot planning and visual bible for Dark Fairytale scene generation.

Translates approved narrative beats into deliberate visual coverage instead of one
generic illustration per paragraph. Every recurring character is anchored in a
persistent visual bible so appearance stays consistent across the episode.

Automated verification of semantic quality (relevance, character consistency,
anatomy, lettering) is not reliably available with the free stack, so those
checks are flagged for human review rather than silently passed.
"""
from __future__ import annotations

from typing import Any

# Shot sizes and coverage used to avoid an illustrated-slideshow look.
SHOT_TYPES = (
    "establishing",
    "wide",
    "medium",
    "close_up",
    "object",
    "cutaway",
    "reveal",
    "action",
    "interaction",
)

# A sensible, configurable shot budget so free provider quotas are not burned
# blindly. One image per planned shot; a shot may cover a whole scene.
DEFAULT_SHOT_BUDGET = 12

# Camera suggestions that pair with shot types to create real visual movement
# direction for the image model (composition, not generated video).
CAMERA_BY_SHOT = {
    "establishing": "wide establishing view, deep depth, horizon and atmosphere",
    "wide": "full-body wide shot, characters in environment, room to move",
    "medium": "medium shot from the waist up, clear interaction space",
    "close_up": "tight close-up on the face and eyes, emotional detail",
    "object": "close-up on the important object or clue, shallow focus",
    "cutaway": "atmospheric cutaway detail, mood and texture",
    "reveal": "dramatic reveal composition, subject entering the frame",
    "action": "mid-action shot, movement and tension visible",
    "interaction": "two-shot interaction, characters reacting to each other",
}


def character_bible(plan: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Persistent visual identity for every recurring character in the episode."""
    bible: dict[str, dict[str, str]] = {}
    for character in plan.get("characters", []):
        cid = str(character.get("id", ""))
        if not cid:
            continue
        bible[cid] = {
            "name": str(character.get("name", "")),
            "role": str(character.get("role", "")),
            "visual_identity": str(character.get("visual_identity", "")),
        }
    return bible


def _varied_shot_type(index: int, total: int, override: str | None,
                      previous: str | None) -> str:
    """Pick a shot type with variety, first = establishing, last emotional beat = reveal/close."""
    if override and override in SHOT_TYPES:
        return override
    if index == 0:
        return "establishing"
    if index == total - 1:
        return "reveal"
    # Rotate through a varied sequence so adjacent shots rarely match.
    sequence = ("wide", "medium", "close_up", "wide", "object", "medium",
                "interaction", "cutaway", "action")
    candidate = sequence[index % len(sequence)]
    if previous and candidate == previous:
        candidate = sequence[(index + 1) % len(sequence)]
    return candidate


def build_shot_plan(plan: dict[str, Any], budget: int | None = None) -> dict[str, Any]:
    """Translate narrative beats into a shot list aligned one-to-one with scenes.

    Returns a dict with the per-scene shot specs, the character bible, the total
    shot budget, and a disclosure that still artwork is being directed cinematically,
    not generated as moving footage.
    """
    scenes = plan.get("scenes", [])
    if not scenes:
        raise ValueError("Cannot build a shot plan for a plan with no scenes")
    shot_budget = int(budget or DEFAULT_SHOT_BUDGET)
    shot_budget = max(1, min(shot_budget, len(scenes)))
    bible = character_bible(plan)
    visual_style = str(plan.get("visual_style", ""))
    shots = []
    previous = None
    for index, scene in enumerate(scenes):
        override = str(scene.get("shot_type", "")).strip() or None
        shot_type = _varied_shot_type(index, len(scenes), override, previous)
        previous = shot_type
        shots.append({
            "scene_id": str(scene.get("id", f"scene-{index:02d}")),
            "scene_index": index,
            "shot_type": shot_type,
            "framing": CAMERA_BY_SHOT[shot_type],
            "narration": str(scene.get("narration", "")),
            "character_ids": list(scene.get("character_ids", [])),
        })
    return {
        "story": plan.get("title", ""),
        "story_id": plan.get("story_id"),
        "source": plan.get("source"),
        "shot_budget": shot_budget,
        "shot_count": len(shots),
        "characters": bible,
        "visual_style": visual_style,
        "shots": shots,
        "disclosure": ("Shot plan directs AI-illustrated still artwork with varied camera "
                       "framing and composition. These are directed stills, not generated "
                       "moving video footage."),
        "approved": False,
        "published": False,
    }


def shot_prompt(shot: dict[str, Any], bible: dict[str, dict[str, str]],
                style: str, negative: str) -> str:
    """Build one cinematic image prompt from a shot spec and the character bible."""
    parts = []
    shot_type = str(shot.get("shot_type", "medium"))
    parts.append(f"Create one cinematic vertical 9:16 storybook illustration, "
                 f"{shot_type} shot: {str(shot.get('framing', '')).strip()}.")
    parts.append(f"Narrated moment: {str(shot.get('narration', '')).strip()}")
    if shot.get("character_ids"):
        parts.append("Recurring character designs (keep these appearances consistent):")
        for cid in shot["character_ids"]:
            char = bible.get(str(cid), {})
            if char:
                parts.append(f"- {char.get('name', cid)} ({char.get('role', '')}): "
                             f"{char.get('visual_identity', '')}")
    parts.append(f"Style: {style}")
    parts.append(negative)
    prompt = " ".join(parts)
    if len(prompt) > 2048:
        raise ValueError(
            f"Shot prompt for {shot.get('scene_id')} is {len(prompt)} characters; "
            "shorten the framing or character identity, never truncate it."
        )
    return prompt


def shot_quality_flags(shot: dict[str, Any]) -> list[str]:
    """Heuristic flags that require human review; automated semantic checks are not
    reliable enough to pass or fail an image on their own."""
    flags = []
    narration = str(shot.get("narration", ""))
    if not narration.strip():
        flags.append("missing narration for shot; relevance cannot be verified")
    if not shot.get("character_ids"):
        flags.append("no recurring character assigned; character consistency cannot be tracked")
    shot_type = str(shot.get("shot_type", ""))
    if shot_type not in SHOT_TYPES:
        flags.append(f"unrecognized shot type '{shot_type}'; framing may be generic")
    return flags
