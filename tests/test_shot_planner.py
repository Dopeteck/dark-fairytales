"""Tests for cinematic shot planning and the visual bible."""
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "destination-prototype"))
from shot_planner import build_shot_plan, shot_prompt, shot_quality_flags, SHOT_TYPES

ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return {
        "title": "The Hidden Path",
        "story_id": "test-tale",
        "source": {"title": "Test Collection", "author": "Traditional",
                   "url": "https://www.gutenberg.org/ebooks/11027",
                   "edition_note": "Test edition."},
        "visual_style": "Dark European fairy-tale storybook, painterly cinematic realism.",
        "characters": [
            {"id": "hero", "name": "Mira", "role": "heroine",
             "visual_identity": "Young woman with a green cloak and long dark braid."},
            {"id": "helper", "name": "Rowan", "role": "helper",
             "visual_identity": "Elderly traveller with a grey beard and brown coat."},
        ],
        "scenes": [
            {"id": "scene-01", "title": "The departure",
             "narration": "Mira left her village before sunrise, carrying one small bag.",
             "character_ids": ["hero"]},
            {"id": "scene-02", "title": "The warning",
             "narration": "An elderly traveller stepped out and warned her of the creature.",
             "character_ids": ["hero", "helper"]},
            {"id": "scene-03", "title": "The confrontation",
             "narration": "The creature blocked the bridge with a roar.",
             "character_ids": ["hero"]},
            {"id": "scene-04", "title": "The resolution",
             "narration": "Mira crossed the bridge and returned home safely.",
             "character_ids": ["hero"]},
        ],
    }


class ShotPlannerTests(unittest.TestCase):
    def test_shot_plan_covers_every_scene_with_varied_coverage(self):
        plan = build_shot_plan(_plan())
        self.assertEqual(plan["shot_count"], 4)
        shot_types = [shot["shot_type"] for shot in plan["shots"]]
        self.assertEqual(shot_types[0], "establishing")
        self.assertEqual(shot_types[-1], "reveal")
        self.assertTrue(all(t in SHOT_TYPES for t in shot_types))

    def test_shot_plan_assigns_bible_to_every_shot(self):
        plan = build_shot_plan(_plan())
        self.assertEqual(set(plan["characters"]), {"hero", "helper"})
        for shot in plan["shots"]:
            if shot["character_ids"]:
                for cid in shot["character_ids"]:
                    self.assertIn(cid, plan["characters"])

    def test_shot_prompt_includes_framing_and_bible(self):
        plan = build_shot_plan(_plan())
        shot = plan["shots"][1]
        prompt = shot_prompt(shot, plan["characters"], plan["visual_style"], "No lettering.")
        self.assertIn(shot["framing"], prompt)
        self.assertIn("Mira", prompt)
        self.assertIn("green cloak", prompt)
        self.assertIn("No lettering", prompt)

    def test_shot_plan_respects_budget(self):
        plan = build_shot_plan(_plan(), budget=2)
        self.assertEqual(plan["shot_budget"], 2)

    def test_shot_quality_flags_missing_narration(self):
        plan = build_shot_plan(_plan())
        shot = dict(plan["shots"][0])
        shot["narration"] = ""
        flags = shot_quality_flags(shot)
        self.assertTrue(any("narration" in flag for flag in flags))


if __name__ == "__main__":
    unittest.main()
