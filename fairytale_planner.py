"""Daily public-domain fairy-tale selection and source-bound episode planning.

Plans are original, clearly disclosed retellings of a named public-domain text edition.
Model output is validated before any paid/quota-limited image generation begins.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SYSTEM = """You are a skilled spoken-story performer and visual episode planner.
Tell ONE supplied public-domain fairy tale as though a gifted human storyteller is speaking
to one listener, not reading an essay, synopsis, school report or list of events.
Open inside the trouble, mystery or decision that makes this particular tale worth hearing.
Make every beat lead naturally to the next: show what a character wants, what they do,
what goes wrong, what choice they make, and what that choice causes.
Write for the ear. Prefer active verbs, concrete actions and everyday spoken phrasing.
Use contractions where they sound natural. Mix short punchy lines with longer flowing ones.
Let suspense breathe with purposeful questions, pauses and occasional direct dialogue.
Give important discoveries and reversals room to land; do not announce them before they happen.
Vary sentence openings and rhythm. Do not march through the plot with repeated "then",
"after that", "suddenly" or "meanwhile". Avoid generic introductions, filler, moralising,
stiff transitions, repetitive explanations and phrases that sound like a written summary.
The narration must be easy to say aloud in one continuous performance.
Dialogue is dramatized retelling, never claim it is a verbatim quotation from the edition.
Follow only the supplied synopsis and ordered key beats. Do not import film adaptations,
modern franchises, invented subplots, or unrelated characters. Do not omit the actual ending.
Use the cited edition as the literary source. Make clear that this is a retelling, not a reading
or reproduction of the source text. Avoid graphic violence, sexual content, and frightening
detail inappropriate for a general audience.
Return one valid JSON object only. No markdown, explanations, or code fences.
"""

SOURCE_ANALYSIS_SYSTEM = """You are a literary editor studying one public-domain fairy tale before it is retold.
Read the supplied synopsis and ordered key beats of the cited edition. Produce a structured
source analysis that captures what the retelling must preserve: the central conflict, each
important character (name, role, motivation, what is at stake for them), the key reversals
that change the situation, the climax, and the resolution. Also name the tone and the
essential beats that must not be omitted or replaced. Do not invent subplots, characters,
or endings that are not in the supplied edition. Return one valid JSON object only.
"""

DRAFT_EPISODE_SYSTEM = """You are writing a fairy-tale retelling for the ear, as one storyteller speaking to one listener.
There is no fixed number of scenes and no fixed word count: use as many scenes and as many words
as the source tale actually needs. A short simple tale must not be stretched; a complex tale
must not be crushed. Open inside the trouble, mystery or decision that makes this tale worth
hearing. Build tension through cause and effect: what a character wants, what they do, what
goes wrong, what choice they make, and what that choice causes. Use natural dialogue where it
dramatizes a moment. Give important discoveries, reversals and emotional beats room to land.
Avoid generic introductions, filler, artificial moral lessons, and repetitive transitions.
End with an emotionally satisfying or memorable payoff that matches the cited edition's ending.
Preserve every essential source beat. Return one valid JSON object only.
"""

CRITIC_SYSTEM = """You are an independent editorial reviewer. You did NOT write the draft below.
Assess the drafted fairy-tale retelling against these criteria, giving specific evidence from
the text: hook strength, narrative clarity, character motivation, stakes and tension, pacing
and escalation, dialogue quality, emotional engagement, accuracy to the cited source, whether
important source events have been omitted, and whether the ending delivers a proper payoff.
A story must not pass merely because its JSON is valid. If it fails, return verdict "reject"
with concrete reasons and actionable revision instructions. If it passes, return verdict "pass"
with a brief justification. Return one valid JSON object only.
"""

REVISE_EPISODE_SYSTEM = """You are revising a fairy-tale retelling in response to an independent editor's review.
Apply only the specific rejection reasons and revision instructions supplied. Preserve the
scenes and source beats that passed, fix what failed, keep the cited edition's ending, and
keep the narration written for one continuous spoken performance. Do not re-approve your own
work; a separate critic will re-review the result. Return one valid JSON object only.
"""


def _text(value: Any, field: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be nonempty text of at most {maximum} characters")
    return value.strip()


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not value or len(value) > 72:
        raise ValueError("Story ID must be a short lowercase slug")
    return value


def load_queue(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Fairy-tale queue must use schema_version 1")
    stories = value.get("stories")
    if not isinstance(stories, list) or len(stories) < 8:
        raise ValueError("Fairy-tale queue needs at least eight curated stories")
    seen = set()
    for item in stories:
        if not isinstance(item, dict):
            raise ValueError("Every queue entry must be an object")
        sid = _slug(_text(item.get("id"), "story id", 72))
        if sid in seen:
            raise ValueError(f"Duplicate story ID: {sid}")
        seen.add(sid)
        _text(item.get("title"), "story title", 120)
        source = item.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"{sid}: source edition is required")
        _text(source.get("title"), "source title", 180)
        _text(source.get("author"), "source author", 120)
        url = _text(source.get("url"), "source URL", 500)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"www.gutenberg.org", "gutenberg.org"}:
            raise ValueError(f"{sid}: source must be a secure Project Gutenberg URL")
        _text(item.get("synopsis"), "story synopsis", 1800)
        beats = item.get("key_beats")
        if not isinstance(beats, list) or not 5 <= len(beats) <= 10:
            raise ValueError(f"{sid}: expected 5–10 ordered key beats")
        for beat in beats:
            _text(beat, "key beat", 300)
    return stories


def initial_state() -> dict:
    return {"schema_version": 1, "cycle": 1, "completed_story_ids": [],
            "last_story_id": None, "completed": []}


def next_story(stories: list[dict], state: dict) -> tuple[dict, dict]:
    """Select the next unused enabled tale; never silently repeat within a cycle."""
    state = dict(state or initial_state())
    if state.get("schema_version") != 1:
        raise ValueError("Unsupported fairy-tale rotation state")
    completed = set(state.get("completed_story_ids", []))
    enabled = [x for x in stories if x.get("enabled", True)]
    if not enabled:
        raise ValueError("No enabled fairy tales in the queue")
    candidates = [x for x in enabled if x["id"] not in completed]
    if not candidates:
        state["cycle"] = int(state.get("cycle", 1)) + 1
        state["completed_story_ids"] = []
        candidates = list(enabled)
        last = state.get("last_story_id")
        if len(candidates) > 1:
            candidates = [x for x in candidates if x["id"] != last] or candidates
    selected = candidates[0]
    return selected, state


def _clean_characters(raw_characters: Any) -> tuple[dict[str, str], list[dict]]:
    if not isinstance(raw_characters, list) or not 2 <= len(raw_characters) <= 5:
        raise ValueError("Episode must define 2–5 recurring characters")
    character_map: dict[str, str] = {}
    clean_characters = []
    for item in raw_characters:
        cid = _slug(_text(item.get("id"), "character id", 48))
        if cid in character_map:
            raise ValueError("Duplicate character ID")
        name = _text(item.get("name"), "character name", 80)
        identity = _text(item.get("visual_identity"), "character visual identity", 260)
        role = _text(item.get("role"), "character role", 120)
        character_map[cid] = name
        clean_characters.append({"id": cid, "name": name, "role": role,
                                 "visual_identity": identity})
    return character_map, clean_characters


def _clean_scenes(raw_scenes: Any, character_map: dict[str, str]) -> list[dict]:
    if not isinstance(raw_scenes, list) or len(raw_scenes) < 1:
        raise ValueError("Episode must contain at least one scene")
    clean_scenes = []
    total_words = 0
    for index, item in enumerate(raw_scenes, 1):
        sid = f"scene-{index:02d}"
        scene_title = _text(item.get("title"), f"{sid} title", 90)
        narration = _text(item.get("narration"), f"{sid} narration", 900)
        visual = _text(item.get("visual_prompt"), f"{sid} visual prompt", 900)
        source_beat = item.get("source_beat")
        if source_beat is not None:
            source_beat = _text(source_beat, f"{sid} source beat", 200)
        ids = item.get("character_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 4 or any(x not in character_map for x in ids):
            raise ValueError(f"{sid} must reference 1–4 defined characters")
        if len(set(ids)) != len(ids):
            raise ValueError(f"{sid} has duplicate character references")
        count = len(narration.split())
        total_words += count
        clean_scenes.append({
            "id": sid, "title": scene_title, "narration": narration,
            "visual_prompt": visual, "character_ids": ids,
            "source_beat": source_beat,
            "word_count": count,
        })
    if total_words < 50:
        raise ValueError(f"Episode narration is too short ({total_words} words) to hold an audience")
    if total_words > 900:
        raise ValueError(f"Episode narration is too long ({total_words} words) for a short-form retelling")
    return clean_scenes, total_words


def validate_episode_plan(raw: dict, story: dict | None = None) -> dict:
    """Structurally validate a drafted episode plan.

    Scene count and word count are story-led: there is no fixed scene count and no
    fixed 180–235 word band. A wide sanity band catches degenerate outputs without
    forcing every tale into the same shape.
    """
    if not isinstance(raw, dict):
        raise ValueError("Episode plan must be a JSON object")
    title = _text(raw.get("title"), "episode title", 100)
    logline = _text(raw.get("logline"), "episode logline", 360)
    if story is None:
        basis = raw.get("retelling_basis", {})
        source = raw.get("source", {})
        story = {
            "id": raw.get("story_id"),
            "title": basis.get("queue_title", title) if isinstance(basis, dict) else title,
            "synopsis": basis.get("synopsis", logline) if isinstance(basis, dict) else logline,
            "key_beats": basis.get("key_beats", []) if isinstance(basis, dict) else [],
            "source": source,
        }
    story_id = _slug(_text(story.get("id"), "story ID", 72))
    source = story.get("source")
    if not isinstance(source, dict):
        raise ValueError("Episode must retain its named source edition")
    source_title = _text(source.get("title"), "source title", 180)
    source_author = _text(source.get("author"), "source author", 120)
    source_url = _text(source.get("url"), "source URL", 500)
    parsed_source = urlparse(source_url)
    if parsed_source.scheme != "https" or parsed_source.netloc not in {"www.gutenberg.org", "gutenberg.org"}:
        raise ValueError("Episode source must be a secure Project Gutenberg URL")
    edition_note = _text(source.get("edition_note"), "source edition note", 500)
    character_map, clean_characters = _clean_characters(raw.get("characters"))
    clean_scenes, total_words = _clean_scenes(raw.get("scenes"), character_map)
    narration = "\n\n".join(x["narration"] for x in clean_scenes)
    return {
        "format": "dark_fairytale_episode_v1",
        "story_id": story_id,
        "title": title,
        "series": "Dark Fairytales",
        "logline": logline,
        "source": {
            "title": source_title, "author": source_author,
            "url": source_url, "edition_note": edition_note,
        },
        "retelling_basis": {
            "queue_title": _text(story.get("title"), "queue story title", 120),
            "synopsis": _text(story.get("synopsis"), "queue synopsis", 1800),
            "key_beats": story.get("key_beats", []),
            "scope": "A new, abridged dramatic retelling based on the named edition's synopsis "
                     "and key beats; not a verbatim reading of the full text.",
        },
        "characters": clean_characters,
        "scenes": clean_scenes,
        "narration": narration,
        "narration_word_count": total_words,
        "target_duration_seconds": None,
        "visual_style": "Dark European fairy-tale storybook, painterly cinematic realism, dramatic candlelight, rich brush texture, coherent palette, believable anatomy.",
        "narration_style": "One continuous, conversational oral performance; active verbs, natural spoken phrasing, varied rhythm, purposeful suspense, direct dramatized dialogue, and clear cause-and-effect transitions.",
        "disclosure": "A synthetic-voice, AI-illustrated dramatic retelling based on the cited public-domain edition. Visuals are original dramatizations; dialogue is not presented as verbatim source text.",
        "status": "draft_needs_human_review",
        "approved": False, "published": False,
    }


def validate_critic_assessment(raw: dict) -> dict:
    """Validate the independent critic's structured assessment."""
    if not isinstance(raw, dict):
        raise ValueError("Critic assessment must be a JSON object")
    verdict = _text(raw.get("verdict"), "critic verdict", 20)
    if verdict not in {"pass", "reject"}:
        raise ValueError("Critic verdict must be 'pass' or 'reject'")
    reasons = raw.get("reasons", [])
    if not isinstance(reasons, list):
        raise ValueError("Critic reasons must be a list")
    clean_reasons = [_text(r, "critic reason", 500) for r in reasons]
    if verdict == "reject" and not clean_reasons:
        raise ValueError("A rejected story must carry specific rejection reasons")
    assessment = raw.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError("Critic assessment must include an assessment object")
    criteria = ("hook", "clarity", "motivation", "stakes", "pacing", "dialogue",
                "emotional", "accuracy", "omissions", "payoff")
    clean_assessment = {}
    for criterion in criteria:
        value = assessment.get(criterion, {})
        if not isinstance(value, dict):
            value = {}
        clean_assessment[criterion] = {
            "verdict": str(value.get("verdict", "weak"))[:20],
            "comment": _text(value.get("comment", ""), f"assessment.{criterion} comment", 800),
        }
    revision_instructions = raw.get("revision_instructions", [])
    if not isinstance(revision_instructions, list):
        raise ValueError("Critic revision instructions must be a list")
    clean_instructions = [_text(i, "revision instruction", 800) for i in revision_instructions]
    if verdict == "reject" and not clean_instructions:
        raise ValueError("A rejected story must carry actionable revision instructions")
    return {
        "verdict": verdict,
        "reasons": clean_reasons,
        "assessment": clean_assessment,
        "revision_instructions": clean_instructions,
    }


