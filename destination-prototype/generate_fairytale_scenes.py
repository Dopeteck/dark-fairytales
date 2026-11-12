#!/usr/bin/env python3
"""Generate review-only fairytale scene images with Cloudflare Workers AI.

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
    "gothic storybook realism, richly textured painterly realism, dramatic candlelight, "
    "deep forest green, tarnished gold, charcoal shadows and atmospheric mist. "
    "The miller's daughter is the same young adult woman in every scene: pale skin, "
    "long dark auburn braided hair, simple ivory linen dress. The king is the same "
    "stern middle-aged man with a black beard and dark crimson-and-gold royal clothing. "
    "Keep character faces, costume and period details consistent."
)

# These physical and framing constraints are deliberately placed FIRST in every
# prompt containing Rumpelstiltskin. The prior output followed his clothes but
# ignored scale because the prompt did not insist on a full-body comparison.
RUMPELSTILTSKIN_CHARACTER_LOCK = (
    "PRIMARY SUBJECT — RUMPELSTILTSKIN: an unmistakably ADULT ELDERLY MALE dwarf "
    "from traditional Grimm fairy-tale folklore, extremely short, only about 60 cm "
    "tall. When standing beside the young adult woman (about 165 cm tall), the top "
    "of his red cap reaches ONLY her hip; he is much less than half her height. "
    "This height difference is essential and must be obvious. He has an old rugged "
    "masculine face, prominent fiery-red bulbous nose, thick brows, long flowing "
    "white beard and moustache, short bowed bandy legs and curled pointed shoes. "
    "His fixed traditional costume: bright red tall pointed cap, short red cloak, "
    "deep blue tunic, ochre-brown breeches, curled leather shoes. He is an adult "
    "male folkloric dwarf, NOT a woman, NOT a child, NOT a normal-sized old man, "
    "NOT a tall human and NOT an anonymous hooded figure. Show his entire body "
    "from cap to shoes, with both short crooked legs visible. Show the woman's "
    "entire body beside him to prove the scale. Wide full-length composition, "
    "both characters standing on the same floor, generous space around their feet. "
    "Never hide his legs behind furniture and never crop either character at the waist."
)

NEGATIVE_GUIDANCE = (
    "No text, captions, watermark, collage, comic panels, modern items, anime, "
    "cartoon, 3D render, duplicate limbs, malformed hands, gore or graphic violence."
)

SCENE_VISUALS = {
    "beat-01-threat": (
        "The miller's daughter alone in a vast stone chamber piled high with golden straw; "
        "an old spinning wheel beside her and the king's threatening silhouette in the doorway. "
        "A wide establishing view of the full chamber."
    ),
    "beat-02-boast": (
        "A nervous miller presents his daughter before a stern king in a candlelit medieval "
        "throne room. The daughter looks shocked by her father's boast; straw bales behind them."
    ),
    "beat-03-first-bargains": (
        "A wide full-length view of the tiny Rumpelstiltskin standing beside the much taller "
        "miller's daughter at an antique spinning wheel. He spins straw into shimmering gold. "
        "Keep the wheel to the side so it does not hide his short bowed legs or curled shoes. "
        "The woman's necklace is visible as the price of the bargain."
    ),
    "beat-04-king-demands": (
        "The stern king leads the miller's daughter into an even larger stone chamber filled "
        "with straw; golden light spills from the doorway and a spinning wheel waits in front."
    ),
    "beat-05-child-pact": (
        "WIDE FULL-BODY TWO-SHOT, both figures standing on the same bare stone floor, head to toe "
        "and feet fully visible. On the right is Rumpelstiltskin, a genuinely tiny 60-centimetre "
        "adult male dwarf whose pointed cap reaches only the young woman's hip. On the left is "
        "the much taller young miller's daughter, about 165 centimetres tall. Their height "
        "difference must be unmistakable: he is less than half her height, not a tall man. "
        "His short bowed legs and curled shoes are clearly visible. They face each other beside "
        "a spinning wheel in a shadowy straw-filled chamber. She has nothing left to give; "
        "tense solemn bargain. Do not crop either person and do not hide his legs."
    ),
    "beat-06-claim": (
        "A wide full-length view in a medieval royal chamber. The young queen stands beside her "
        "peacefully sleeping infant's cradle. Rumpelstiltskin stands on the same floor facing her: "
        "a tiny 60-centimetre elderly male dwarf, his pointed red cap reaching only the queen's "
        "hip. Show his entire tiny figure, short bowed legs and curled shoes, with the much taller "
        "queen's full body visible for scale. He demands the promise; no threat to the baby."
    ),
    "beat-07-three-days": (
        "The anxious queen at a castle window speaking urgently with a mounted messenger who "
        "prepares to ride into a moonlit forest; warm candlelight inside and cold blue night outside."
    ),
    "beat-08-forest-fire": (
        "A full-body wide shot of Rumpelstiltskin dancing alone beside a small forest fire and "
        "crooked woodland hut. His entire tiny 60-centimetre adult male dwarf body is visible "
        "head to toe; compare his height with the hut door and nearby tree roots. Show his short "
        "bowed legs and curled shoes clearly as he dances on one leg. Moonlit trees and sparks."
    ),
    "beat-09-foot-revelation": (
        "A full-body wide view of the tiny elderly male dwarf Rumpelstiltskin after the queen "
        "speaks his name. His short bowed leg is stamped deep into the wooden floorboards as he "
        "strains to pull it free with both hands. Show his entire tiny body, white beard, red "
        "pointed cap and curled shoes; his other crooked leg and trapped foot must be visible. "
        "The queen stands farther back for scale. No gore."
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

    # Keep all high-priority subject and scale instructions intact. Add mood
    # and scene facts after them; never truncate the character identity lock.
    parts = []
    if scene_id in RUMPELSTILTSKIN_SCENES:
        parts.extend([RUMPELSTILTSKIN_CHARACTER_LOCK, visual])
    else:
        parts.append(visual)
    parts.extend([f"Scene {index}: {title}.", STYLE_BIBLE, NEGATIVE_GUIDANCE])
    prompt = " ".join(parts)
    if len(prompt) > 2048:
        # Low-priority style adjectives are shortened, never the body/scale lock.
        compact_style = (
            "Dark medieval European fairytale, cinematic painterly realism, "
            "dramatic candlelight, mist, deep greens, old gold and charcoal shadows."
        )
        parts = [part for part in parts if part != STYLE_BIBLE]
        parts.append(compact_style)
        prompt = " ".join(parts)
    if len(prompt) > 2048:
        # Fail explicitly instead of silently cutting off the character constraints.
        raise ValueError(
            f"Prompt for {scene_id} exceeds FLUX's 2048-character limit "
            "after removing optional style detail"
        )
    return prompt


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
                 steps: int = 8, session: Any = requests) -> bytes:
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
        steps: int = 8, pause_seconds: float = 1.0) -> dict[str, Any]:
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
    parser.add_argument("--steps", type=int, choices=range(1, 9), default=8)
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
