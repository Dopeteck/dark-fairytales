"""Tests for visual quality control."""
import io
import unittest
from pathlib import Path

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "destination-prototype"))
from visual_qa import technical_checks, review_image, semantic_flags
from shot_planner import build_shot_plan

ROOT = Path(__file__).resolve().parents[1]


def _make_image_bytes(size=(832, 1472), color=(40, 50, 60), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _blank_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (832, 1472), (0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class VisualQATests(unittest.TestCase):
    def test_technical_checks_accept_valid_portrait_image(self):
        problems = technical_checks(_make_image_bytes())
        self.assertEqual(problems, [])

    def test_technical_checks_reject_blank_and_wrong_ratio(self):
        self.assertIn("blank image", technical_checks(_blank_bytes()))
        wide = io.BytesIO()
        Image.new("RGB", (1472, 832), (10, 20, 30)).save(wide, format="PNG")
        self.assertTrue(any("not portrait" in p for p in technical_checks(wide.getvalue())))
        tiny = io.BytesIO()
        Image.new("RGB", (100, 100), (10, 20, 30)).save(tiny, format="PNG")
        self.assertTrue(any("too small" in p for p in technical_checks(tiny.getvalue())))

    def test_review_image_passes_valid_technically_sound_shot(self):
        plan = build_shot_plan({
            "title": "T", "story_id": "t", "source": {},
            "visual_style": "style",
            "characters": [{"id": "hero", "name": "Mira", "role": "heroine",
                            "visual_identity": "A woman in a green cloak."}],
            "scenes": [{"id": "scene-01", "title": "S",
                        "narration": "Mira left her village at dawn.",
                        "character_ids": ["hero"]}],
        })
        shot = plan["shots"][0]
        result = review_image(_make_image_bytes(), shot)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["technical"], [])

    def test_review_image_fails_blank_image(self):
        plan = build_shot_plan({
            "title": "T", "story_id": "t", "source": {},
            "visual_style": "style",
            "characters": [],
            "scenes": [{"id": "scene-01", "title": "S",
                        "narration": "Mira left her village at dawn.",
                        "character_ids": []}],
        })
        shot = plan["shots"][0]
        result = review_image(_blank_bytes(), shot)
        self.assertEqual(result["status"], "fail")
        self.assertIn("blank image", result["technical"])

    def test_review_image_flags_semantic_issues_for_human_review(self):
        plan = build_shot_plan({
            "title": "T", "story_id": "t", "source": {},
            "visual_style": "style",
            "characters": [],
            "scenes": [{"id": "scene-01", "title": "S",
                        "narration": "",
                        "character_ids": []}],
        })
        shot = plan["shots"][0]
        result = review_image(_make_image_bytes(), shot)
        self.assertEqual(result["status"], "review_needed")
        self.assertEqual(result["technical"], [])
        self.assertGreater(len(result["semantic"]), 0)

    def test_semantic_flags_unrecognized_shot_type(self):
        flags = semantic_flags({"shot_type": "not_a_shot", "narration": "x",
                                "character_ids": ["hero"]})
        self.assertTrue(any("unrecognized" in f for f in flags))


if __name__ == "__main__":
    unittest.main()
