import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "destination-prototype"))
from render_fairytale_video import load_inputs, make_contact_sheet


class FairytaleVideoInputTests(unittest.TestCase):
    def setUp(self):
        self.plan_path = ROOT / "research" / "rumpelstiltskin-pilot.json"
        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))

    def _create_generated_set(self, folder: Path):
        rows = []
        for index, scene in enumerate(self.plan["scenes"]):
            filename = f"{index + 1:02d}-{scene['id']}.jpg"
            path = folder / filename
            image = Image.new("RGB", (832, 1472), ((index * 23) % 255, 70, 90))
            image.save(path, quality=88)
            rows.append({
                "scene_id": scene["id"],
                "file": filename,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "approved": False,
            })
        manifest = {
            "scene_count": len(rows),
            "status": "generated_unapproved_review_only",
            "approved": False,
            "published": False,
            "images": rows,
            "model_strategy": {
                "character_scenes": "@cf/black-forest-labs/flux-2-klein-9b",
                "other_scenes": "@cf/black-forest-labs/flux-2-klein-4b",
            },
        }
        (folder / "generation-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def test_requires_all_nine_generated_images_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._create_generated_set(folder)
            plan, manifest, rows, images = load_inputs(self.plan_path, folder)
            self.assertEqual(len(plan["scenes"]), 9)
            self.assertEqual(manifest["scene_count"], 9)
            self.assertEqual(len(rows), 9)
            self.assertEqual(len(images), 9)
            self.assertTrue(all(image.size == (832, 1472) for image in images))
            self.assertFalse(manifest["approved"])
            self.assertFalse(manifest["published"])

    def test_rejects_incomplete_image_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._create_generated_set(folder)
            (folder / "01-beat-01-threat.jpg").unlink()
            with self.assertRaisesRegex(ValueError, "Missing generated image"):
                load_inputs(self.plan_path, folder)

    def test_rejects_approved_or_published_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._create_generated_set(folder)
            manifest_path = folder / "generation-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["approved"] = True
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "explicitly unapproved"):
                load_inputs(self.plan_path, folder)

    def test_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._create_generated_set(folder)
            image_path = folder / "01-beat-01-threat.jpg"
            image_path.write_bytes(b"not-the-generated-image")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_inputs(self.plan_path, folder)

    def test_contact_sheet_contains_all_nine_beats(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self._create_generated_set(folder)
            plan, _, _, images = load_inputs(self.plan_path, folder)
            output = folder / "contact-sheet.jpg"
            make_contact_sheet(plan, images, output)
            self.assertTrue(output.is_file())
            with Image.open(output) as sheet:
                self.assertEqual(sheet.size, (720, 1278))


if __name__ == "__main__":
    unittest.main()
