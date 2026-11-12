#!/usr/bin/env python3
"""Generate a review-only set of fairytale scene images with Cloudflare Workers AI.

This tool never approves assets and never renders or publishes a video.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image

MODEL_ID = "@cf/black-forest-labs/flux-1-schnell"
API_ROOT = "https://api.cloudflare.com/client/v4/accounts"

STYLE_BIBLE = (
    "Cinematic dark European fairytale, late-medieval Central European setting, "
    "gothic storybook realism, richly textured oil-painting and fine-grain film look, "
    "deep forest greens, tarnished gold, charcoal shadows, warm candlelight, "
    "dramatic chiaroscuro, atmospheric mist, carefully composed vertical-film framing. "
    "The miller's daughter is the same young adult woman in every scene: pale skin, "
    "long dark auburn braided hair, simple ivory linen dress, expressive face. "
    "The king is the same stern middle-aged man in every scene: black beard, "
    "dark crimson and gold royal clothing. Maintain consistent faces, clothing, "
    "proportions and period design across all scenes."
)

# Keep the folkloric character unmistakably male and visually distinct from
# both the miller's daughter and the king. Grimm descriptions identify him as
# a little old man with bandy legs, a fiery red nose and a long peaked cap.
RUMPELSTILTSKIN_CHARACTER_LOCK = (
    "IDENTITY LOCK — RUMPELSTILTSKIN: He is ALWAYS an unmistakably adult MALE "
    "folkloric little man/dwarf, elderly and very short (about waist-high beside "
    "the young woman), never female or androgynous. He has a weathered masculine "
    "old-man face, a prominent fiery red nose, strong bushy eyebrows, a long "
    "flowing white beard and moustache, crooked bandy legs, and a mischievous "
    "slightly sinister expression. His distinctive traditional costume is a "
    "bright red peaked pointed cap, a red cloak or short red jacket, a deep "
    "cobalt-blue tunic, ochre-brown breeches, and curled pointed leather shoes. "
    "Keep exactly this male face, beard, red cap and red-blue-ochre costume in "
    "every scene where he appears. Do NOT turn Rumpelstiltskin into a woman, "
    "girl, queen, female elf, ordinary tall man, child, or hooded anonymous figure. "
    "No green hood covering his head; his red peaked cap and white beard must be visible."
)

NEGATIVE_GUIDANCE = (
    "No text, letters, captions, typography, watermark, logo, collage, comic panels, "
    "modern objects, modern clothing, anime, cartoon, 3D render, plastic skin, "
    "extra fingers, malformed hands, duplicate characters, gore or graphic violence."
)

SCENE_VISUALS = {
    "beat-01-threat": (
        "The miller's daughter alone in a vast stone chamber piled high with golden straw, "
        "an old spinning wheel beside her, the king's threatening silhouette visible in the doorway; "
        "fearful but dignified, cinematic wide establishing composition."
    ),
    "beat-02-boast": (
        "A nervous miller in rough wool clothing presenting his daughter before a stern king "
        "in a candlelit medieval throne room; the daughter looks shocked by her father's boast, "
        "straw bales in the background."
    ),
    "beat-03-first-bargains": (
        "Show Rumpelstiltskin clearly in the foreground: a tiny elderly male dwarf with a long "
        "white beard, fiery red nose and bright red pointed cap, wearing a short red cloak, "
        "blue tunic, ochre breeches and curled shoes. He turns straw into shimmering gold at "
        "an antique spinning wheel while the young woman watches in astonishment; her necklace "
        "is visible as the price of the bargain. Make his male face and full folkloric costume obvious."
    ),
    "beat-04-king-demands": (
        "The stern king leading the miller's daughter into an even larger stone chamber filled "
        "with straw, golden light spilling from the doorway, the spinning wheel waiting in "
        "the foreground."
    ),
    "beat-05-child-pact": (
        "Rumpelstiltskin, unmistakably a tiny elderly bearded MALE dwarf in his bright red peaked "
        "cap, red cloak, blue tunic, ochre-brown breeches and curled shoes, faces the miller's "
        "daughter beside a spinning wheel in a shadowy straw-filled chamber. His prominent red "
        "nose and long white beard are clearly visible. She holds an empty hand, conveying that "
        "she has nothing left to give; tense solemn bargain, no written contract."
    ),
    "beat-06-claim": (
        "The young queen in a medieval royal chamber protects her peacefully sleeping infant "
        "while Rumpelstiltskin, the same tiny elderly MALE folkloric dwarf with a long white beard, "
        "fiery red nose, bright red peaked cap, red cloak, blue tunic and ochre breeches, stands "
        "before her demanding the promise. His male face and traditional costume are unmistakable; "
        "emotionally tense, no threat to the baby."
    ),
    "beat-07-three-days": (
        "The anxious queen at a castle window speaking urgently with a mounted messenger "
        "preparing to ride into a moonlit forest; urgency, candlelight and cold blue night "
        "beyond the window."
    ),
    "beat-08-forest-fire": (
        "Rumpelstiltskin alone beside a small forest fire near a crooked woodland hut, dancing "
        "on one leg in wicked delight. He is a tiny elderly MALE folkloric dwarf with a long "
        "white beard and moustache, prominent fiery red nose, bright red peaked pointed cap, "
        "short red cloak, blue tunic, ochre-brown breeches and curled pointed shoes. Show his "
        "clearly masculine old face and crooked little legs; moonlit trees and drifting sparks."
    ),
    "beat-09-foot-revelation": (
        "The same unmistakably elderly MALE Rumpelstiltskin after the queen has spoken his name: "
        "tiny bearded folkloric dwarf, fiery red nose, white beard and moustache, bright red peaked "
        "cap, red cloak, blue tunic, ochre breeches and curled shoes. One crooked bandy leg is "
        "stamped deep into the wooden floorboards as he strains to pull it free with both hands; "
        "his furious masculine face is visible, the queen stands safely in the background, no gore."
    ),
}

RUMPELSTILTSKIN_SCENES = {
    "beat-03-first-bargains",
    "beat-05-child-pact",
    "beat-06-claim",
    "beat-08-forest-fire",
    "beat-09-foot-revelation",
}


def build_prompt(scene: dict[str, Any], index: int) -> str:
    scene_id = str(scene.get("id", ""))
    visual = SCENE_VISUALS.get(scene_id)
    if not visual:
        raise ValueError(f"No approved visual direction exists for scene {scene_id!r}")
    title = str(scene.get("title", scene_id)).strip()
    character_lock = (
        f" {RUMPELSTILTSKIN_CHARACTER_LOCK}"
        if scene_id in RUMPELSTILTSKIN_SCENES else ""
    )
    return (
        f"{STYLE_BIBLE} Scene {index}: {title}. {visual}"
        f"{character_lock} Story context: {str(scene.get('narration', '')).strip()} "
        f"{NEGATIVE_GUIDANCE}"
    )[:2048]


def _decode_image(payload: dict[str, Any]) -> bytes:
    image_value = payload.get("result", {}).get("image")
    if not isinstance(image_value, str) or not image_value:
        raise RuntimeError(f"Cloudflare response did not contain result.image: {json.dumps(payload)[:500]}")
    try:
        data = base64.b64decode(image_value, validate=True)
    except Exception as exc:
        raise RuntimeError("Cloudflare returned invalid base64 image data") from exc
    if not data:
        raise RuntimeError("Cloudflare returned an empty image")
    return data


def generate_one(prompt: str, account_id: str, api_token: str,
                 steps: int = 4, session: Any = requests) -> bytes:
    """Call FLUX.1 schnell using only its supported REST input fields."""
    url = f"{API_ROOT}/{account_id}/ai/run/{MODEL_ID}"
    response = session.post(
        url,
        headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
        json={"prompt": prompt, "steps": steps},
        timeout=(20, 240),
    )
    if response.status_code == 429:
        raise RuntimeError("Cloudflare Workers AI rate limit reached; retry later")
    if response.status_code >= 400:
        raise RuntimeError(f"Cloudflare Workers AI returned HTTP {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Cloudflare Workers AI returned non-JSON response") from exc
    return _decode_image(payload)


def run(plan_path: Path, output_dir: Path, account_id: str, api_token: str,
        steps: int = 4, pause_seconds: float = 1.0) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scenes = plan.get("scenes", [])
    if not scenes:
        raise ValueError("The story plan contains no scenes")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "story": plan.get("title", plan.get("series", "Untitled story")),
        "model": MODEL_ID,
        "steps": steps,
        "status": "generated_unapproved_review_only",
        "approved": False,
        "rendered": False,
        "published": False,
        "images": [],
    }
    for index, scene in enumerate(scenes, 1):
        prompt = build_prompt(scene, index)
        data = generate_one(prompt, account_id, api_token, steps=steps)
        filename = f"{index:02d}-{re.sub(r'[^a-z0-9]+', '-', str(scene['id']).lower()).strip('-')}.jpg"
        path = output_dir / filename
        path.write_bytes(data)
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format
        manifest["images"].append({
            "scene_id": scene["id"],
            "title": scene.get("title", scene["id"]),
            "file": filename,
            "width": width,
            "height": height,
            "format": image_format,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "approved": False,
        })
        print(f"Generated {index}/{len(scenes)}: {filename} ({width}x{height})")
        if index < len(scenes) and pause_seconds > 0:
            time.sleep(pause_seconds)
    manifest["scene_count"] = len(manifest["images"])
    manifest_path = output_dir / "generation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("research/rumpelstiltskin-pilot.json"))
    parser.add_argument("--output", type=Path, default=Path("output/rumpelstiltskin-generated-scenes"))
    parser.add_argument("--steps", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    args = parser.parse_args()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not api_token:
        raise SystemExit(
            "Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN. "
            "Add these as GitHub Actions repository secrets before running this workflow."
        )
    manifest = run(args.plan, args.output, account_id, api_token, args.steps, args.pause_seconds)
    print(f"Generated {manifest['scene_count']} unapproved scene images with {MODEL_ID}")
    print(f"Review directory: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