def analyze_source(story: dict, llm) -> dict:
    """Stage 1: understand the source tale before writing (conflict, characters, stakes,
    reversals, climax, resolution, essential beats)."""
    prompt = {
        "task": "source_analysis",
        "story": {
            "title": story["title"], "synopsis": story["synopsis"],
            "ordered_key_beats": story["key_beats"], "source": story["source"],
        },
        "schema": {
            "title": "episode title",
            "central_conflict": "the central conflict of the tale",
            "characters": [{"id": "short_id", "name": "character name",
                            "role": "story role", "motivation": "what the character wants",
                            "stakes": "what is at stake for them",
                            "visual_identity": "consistent visual appearance"}],
            "key_reversals": ["moments that change the situation"],
            "climax": "the story's climax",
            "resolution": "how the tale ends",
            "tone": "the tale's tone",
            "essential_beats": ["source beats that must not be omitted"],
        },
    }
    return llm.generate(SOURCE_ANALYSIS_SYSTEM, prompt, lambda data: data)


def draft_episode(story: dict, source_analysis: dict, llm) -> dict:
    """Stage 2: draft the narration with a variable scene count led by the story."""
    prompt = {
        "task": "draft_episode",
        "story": {
            "title": story["title"], "synopsis": story["synopsis"],
            "ordered_key_beats": story["key_beats"], "source": story["source"],
        },
        "source_analysis": source_analysis,
        "requirements": {
            "scene_count": "variable; one scene per narrative moment the story needs",
            "style": "natural spoken oral storytelling; one continuous performance",
            "order": "chronological, cause-and-effect; include the full resolution",
            "visuals": "one specific, cinematic visual direction per scene",
            "characters": "2–5 recurring characters, visually distinctive and consistent",
            "guardrails": [
                "Open with a strong hook; end with the cited edition's resolution.",
                "Use only the supplied synopsis, beats and source analysis.",
                "Do not omit the ending or solve a mystery before the discovery.",
                "Do not claim invented dialogue is a verbatim quotation.",
                "Every visual prompt must depict the action narrated in that same scene.",
                "No words, titles, captions, watermarks or lettering in the image.",
            ],
        },
        "schema": {
            "title": "episode title",
            "logline": "one-sentence premise",
            "characters": [{"id": "short_id", "name": "character name",
                            "role": "story role", "visual_identity": "consistent visual appearance"}],
            "scenes": [{"title": "scene label",
                        "narration": "spoken storyteller text",
                        "visual_prompt": "specific visible action, setting, composition",
                        "character_ids": ["character_id"],
                        "source_beat": "which source beat this scene covers"}],
        },
    }
    return llm.generate(DRAFT_EPISODE_SYSTEM, prompt,
                        lambda data: validate_episode_plan(data, story))


