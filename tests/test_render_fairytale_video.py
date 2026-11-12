import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "destination-prototype"))
from render_fairytale_video import load_inputs, make_contact_sheet, make_ambient, _audio_mix_filter, _chapter_frame


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

    def test_chapter_overlay_is_visible_and_preserves_vertical_frame_size(self):
        source = Image.new("RGB", (1080, 1920), (35, 42, 50))
        labelled = _chapter_frame(source, "NIGHT ONE — THE NECKLACE", 3)
        self.assertEqual(labelled.size, (1080, 1920))
        self.assertNotEqual(labelled.getpixel((80, 120)), source.getpixel((80, 120)))
        self.assertEqual(labelled.getpixel((540, 1000)), source.getpixel((540, 1000)))

    def test_story_plan_runs_in_chronological_order_with_a_clear_name_reveal(self):
        plan = json.loads((ROOT / "research" / "rumpelstiltskin-pilot.json").read_text(encoding="utf-8"))
        ids = [scene["id"] for scene in plan["scenes"]]
        self.assertEqual(ids, [
            "beat-02-boast",
            "beat-01-threat",
            "beat-03-first-bargains",
            "beat-04-king-demands",
            "beat-05-child-pact",
            "beat-06-claim",
            "beat-07-three-days",
            "beat-08-forest-fire",
            "beat-09-foot-revelation",
        ])
        self.assertIn("Rumpelstiltskin!", plan["scenes"][-1]["narration"])
        self.assertEqual(plan["narration"], " ".join(scene["narration"] for scene in plan["scenes"]))
        self.assertTrue(120 <= len(plan["narration"].split()) <= 140)

    def test_ffmpeg_mix_reads_narration_and_ambient_from_correct_inputs(self):
        mix = _audio_mix_filter()
        self.assertIn("[1:a]volume=1.0[narr]", mix)
        self.assertIn("[2:a]volume=0.22[bed]", mix)
        self.assertNotIn("[0:a]", mix)

    def test_ambient_audio_fade_uses_integer_slice_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ambient.wav"
            make_ambient(path, 0.8)
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertGreater(audio.getframerate(), 0)
                self.assertGreater(audio.getnframes(), 0)

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
            manifest = json.loads((folder / "generation-manifest.json").read_text())
            first_row = manifest["images"][0]
            (folder / first_row["file"]).unlink()
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
            manifest = json.loads((folder / "generation-manifest.json").read_text())
            image_path = folder / manifest["images"][0]["file"]
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
