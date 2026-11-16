"""Tests for the end-of-pipeline episode QA gates."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "destination-prototype"))
from episode_qa import review_episode as review_qa


def _write_image(path: Path, size=(832, 1472)) -> bytes:
    image = Image.new("RGB", size, (40, 50, 60))
    data = io.BytesIO()
    image.save(data, format="PNG")
    path.write_bytes(data.getvalue())
    return data.getvalue()


def _base_plan(scenes_count=3):
    scenes = []
    for i in range(scenes_count):
        scenes.append({
            "id": f"scene-{i + 1:02d}", "title": f"Scene {i + 1}",
            "narration": f"This is the narration for scene {i + 1}. It has several words.",
            "character_ids": ["hero"],
        })
    return {
        "title": "Test Tale", "story_id": "test-tale",
        "narration": "\n\n".join(s["narration"] for s in scenes),
        "narration_word_count": sum(len(s["narration"].split()) for s in scenes),
        "scenes": scenes,
        "disclosure": "An AI-illustrated dramatic retelling based on the cited source.",
        "approved": False, "published": False,
        "source_analysis": {
            "central_conflict": "A central want meets an obstacle.",
            "resolution": "The heroine reaches safety.",
            "characters": [],
            "key_reversals": [],
            "climax": "The climax.",
            "tone": "Folkloric.",
            "essential_beats": ["beat 1", "beat 2"],
        },
        "critic_assessment": {
            "verdict": "pass",
            "reasons": [],
            "story_id": "test-tale",
            "generated_for_episode": "test-tale",
            "generated_at": "2026-11-15T00:00:00Z",
            "assessment": {
                "hook": {"verdict": "strong", "comment": "Opens inside the trouble."},
                "clarity": {"verdict": "clear", "comment": "Narrative is easy to follow."},
                "motivation": {"verdict": "clear", "comment": "Character wants are evident."},
                "stakes": {"verdict": "high", "comment": "Safety is at stake."},
                "pacing": {"verdict": "well-paced", "comment": "Escalation is steady."},
                "dialogue": {"verdict": "natural", "comment": "Dialogue sounds spoken."},
                "emotional": {"verdict": "engaging", "comment": "Emotional beats land."},
                "accuracy": {"verdict": "accurate", "comment": "Follows the source edition."},
                "omissions": {"verdict": "none", "comment": "No essential beats omitted."},
                "payoff": {"verdict": "satisfying", "comment": "Ending delivers a payoff."},
            },
            "revision_instructions": [],
        },
        "editorial_gate": {
            "verdict": "pass",
            "story_id": "test-tale",
            "critic_verdict": "pass",
            "source_analysis_complete": True,
            "criteria_count": 10,
            "revision_count": 0,
            "gate_passed_at": "2026-11-15T00:00:00Z",
        },
    }


def _base_manifest(plan):
    images = []
    for i, scene in enumerate(plan["scenes"]):
        images.append({
            "scene_id": scene["id"], "title": scene["title"],
            "file": f"{i + 1:02d}-{scene['id']}.png",
            "width": 832, "height": 1472, "format": "PNG",
            "quality_status": "pass", "quality_technical": [], "quality_semantic": [],
        })
    return {"scene_count": len(images), "images": images}


def _base_metadata(plan):
    return {"scene_count": len(plan["scenes"]), "chapter_overlays": False,
            "opening": "full_bleed_scene_one_no_title_overlay",
            "voice": "bm_fable", "duration_seconds": 60.0,
            "approved": False, "published": False}


class EpisodeQATests(unittest.TestCase):
    def setUp(self):
        self._patcher = patch("episode_qa.subprocess.run")
        self._mock_run = self._patcher.start()
        self._mock_run.return_value.returncode = 0
        self._mock_run.return_value.stdout = json.dumps({"streams": [
            {"codec_type": "video"}, {"codec_type": "audio"}]})

    def tearDown(self):
        self._patcher.stop()

    def _episode_dir(self, plan=None, manifest=None, metadata=None,
                     with_video=True, with_captions=True):
        plan = plan or _base_plan()
        manifest = manifest or _base_manifest(plan)
        metadata = metadata or _base_metadata(plan)
        tmp = Path(tempfile.mkdtemp())
        review = tmp / "review"
        image_dir = tmp / "scenes"
        review.mkdir()
        image_dir.mkdir()
        (tmp / "episode-plan.json").write_text(json.dumps(plan))
        (review / "render-metadata.json").write_text(json.dumps(metadata))
        for row in manifest["images"]:
            _write_image(image_dir / row["file"])
        (review / "generation-manifest.json").write_text(json.dumps(manifest))
        if with_video:
            (review / "video.mp4").write_bytes(b"\x00\x00" * 60000)
        if with_captions:
            (review / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n\n", encoding="utf-8")
        (review / "contact-sheet.jpg").write_bytes(b"sheet")
        (review / "review-summary.json").write_text(
            json.dumps({"status": "private_review_ready", "approved": False, "published": False}))
        return tmp, plan, manifest, metadata

    def test_all_gates_pass_makes_episode_review_ready(self):
        root, plan, manifest, metadata = self._episode_dir()
        report = review_qa(root, plan, manifest, metadata)
        self.assertTrue(report["review_ready"])
        self.assertFalse(report["approved"])
        self.assertFalse(report["published"])
        self.assertEqual(report["weaknesses"], [])

    def test_missing_image_fails_shots_have_images(self):
        root, plan, manifest, metadata = self._episode_dir()
        manifest["images"].pop()
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("shots_have_images" in w or "Missing images" in w
                            for w in report["weaknesses"]))

    def test_blank_image_fails_images_pass_checks(self):
        root, plan, manifest, metadata = self._episode_dir()
        image_dir = root / "scenes"
        blank = Image.new("RGB", (832, 1472), (0, 0, 0))
        blank.save(image_dir / "01-scene-01.png")
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("failed technical checks" in w for w in report["weaknesses"]))

    def test_approval_or_publication_true_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["approved"] = True
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("Approval status must remain false" in w
                            for w in report["weaknesses"]))

    def test_missing_disclosure_is_a_weakness(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["disclosure"] = "Just a regular story."
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("Disclosure" in w for w in report["weaknesses"]))

    # --- Editorial critic provenance gates ---

    def test_missing_source_analysis_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        del plan["source_analysis"]
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("source_analysis_exists" in w or "No source analysis" in w
                            for w in report["weaknesses"]))

    def test_missing_critic_assessment_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        del plan["critic_assessment"]
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("critic_assessment_exists" in w or "No editorial critic" in w
                            for w in report["weaknesses"]))

    def test_rejected_critic_verdict_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["critic_assessment"]["verdict"] = "reject"
        plan["critic_assessment"]["reasons"] = ["Weak hook", "Unclear motivation"]
        plan["editorial_gate"]["verdict"] = "reject"
        plan["editorial_gate"]["critic_verdict"] = "reject"
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("critic_verdict_pass" in w or "not 'pass'" in w
                            for w in report["weaknesses"]))

    def test_malformed_critic_assessment_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["critic_assessment"] = "not-a-dict"
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("No editorial critic" in w for w in report["weaknesses"]))

    def test_missing_critic_criteria_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["critic_assessment"]["assessment"] = {
            "hook": {"verdict": "strong", "comment": "Good hook."},
        }
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("critic_criteria_complete" in w or "Missing or empty" in w
                            for w in report["weaknesses"]))

    def test_empty_critic_criterion_comment_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["critic_assessment"]["assessment"]["payoff"] = {"verdict": "satisfying", "comment": ""}
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("Missing or empty" in w for w in report["weaknesses"]))

    def test_stale_critic_assessment_different_story_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["critic_assessment"]["story_id"] = "other-story"
        plan["critic_assessment"]["generated_for_episode"] = "other-story"
        plan["editorial_gate"]["story_id"] = "other-story"
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("stale or mismatched" in w or "inconsistent with the plan" in w
                            for w in report["weaknesses"]))

    def test_editorial_gate_inconsistent_fails(self):
        root, plan, manifest, metadata = self._episode_dir()
        plan["editorial_gate"]["verdict"] = "fail"
        report = review_qa(root, plan, manifest, metadata)
        self.assertFalse(report["review_ready"])
        self.assertTrue(any("inconsistent with the plan" in w for w in report["weaknesses"]))

    def test_valid_passing_assessment_passes(self):
        root, plan, manifest, metadata = self._episode_dir()
        report = review_qa(root, plan, manifest, metadata)
        self.assertTrue(report["review_ready"])
        self.assertFalse(report["approved"])
        self.assertFalse(report["published"])
        self.assertEqual(report["weaknesses"], [])


if __name__ == "__main__":
    unittest.main()