def critic_review(draft_plan: dict, story: dict, llm) -> dict:
    """Stage 3: independent editorial review of the drafted episode.

    The critic did not write the draft. It returns a structured pass/reject assessment with
    specific reasons and actionable revision instructions. A story must not pass merely
    because its JSON is valid.
    """
    prompt = {
        "task": "story_critic",
        "story": {
            "title": story["title"], "synopsis": story["synopsis"],
            "ordered_key_beats": story["key_beats"], "source": story["source"],
        },
        "draft": {
            "title": draft_plan.get("title"),
            "logline": draft_plan.get("logline"),
            "narration": draft_plan.get("narration"),
            "scenes": [
                {"title": s.get("title"), "narration": s.get("narration"),
                 "source_beat": s.get("source_beat")}
                for s in draft_plan.get("scenes", [])
            ],
        },
        "schema": {
            "verdict": "'pass' or 'reject'",
            "reasons": ["specific reasons for rejection, empty when passing"],
            "assessment": {
                "hook": {"verdict": "strong/weak", "comment": "evidence"},
                "clarity": {"verdict": "clear/unclear", "comment": "evidence"},
                "motivation": {"verdict": "clear/unclear", "comment": "evidence"},
                "stakes": {"verdict": "high/low", "comment": "evidence"},
                "pacing": {"verdict": "well-paced/rushed/dragged", "comment": "evidence"},
                "dialogue": {"verdict": "natural/stilted", "comment": "evidence"},
                "emotional": {"verdict": "engaging/flat", "comment": "evidence"},
                "accuracy": {"verdict": "accurate/inaccurate", "comment": "evidence"},
                "omissions": {"verdict": "none/missing", "comment": "evidence"},
                "payoff": {"verdict": "satisfying/weak", "comment": "evidence"},
            },
            "revision_instructions": ["actionable revision instructions, empty when passing"],
        },
    }
    return llm.generate(CRITIC_SYSTEM, prompt, validate_critic_assessment)


