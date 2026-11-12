import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "destination-prototype"))
import generate_fairytale_scenes as generator


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "title": "Rumpelstiltskin: The Price of a Promise",
            "scenes": [
                {"id": "beat-01-threat", "title": "A threat before the magic",
                 "narration": "Spin straw into gold by morning."},
                {"id": "beat-05-child-pact", "title": "The child pact",
                 "narration": "She bargains away her first child."},
                {"id": "beat-08-forest-fire", "title": "A dance in the forest",
                 "narration": "A messenger finds him dancing by a fire."},
            ],
        }
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), (12, 34, 56)).save(buffer, format="JPEG")
        self.image_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    def test_prompt_contains_shared_style_and_scene_direction(self):
        prompt = generator.build_prompt(self.plan["scenes"][0], 1)
        self.assertIn("same young adult woman", prompt)
        self.assertIn("vast stone chamber piled high", prompt)
        self.assertIn("No text", prompt)
        self.assertLessEqual(len(prompt), 2048)

    def test_rumpelstiltskin_prompt_makes_his_small_scale_mandatory(self):
        prompt = generator.build_prompt(self.plan["scenes"][1], 5)
        for required in (
            "ADULT MALE dwarf",
            "60 cm",
            "reaches ONLY her hip",
            "2.5 times taller",
            "full-body",
            "tiny bowed bandy legs",
            "long white beard",
            "bulbous fiery-red nose",
            "tall red pointed cap",
            "deep-blue tunic",
            "ochre breeches",
            "never a woman",
            "never a woman, child",
        ):
            self.assertIn(required, prompt)
        self.assertLessEqual(len(prompt), 2048)

    def test_character_lock_is_only_added_to_scenes_where_he_appears(self):
        queen_scene = {"id": "beat-07-three-days", "title": "Three days to name him"}
        prompt = generator.build_prompt(queen_scene, 7)
        self.assertNotIn("RUMPELSTILTSKIN: tiny", prompt)
        self.assertNotIn("2.5 times taller", prompt)

    def test_every_character_appearance_uses_the_same_scale_and_costume_lock(self):
        expected = {
            "beat-03-first-bargains",
            "beat-05-child-pact",
            "beat-06-claim",
            "beat-08-forest-fire",
            "beat-09-foot-revelation",
        }
        self.assertEqual(generator.RUMPELSTILTSKIN_SCENES, expected)
        for index, scene_id in enumerate(sorted(expected), 1):
            prompt = generator.build_prompt({"id": scene_id, "title": scene_id}, index)
            self.assertIn("RUMPELSTILTSKIN: tiny", prompt)
            self.assertIn("60 cm", prompt)
            self.assertIn("long white beard", prompt)
            self.assertIn("tall red pointed cap", prompt)
            self.assertLessEqual(len(prompt), 2048)

    def test_unknown_scene_fails_closed(self):
        with self.assertRaises(ValueError):
            generator.build_prompt({"id": "unknown-beat"}, 1)

    def test_cloudflare_request_uses_only_supported_flux_inputs(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        data = generator.generate_one("a fairytale scene", "account", "token", steps=8, session=session)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertIn("/ai/run/@cf/black-forest-labs/flux-1-schnell", args[0])
        self.assertEqual(kwargs["json"], {"prompt": "a fairytale scene", "steps": 8})
        self.assertNotIn("seed", kwargs["json"])

    def test_http_errors_are_clear(self):
        response = Mock(status_code=429, text="rate limited")
        session = Mock()
        session.post.return_value = response
        with self.assertRaisesRegex(RuntimeError, "rate limit"):
            generator.generate_one("prompt", "account", "token", session=session)

    def test_run_writes_verified_unapproved_scene_files_and_manifest(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        original = generator.generate_one
        generator.generate_one = lambda prompt, account_id, api_token, steps=8: original(
            prompt, account_id, api_token, steps, session=session
        )
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                plan_path = root / "plan.json"
                plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
                out = root / "images"
                manifest = generator.run(plan_path, out, "account", "token", pause_seconds=0)
                self.assertEqual(manifest["scene_count"], 3)
                self.assertEqual(manifest["steps"], 8)
                self.assertFalse(manifest["approved"])
                self.assertFalse(manifest["rendered"])
                self.assertTrue((out / "01-beat-01-threat.jpg").is_file())
                self.assertTrue((out / "02-beat-05-child-pact.jpg").is_file())
                self.assertTrue((out / "03-beat-08-forest-fire.jpg").is_file())
                saved = json.loads((out / "generation-manifest.json").read_text())
                self.assertEqual(saved["scene_count"], 3)
                self.assertTrue(all(not item["approved"] for item in saved["images"]))
        finally:
            generator.generate_one = original


if __name__ == "__main__":
    unittest.main()
