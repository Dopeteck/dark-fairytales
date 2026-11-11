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

    def test_unknown_scene_fails_closed(self):
        with self.assertRaises(ValueError):
            generator.build_prompt({"id": "unknown-beat"}, 1)

    def test_cloudflare_image_response_is_decoded(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        data = generator.generate_one("a fairytale scene", "account", "token", 42, session=session)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertIn("/ai/run/@cf/black-forest-labs/flux-1-schnell", args[0])
        self.assertEqual(kwargs["json"]["seed"], 42)
        self.assertEqual(kwargs["json"]["steps"], 4)

    def test_http_errors_are_clear(self):
        response = Mock(status_code=429, text="rate limited")
        session = Mock()
        session.post.return_value = response
        with self.assertRaisesRegex(RuntimeError, "rate limit"):
            generator.generate_one("prompt", "account", "token", 1, session=session)

    def test_run_writes_verified_unapproved_scene_files_and_manifest(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        original = generator.generate_one
        generator.generate_one = lambda prompt, account_id, api_token, seed, steps=4: original(
            prompt, account_id, api_token, seed, steps, session=session
        )
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                plan_path = root / "plan.json"
                plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
                out = root / "images"
                manifest = generator.run(plan_path, out, "account", "token", pause_seconds=0)
                self.assertEqual(manifest["scene_count"], 2)
                self.assertFalse(manifest["approved"])
                self.assertFalse(manifest["rendered"])
                self.assertTrue((out / "01-beat-01-threat.jpg").is_file())
                self.assertTrue((out / "02-beat-08-forest-fire.jpg").is_file())
                saved = json.loads((out / "generation-manifest.json").read_text())
                self.assertEqual(saved["scene_count"], 2)
                self.assertTrue(all(not item["approved"] for item in saved["images"]))
        finally:
            generator.generate_one = original


if __name__ == "__main__":
    unittest.main()