def revise_episode(draft_plan: dict, assessment: dict, story: dict, llm) -> dict:
    """Stage 4: revise the draft according to the critic's specific instructions."""
    prompt = {
        "task": "revise_episode",
        "story": {
            "title": story["title"], "synopsis": story["synopsis"],
            "ordered_key_beats": story["key_beats"], "source": story["source"],
        },
        "draft": draft_plan,
        "critic_reasons": assessment.get("reasons", []),
        "revision_instructions": assessment.get("revision_instructions", []),
        "requirements": {
            "scene_count": "variable; one scene per narrative moment the story needs",
            "style": "natural spoken oral storytelling; one continuous performance",
            "guardrails": [
                "Apply each revision instruction directly.",
                "Preserve the cited edition's ending and essential source beats.",
                "Do not omit important events or introduce new subplots.",
                "Every visual prompt must depict the action narrated in that same scene.",
            ],
        },
        "schema": {
            "title": "episode title",
            "logline": "one-sentence premise",
            "characters": [{"id": "short_id", "name": "character name",
                            "role": "story role", "visual_identity": "consistent visual appearance"}],
            "scenes": [{"title": "scene label",
                        "narration": "spoken storyteller text",
                        "visual_prompt": "specific visible action, setting, composition",
                        "character_ids": ["character_id"],
                        "source_beat": "which source beat this scene covers"}],
        },
    }
    return llm.generate(REVISE_EPISODE_SYSTEM, prompt,
                        lambda data: validate_episode_plan(data, story))


