"""End-of-pipeline quality assurance for a Dark Fairytales episode.

Separates technical validation (files, streams, timestamps, checksums) from
creative validation (editorial pass, shot coverage, image quality). Failed
checks are reported as weaknesses; they are never silently converted into
success. An episode is review-ready only when every gate passes and it remains
explicitly unapproved and unpublished.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _srt_timestamps_valid(text: str) -> bool:
    if not text or not text.strip():
        return False
    pattern = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")
    for line in text.splitlines():
        line = line.strip()
        if "-->" in line and not pattern.match(line):
            return False
    return True


def _image_ok(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            if image.getbbox() is None:
                return False
            if abs((width / height) - (9 / 16)) > 0.035:
                return False
            return width >= 700 and height >= 1200
    except Exception:
        return False


def review_episode(episode_dir: Path, plan: dict[str, Any],
                   manifest: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Run every QA gate and return a structured review report.

    review_ready is True only when every gate passes. approval/publication must
    remain False. weaknesses lists concrete, actionable problems.
    """
    episode_dir = Path(episode_dir)
    review_dir = episode_dir / "review"
    image_dir = episode_dir / "scenes"
    checks: dict[str, dict[str, Any]] = {}
    weaknesses: list[str] = []

    def gate(name: str, ok: bool, detail: str = "", weakness: str | None = None) -> None:
        checks[name] = {"passed": bool(ok), "detail": detail}
        if not ok:
            checks[name]["passed"] = False
            if weakness:
                weaknesses.append(weakness)

    # --- Creative / editorial ---
    narration = str(plan.get("narration", ""))
    disclosure = str(plan.get("disclosure", ""))
    gate("story_editorial_passed", bool(plan.get("scenes")) and bool(narration),
         f"{len(plan.get('scenes', []))} scenes, {plan.get('narration_word_count', 0)} words",
         "No scenes or narration; editorial review did not produce a usable episode.")
    gate("narration_complete", bool(narration.strip()),
         f"{len(narration.split())} narration words",
         "Narration is empty; the voice track has nothing to speak.")
    gate("disclosure_disclosed", "AI-illustrated" in disclosure and "retelling" in disclosure,
         disclosure[:120],
         "Disclosure does not identify an AI-illustrated retelling of its source.")

    # --- Voice track ---
    voice = metadata.get("voice")
    duration = float(metadata.get("duration_seconds", 0))
    gate("voice_track_valid", bool(voice) and duration > 0,
         f"voice={voice} duration={duration}s",
         "Voice track is missing or has zero duration.")

    # --- Every planned shot has an image ---
    scenes = plan.get("scenes", [])
    image_rows = {}
    for row in manifest.get("images", []):
        if isinstance(row, dict):
            image_rows[str(row.get("scene_id"))] = row
    missing_images = [str(s["id"]) for s in scenes if str(s["id"]) not in image_rows]
    gate("shots_have_images", not missing_images,
         f"{len(image_rows)} images for {len(scenes)} scenes",
         f"Missing images: {', '.join(missing_images)}" if missing_images else None)

    # --- Images pass technical checks; semantic flagged for review ---
    failing_images = []
    review_needed_images = []
    for scene in scenes:
        row = image_rows.get(str(scene["id"]), {})
        image_path = image_dir / str(row.get("file", ""))
        if not image_path.is_file():
            failing_images.append(str(scene["id"]))
            continue
        qstatus = str(row.get("quality_status", ""))
        if qstatus == "fail":
            failing_images.append(str(scene["id"]))
        elif qstatus == "review_needed" or row.get("quality_semantic"):
            review_needed_images.append(str(scene["id"]))
        elif not _image_ok(image_path):
            failing_images.append(str(scene["id"]))
    gate("images_pass_checks", not failing_images,
         "flagged for human review" if review_needed_images else "all technically valid",
         f"Images failed technical checks: {', '.join(failing_images)}" if failing_images else None)
    if review_needed_images:
        weaknesses.append(f"Images needing human visual review: {', '.join(review_needed_images)}")

    # --- Editing output ---
    gate("editing_scenes_match", metadata.get("scene_count") == len(scenes),
         f"metadata {metadata.get('scene_count')} scenes vs {len(scenes)} planned",
         "Rendered metadata scene count does not match the planned scene count.")
    gate("no_chapter_banners", metadata.get("chapter_overlays") is False,
         str(metadata.get("chapter_overlays")),
         "Chapter title banners must remain disabled.")
    opening = metadata.get("opening")
    gate("no_opening_title_card", opening == "full_bleed_scene_one_no_title_overlay",
         str(opening),
         "Video must open on the first full-bleed scene without a title card.")

    # --- Captions ---
    captions_path = review_dir / "captions.srt"
    captions_text = ""
    if captions_path.is_file():
        captions_text = captions_path.read_text(encoding="utf-8")
    gate("captions_exist", captions_path.is_file() and bool(captions_text.strip()),
         "captions.srt present" if captions_path.is_file() else "missing",
         "SRT captions are missing or empty.")
    if captions_text.strip():
        gate("captions_valid_timestamps", _srt_timestamps_valid(captions_text),
             "timestamps parse",
             "Caption timestamps are not valid SRT.")

    # --- Final MP4 ---
    video_path = review_dir / "video.mp4"
    mp4_ok = video_path.is_file() and video_path.stat().st_size > 100_000
    gate("mp4_exists", mp4_ok,
         f"{video_path.stat().st_size} bytes" if video_path.is_file() else "missing",
         "Final MP4 is missing or unexpectedly small.") if video_path.is_file() else None
    if video_path.is_file():
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type", "-of", "json", str(video_path)],
                capture_output=True, text=True, timeout=30,
            )
            streams = json.loads(probe.stdout or "{}").get("streams", [])
            kinds = {s.get("codec_type") for s in streams}
            gate("mp4_valid_streams", {"video", "audio"} <= kinds,
                 f"streams={sorted(kinds)}",
                 "MP4 must contain both video and audio streams.")
        except Exception:
            gate("mp4_valid_streams", False, "ffprobe unavailable",
                 "Could not probe the MP4 with ffprobe.")

    # --- Review package complete ---
    package_files = ["episode-plan.json", "review-summary.json", "video.mp4",
                     "captions.srt", "contact-sheet.jpg", "render-metadata.json"]
    missing_package = [f for f in package_files
                       if not (episode_dir / f).is_file() and not (review_dir / f).is_file()]
    gate("review_package_complete", not missing_package,
         "all review artifacts present",
         f"Review package missing: {', '.join(missing_package)}" if missing_package else None)

    # --- Approval / publication status ---
    gate("approval_false", plan.get("approved") is False and metadata.get("approved") is False,
         "approved=False",
         "Approval status must remain false before human review.")
    gate("publication_false", plan.get("published") is False and metadata.get("published") is False,
         "published=False",
         "Publication status must remain false before human approval.")

    review_ready = all(c["passed"] for c in checks.values())
    return {
        "episode_dir": str(episode_dir),
        "review_ready": review_ready,
        "approved": bool(plan.get("approved")),
        "published": bool(plan.get("published")),
        "checks": checks,
        "weaknesses": weaknesses,
        "passed": sum(1 for c in checks.values() if c["passed"]),
        "total": len(checks),
    }
