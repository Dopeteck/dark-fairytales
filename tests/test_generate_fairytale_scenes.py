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
        self.image_bytes = buffer.getvalue()
        self.image_b64 = base64.b64encode(self.image_bytes).decode("ascii")

    def _reference_file(self, path: Path):
        Image.new("RGB", (510, 510), (90, 60, 35)).save(path, format="PNG")
        return path

    def test_prompt_contains_shared_style_and_scene_direction(self):
        prompt = generator.build_prompt(self.plan["scenes"][0], 1)
        self.assertIn("adult woman in her early twenties", prompt)
        self.assertIn("vast stone chamber piled high", prompt)
        self.assertIn("No lettering", prompt)
        self.assertLessEqual(len(prompt), 2048)

    def test_rumpelstiltskin_prompt_uses_identity_and_separate_scale_reference(self):
        prompt = generator.build_prompt(self.plan["scenes"][1], 5)
        for required in (
            "input image 0 is Rumpelstiltskin",
            "input image 1",
            "input image 1 shows ONLY the height scale",
            "60-centimetre",
            "reaches no higher than her KNEECAP",
            "adult woman",
            "white beard",
            "fiery-red nose",
            "pointed red cap",
            "blue tunic",
            "ochre breeches",
            "NOT a normal-sized man",
        ):
            self.assertIn(required.lower(), prompt.lower())
        self.assertIn("There is NO child in this scene", prompt)
        self.assertIn("Dark medieval European fairytale", prompt)
        self.assertIn("knee joint", prompt)
        self.assertNotIn("hip", prompt.lower())
        self.assertLessEqual(len(prompt), 2048)

    def test_forest_scene_requests_exactly_one_character(self):
        prompt = generator.build_prompt(self.plan["scenes"][2], 8)
        self.assertIn("Show exactly ONE person", prompt)
        self.assertIn("no second dwarf", prompt)

    def test_reference_lock_is_only_added_to_scenes_where_he_appears(self):
        queen_scene = {"id": "beat-07-three-days", "title": "Three days to name him"}
        prompt = generator.build_prompt(queen_scene, 7)
        self.assertNotIn("input image 0", prompt)
        self.assertNotIn("input image 1", prompt)
        self.assertNotIn("60-centimetre", prompt)

    def test_every_character_appearance_uses_both_reference_constraints(self):
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
            self.assertIn("input image 0 is Rumpelstiltskin", prompt)
            self.assertIn("input image 1", prompt)
            self.assertIn("60-centimetre", prompt)
            self.assertLessEqual(len(prompt), 2048)

    def test_unknown_scene_fails_closed(self):
        with self.assertRaises(ValueError):
            generator.build_prompt({"id": "unknown-beat"}, 1)

    def test_cloudflare_request_uses_two_reference_multipart_images(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        identity = b"identity-image-png"
        scale = b"scale-image-png"
        data = generator.generate_one(
            "a fairytale scene", "account", "token",
            reference_image=identity,
            scale_reference_image=scale,
            width=832, height=1472, session=session
        )
        self.assertTrue(data.startswith(b"\xff\xd8"))
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertIn("/ai/run/@cf/black-forest-labs/flux-2-klein-4b", args[0])
        file_fields = {name: value for name, value in kwargs["files"]}
        self.assertEqual(file_fields["prompt"], (None, "a fairytale scene"))
        self.assertEqual(file_fields["width"], (None, "832"))
        self.assertEqual(file_fields["height"], (None, "1472"))
        self.assertEqual(file_fields["input_image_0"][1], identity)
        self.assertEqual(file_fields["input_image_0"][2], "image/png")
        self.assertEqual(file_fields["input_image_1"][1], scale)
        self.assertEqual(file_fields["input_image_1"][2], "image/png")
        self.assertNotIn("seed", kwargs)

    def test_http_errors_are_clear(self):
        response = Mock(status_code=429, text="rate limited")
        session = Mock()
        session.post.return_value = response
        with self.assertRaisesRegex(RuntimeError, "rate limit"):
            generator.generate_one("prompt", "account", "token", session=session)

    def test_rumpel_scene_requires_two_valid_small_visual_references(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps({"scenes": [self.plan["scenes"][1]]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "visual identity reference"):
                generator.run(
                    plan_path, root / "out", "account", "token",
                    only_scene="beat-05-child-pact"
                )

            identity_path = self._reference_file(root / "identity.png")
            with self.assertRaisesRegex(ValueError, "height-scale reference"):
                generator.run(
                    plan_path, root / "out", "account", "token",
                    reference_image_path=identity_path,
                    only_scene="beat-05-child-pact"
                )

            oversized = root / "large.png"
            Image.new("RGB", (512, 512)).save(oversized)
            with self.assertRaisesRegex(ValueError, "strictly smaller than 512x512"):
                generator.run(
                    plan_path, root / "out", "account", "token",
                    reference_image_path=oversized,
                    scale_reference_path=identity_path,
                    only_scene="beat-05-child-pact"
                )

    def test_run_writes_reference_conditioned_image_and_manifest(self):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"image": self.image_b64}}
        session = Mock()
        session.post.return_value = response
        original = generator.generate_one
        generator.generate_one = lambda prompt, account_id, api_token, reference_image=None, scale_reference_image=None, width=832, height=1472, guidance=4.0: original(
            prompt, account_id, api_token, reference_image, scale_reference_image,
            width, height, guidance, session=session
        )
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                plan_path = root / "plan.json"
                plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
                identity_path = self._reference_file(root / "identity.png")
                scale_path = self._reference_file(root / "scale.png")
                out = root / "images"
                manifest = generator.run(
                    plan_path, out, "account", "token",
                    reference_image_path=identity_path,
                    scale_reference_path=scale_path,
                    only_scene="beat-05-child-pact",
                    pause_seconds=0,
                )
                self.assertEqual(manifest["scene_count"], 1)
                self.assertEqual(manifest["model"], "@cf/black-forest-labs/flux-2-klein-4b")
                self.assertFalse(manifest["approved"])
                self.assertFalse(manifest["rendered"])
                self.assertTrue((out / "01-beat-05-child-pact.jpg").is_file())
                saved = json.loads((out / "generation-manifest.json").read_text())
                self.assertEqual(saved["scene_count"], 1)
                self.assertTrue(saved["images"][0]["uses_character_reference"])
                self.assertTrue(saved["images"][0]["uses_scale_reference"])
                self.assertFalse(saved["images"][0]["approved"])
        finally:
            generator.generate_one = original


if __name__ == "__main__":
    unittest.main()
