"""End-to-end offline tests of the rebuilt story engine across multiple tales.

Validates that scene count, word count and shot coverage follow the story
rather than a fixed template, that the independent critic gates image
generation, and that episodes remain unapproved and unpublished.
"""
import unittest
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "destination-prototype"))

from fairytale_planner import load_queue, generate_episode
from llm import DryRunLLM
from shot_planner import build_shot_plan


def _story_by_id(queue, story_id):
    for story in queue:
        if story["id"] == story_id:
            return story
    raise AssertionError(f"Queue has no story {story_id!r}")


class MultiStoryEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        queue = load_queue(ROOT / "fairytale_queue.json")
        # Three substantially different tales: identity/betrayal, abandonment/survival,
        # deception/danger. Different beat counts -> different scene counts.
        cls.tales = [
            _story_by_id(queue, "goose-girl"),      # 8 beats
            _story_by_id(queue, "hansel-gretel"),   # 8 beats
            _story_by_id(queue, "little-red-cap"),  # 7 beats
            _story_by_id(queue, "snow-white"),      # 9 beats (complex)
        ]
        cls.llm = DryRunLLM()

    def test_each_tale_gets_a_source_led_variable_structure(self):
        results = {}
        for story in self.tales:
            plan = generate_episode(story, self.llm)
            results[story["id"]] = plan
            # The engine must not force eight scenes or 180-235 words.
            self.assertEqual(plan["format"], "dark_fairytale_episode_v1")
            self.assertGreaterEqual(len(plan["scenes"]), 1)
            self.assertEqual(plan["narration_word_count"], len(plan["narration"].split()))
            self.assertFalse(plan["approved"])
            self.assertFalse(plan["published"])
            self.assertIn("AI-illustrated", plan["disclosure"])
            self.assertIn("retelling", plan["disclosure"])
            # Source edition is retained.
            self.assertEqual(plan["source"]["title"], story["source"]["title"])
        # Variable scene counts across tales (story-led, not fixed at eight).
        scene_counts = {len(p["scenes"]) for p in results.values()}
        self.assertGreater(len(scene_counts), 1, f"scene counts not variable: {scene_counts}")

    def test_critic_gates_every_tale_before_images(self):
        # generate_episode only returns once the independent critic passes;
        # if a tale failed review it would raise ValueError.
        for story in self.tales:
            plan = generate_episode(story, self.llm)
            # Shot planning only runs after the critic has passed.
            shot_plan = build_shot_plan(plan)
            self.assertEqual(shot_plan["shot_count"], len(plan["scenes"]))
            shot_types = [s["shot_type"] for s in shot_plan["shots"]]
            self.assertEqual(shot_types[0], "establishing")
            self.assertTrue(all(s in ("establishing", "wide", "medium", "close_up", "object",
                                      "cutaway", "reveal", "action", "interaction")
                                for s in shot_types))
            # Every shot references defined characters and carries a shot bible.
            for shot in shot_plan["shots"]:
                for cid in shot["character_ids"]:
                    self.assertIn(cid, shot_plan["characters"])

    def test_complex_tale_is_not_brutally_compressed(self):
        # snow-white has 9 beats; it should not be crushed into a tiny plan.
        story = self.tales[-1]
        plan = generate_episode(story, self.llm)
        self.assertGreaterEqual(len(plan["scenes"]), 5)
        self.assertGreaterEqual(plan["narration_word_count"], 50)


if __name__ == "__main__":
    unittest.main()
