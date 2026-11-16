#!/usr/bin/env python3
"""Run one complete private daily dark-fairytale episode.

A queue item is marked complete only after all eight images, the MP4, captions,
metadata, and review disclosure pass validation. No approval or publishing occurs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from datetime import date

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "destination-prototype"))

from fairytale_planner import (
    EditorialRejectionError,
    generate_episode, initial_state, load_queue, next_story, record_success,
)
from llm import JsonLLM, StageError
from story_store import write_json
from generate_fairytale_scenes import run as generate_scenes
from render_fairytale_video import render
from episode_qa import review_episode


def _read_state(path: Path) -> dict:
    if not path.exists():
        return initial_state()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported fairytale rotation state")
    return value


def _repository_relative(path: Path) -> str:
    """Return a repository-relative path for a generated review artifact.

    The workflow may pass a relative output_root while ROOT is absolute, so both
    sides are resolved to the same absolute basis before relative_to is used.
    The exception is never suppressed: a missing or unresolvable path surfaces
    as a clear error so the summary always contains valid, portable paths.
    """
    resolved = path.resolve()
    root = ROOT.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError as exc:
        raise ValueError(
            f"Review artifact is outside the repository root and cannot be "
            f"referenced portably: {path} (resolved {resolved}, root {root})"
        ) from exc


def _collect_editorial_diagnostics(selected: dict, draft: dict | None,
                                   source_analysis: dict | None = None,
                                   assessments: list[dict] | None = None,
                                   revision_history: list[dict] | None = None,
                                   story: dict | None = None,
                                   episode_key: str | None = None) -> dict:
    """Collect the editorial diagnostic package for auditability.

    Includes the selected story, source edition, source analysis, initial
    draft, every critic assessment and its reasons, revision history, and
    the final rejection explanation. No secrets are included.
    """
    story_obj = story or selected
    return {
        "episode_key": episode_key,
        "story_id": story_obj.get("id"),
        "story_title": story_obj.get("title"),
        "source_edition": story_obj.get("source"),
        "synopsis": story_obj.get("synopsis"),
        "key_beats": story_obj.get("key_beats", []),
        "source_analysis": source_analysis,
        "initial_draft": draft,
        "critic_assessments": assessments or [],
        "revision_history": revision_history or [],
        "final_rejection_explanation": (
            assessments[-1].get("reasons", []) if assessments else []
        ),
    }


def _save_diagnostic_package(episode_dir: Path, review_dir: Path,
                             selected: dict, draft: dict | None,
                             editorial_diagnostics: dict | None = None,
                             provider_error: str | None = None,
                             stage: str = "unknown") -> None:
    """Persist a private diagnostic package so a failed or rejected episode
    remains inspectable. Never includes API keys or secrets."""
    review_dir.mkdir(parents=True, exist_ok=True)
    diag = dict(editorial_diagnostics or {})
    diag["failure_stage"] = stage
    diag["failure_type"] = "provider_technical" if provider_error else "editorial"
    diag["provider_error"] = provider_error
    diag["selected_story"] = {
        "id": selected.get("id"),
        "title": selected.get("title"),
        "source": selected.get("source"),
    }
    if draft:
        diag["final_draft_title"] = draft.get("title")
        diag["final_draft_narration_word_count"] = draft.get("narration_word_count")
        diag["final_draft_scene_count"] = len(draft.get("scenes", []))
    write_json(review_dir / "diagnostic-package.json", diag)
    # Also save a machine-readable failure marker for the workflow.
    write_json(review_dir / "failure-marker.json", {
        "stage": stage,
        "type": diag["failure_type"],
        "provider_error": provider_error,
        "story_id": selected.get("id"),
    })


def run(queue_path: Path, state_path: Path, output_root: Path,
        voice: str = "bm_fable", speed: float = 0.92,
        env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = env.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not api_token:
        raise RuntimeError("Missing Cloudflare Workers AI secrets; no images were generated.")
    if not any(env.get(key, "").strip() for key in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"
    )):
        raise RuntimeError("Missing a script provider secret (GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY).")

    queue = load_queue(queue_path)
    state = _read_state(state_path)
    selected, pending_state = next_story(queue, state)

    episode_date = env.get("EPISODE_DATE", date.today().isoformat())
    run_id = env.get("GITHUB_RUN_ID", "manual")
    run_attempt = env.get("GITHUB_RUN_ATTEMPT", "1")
    episode_key = f"{episode_date}-{selected['id']}-run-{run_id}-{run_attempt}"
    episode_dir = output_root / episode_key
    if episode_dir.exists() and any(episode_dir.iterdir()):
        raise RuntimeError(f"Episode output already exists: {episode_dir}; use a fresh workflow run.")
    episode_dir.mkdir(parents=True, exist_ok=True)
    image_dir = episode_dir / "scenes"
    review_dir = episode_dir / "review"

    stage = "selection"
    editorial_diagnostics: dict | None = None
    provider_error: str | None = None
    try:
        llm = JsonLLM(
            cache_dir=ROOT / "work" / "fairytale-plan-cache",
            draft_cache_dir=ROOT / "work" / "fairytale-plan-progress",
        )
        stage = "story_planning"
        plan = generate_episode(selected, llm)
        plan_path = episode_dir / "episode-plan.json"
        write_json(plan_path, plan)

        print(f"Selected tale: {selected['title']} ({selected['id']})")
        print(f"Source edition: {selected['source']['title']} — {selected['source']['url']}")
        print(f"Validated narration: {plan['narration_word_count']} words in {len(plan['scenes'])} scenes")

        stage = "image_generation"
        manifest = generate_scenes(
            plan_path=plan_path,
            output_dir=image_dir,
            account_id=account_id,
            api_token=api_token,
            pause_seconds=1.0,
            resume=False,
        )
        if manifest.get("approved") is not False or manifest.get("published") is not False:
            raise ValueError("Generated image manifest must remain unapproved and unpublished.")
        if manifest.get("scene_count") != len(plan["scenes"]):
            raise ValueError(
                f"Image generation produced {manifest.get('scene_count')} images but the "
                f"story plan has {len(plan['scenes'])} scenes."
            )

        stage = "render"
        video_path, metadata = render(
            plan_path=plan_path,
            images_dir=image_dir,
            output_dir=review_dir,
            voice=voice,
            speed=speed,
        )
        if not video_path.is_file() or video_path.stat().st_size < 100_000:
            raise ValueError("Rendered MP4 is missing or unexpectedly small.")
        if metadata.get("scene_count") != len(plan["scenes"]):
            raise ValueError(
                f"Rendered metadata contains {metadata.get('scene_count')} scenes but the "
                f"story plan has {len(plan['scenes'])} scenes."
            )
        if metadata.get("chapter_overlays") is not False:
            raise ValueError("Chapter banners must remain disabled.")
        if metadata.get("opening") != "full_bleed_scene_one_no_title_overlay":
            raise ValueError("The video must open on the first full-bleed scene without a title card")
        if metadata.get("narration_word_count") != plan["narration_word_count"]:
            raise ValueError("Rendered narration word count differs from the validated story plan.")
        if metadata.get("approved") is not False or metadata.get("published") is not False:
            raise ValueError("Rendered preview must remain unapproved and unpublished.")
        duration = float(metadata.get("duration_seconds", 0))
        if duration <= 0 or duration > 600:
            raise ValueError(f"Rendered runtime is not a valid short-form duration: {duration:.2f}s")
        if not 45 <= duration <= 150:
            print(f"Note: rendered runtime {duration:.2f}s is outside the 45–150s soft review band; "
                  "keeping the story's natural spoken duration.")

        stage = "review_package"
        captions_path = review_dir / "captions.srt"
        captions = captions_path.read_text(encoding="utf-8")
        if not captions.strip() or "\\n" in captions:
            raise ValueError("SRT captions are missing or contain literal escaped newline text.")
        if not (review_dir / "contact-sheet.jpg").is_file():
            raise ValueError("Missing review contact sheet.")
    except StageError as exc:
        # Provider / technical failure: never an editorial revision. Preserve
        # every diagnostic artifact and report the failed stage without secrets.
        provider_error = (
            f"Provider {exc.provider or 'unknown'}"
            + (f" model {exc.model}" if exc.model else "")
            + (f": HTTP {exc.status}" if exc.status else "")
            + f" — {exc}"
        )
        _save_diagnostic_package(
            episode_dir, review_dir, selected, plan if 'plan' in locals() else None,
            editorial_diagnostics, provider_error=provider_error, stage=exc.stage,
        )
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        raise RuntimeError(f"fairytale pipeline failed at stage '{exc.stage}' (provider/technical): {message}") from exc
    except EditorialRejectionError as exc:
        # Editorial rejection: preserve the full diagnostic package (source
        # analysis, draft, every critic assessment, revision history) so the
        # rejection can be audited. Do not mark the story complete.
        editorial_diagnostics = _collect_editorial_diagnostics(
            selected, exc.draft, exc.source_analysis, exc.assessments,
            exc.revision_history, exc.story, episode_key,
        )
        _save_diagnostic_package(
            episode_dir, review_dir, selected, exc.draft, editorial_diagnostics,
            provider_error=provider_error,
        )
        raise RuntimeError(
            f"fairytale pipeline failed at stage '{stage}' (editorial rejection): {exc}"
        ) from exc
    except ValueError as exc:
        # Could be a QA gate failure or other editorial issue. Preserve
        # diagnostics; do not mark the story complete.
        if editorial_diagnostics is None:
            editorial_diagnostics = _collect_editorial_diagnostics(
                selected, plan if 'plan' in locals() else None,
                episode_key=episode_key,
            )
        _save_diagnostic_package(
            episode_dir, review_dir, selected,
            plan if 'plan' in locals() else None,
            editorial_diagnostics,
            provider_error=provider_error,
        )
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        raise RuntimeError(f"fairytale pipeline failed at stage '{stage}': {message}") from exc

    summary = {
        "status": "private_review_ready",
        "story_id": selected["id"],
        "title": plan["title"],
        "episode_date": episode_date,
        "run_id": str(run_id),
        "run_attempt": str(run_attempt),
        "episode_key": episode_key,
        "source": plan["source"],
        "video": _repository_relative(video_path),
        "contact_sheet": _repository_relative(review_dir / "contact-sheet.jpg"),
        "captions": _repository_relative(captions_path),
        "duration_seconds": metadata["duration_seconds"],
        "resolution": metadata["resolution"],
        "fps": metadata["fps"],
        "narration_word_count": plan["narration_word_count"],
        "image_count": manifest["scene_count"],
        "voice": metadata["voice"],
        "chapter_overlays": False,
        "preview_only": True,
        "approved": False,
        "published": False,
        "disclosure": plan["disclosure"],
    }
    write_json(episode_dir / "review-summary.json", summary)

    # Persist traceability artifacts for human review.
    shot_plan = manifest.get("shot_plan")
    if shot_plan:
        write_json(review_dir / "shot-plan.json", shot_plan)
    character_bible = shot_plan.get("characters") if shot_plan else None
    if character_bible:
        write_json(review_dir / "character-bible.json", character_bible)
    visual_qa_report = {
        "episode_key": episode_key,
        "story_id": selected["id"],
        "run_id": str(run_id),
        "run_attempt": str(run_attempt),
        "images": [
            {
                "scene_id": row.get("scene_id"),
                "file": row.get("file"),
                "quality_status": row.get("quality_status"),
                "quality_technical": row.get("quality_technical"),
                "quality_semantic": row.get("quality_semantic"),
                "shot_type": row.get("shot_type"),
                "shot_framing": row.get("shot_framing"),
            }
            for row in manifest.get("images", [])
        ],
    }
    write_json(review_dir / "visual-qa-report.json", visual_qa_report)

    qa_report = review_episode(episode_dir, plan, manifest, metadata)
    if not qa_report["review_ready"]:
        # Do not mark the episode complete; preserve every partial output so the
        # failure is inspectable. Surface concrete weaknesses, never secrets.
        raise ValueError(
            "Episode failed quality-assurance gates: "
            + "; ".join(qa_report["weaknesses"] or [qa_report["checks"]])
        )
    qa_report["episode_key"] = episode_key
    qa_report["run_id"] = str(run_id)
    qa_report["run_attempt"] = str(run_attempt)
    summary["qa_report"] = qa_report
    write_json(episode_dir / "review-summary.json", summary)

    # Persist the final, critic-approved plan with editorial provenance.
    write_json(plan_path, plan)
    write_json(review_dir / "episode-plan.json", plan)

    completed_state = record_success(pending_state, selected, episode_date, str(run_id))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, completed_state)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=ROOT / "fairytale_queue.json")
    parser.add_argument("--state", type=Path, default=ROOT / "state" / "fairytale_rotation.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "daily-fairytales")
    parser.add_argument("--voice", choices=("bm_fable", "bm_george", "am_michael"), default="bm_fable")
    parser.add_argument("--speed", type=float, default=0.92)
    args = parser.parse_args()
    run(args.queue, args.state, args.output, args.voice, args.speed)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        print("Daily fairytale failed safely: " + message, file=sys.stderr)
        raise SystemExit(1)