def generate_episode(story: dict, llm) -> dict:
    """Run the full source-led story engine with an independent critic gate.

    Stages: source analysis -> draft -> critic review -> (optional revise -> re-review).
    Image generation must not begin until the story passes the critic.
    """
    max_revisions = int(os.environ.get("FAIRYTALE_MAX_REVISIONS", "2"))
    source_analysis = analyze_source(story, llm)
    draft = draft_episode(story, source_analysis, llm)
    assessment = critic_review(draft, story, llm)
    revisions = 0
    while assessment["verdict"] == "reject":
        if revisions >= max_revisions:
            raise ValueError(
                f"Story '{story['title']}' failed editorial review after {max_revisions} "
                f"revision attempts: {'; '.join(assessment['reasons'])}"
            )
        draft = revise_episode(draft, assessment, story, llm)
        assessment = critic_review(draft, story, llm)
        revisions += 1
    if assessment["verdict"] != "pass":
        raise ValueError(f"Story '{story['title']}' did not pass editorial review")
    return draft


def record_success(state: dict, story: dict, episode_date: str, run_id: str) -> dict:
    state = dict(state or initial_state())
    ids = list(state.get("completed_story_ids", []))
    if story["id"] not in ids:
        ids.append(story["id"])
    completed = list(state.get("completed", []))
    completed.append({"story_id": story["id"], "title": story["title"],
                      "episode_date": episode_date, "run_id": run_id,
                      "cycle": state.get("cycle", 1),
                      "completed_at": datetime.now(timezone.utc).isoformat()})
    return {"schema_version": 1, "cycle": state.get("cycle", 1),
            "completed_story_ids": ids, "last_story_id": story["id"],
            "completed": completed[-120:]}
