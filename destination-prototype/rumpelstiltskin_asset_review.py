#!/usr/bin/env python3
"""Build a private, source-backed image review board for the Grimm pilot.

Candidate discovery, licensing, OCR, size/upscale, duplicate and CLIP gates are
delegated to the existing destination-prototype asset resolver. Nothing here
approves an asset or renders a video.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import asset_resolver as ar
import rumpelstiltskin_visual_policy as visual_policy

SEEDS = [
    {"file_title": "Rumpelstiltskin at the Spinning-Wheel and the Dwarf MET DP827694.jpg",
     "scene_id": "beat-03-first-bargains",
     "source_url": "https://commons.wikimedia.org/wiki/File:Rumpelstiltskin_at_the_Spinning-Wheel_and_the_Dwarf_MET_DP827694.jpg"},
    {"file_title": "The Blue Fairy Book, p. 97.jpg",
     "scene_id": "beat-03-first-bargains",
     "source_url": "https://commons.wikimedia.org/wiki/File:The_Blue_Fairy_Book,_p._97.jpg"},
    {"file_title": "GrimmsGoblins-140-Rumpelstiltskin.jpg",
     "scene_id": "beat-09-foot-revelation",
     "source_url": "https://commons.wikimedia.org/wiki/File:GrimmsGoblins-140-Rumpelstiltskin.jpg"},
]

SEARCH_TERMS = {
    "beat-01-threat": ["Rumpelstiltskin threatened daughter spinning straw", "Rumpelstilzchen Müllerstochter Stroh Spinnrad", "Rumpel-Stilts-Kin miller's daughter Grimm"],
    "beat-02-boast": ["Rumpelstiltskin miller daughter Grimm illustration", "Rumpelstilzchen Müller Tochter illustration", "Grimm's Goblins 1876 Rumpel-Stilts-Kin"],
    "beat-03-first-bargains": ["Rumpelstiltskin spinning wheel dwarf necklace ring", "Rumpelstilzchen Spinnrad Zwerg Ring Halsband", "Gustav Heinrich Naeke Rumpelstiltskin spinning wheel", "George Cruikshank Grimm's Goblins Rumpel-Stilts-Kin"],
    "beat-04-king-demands": ["Rumpelstiltskin king chamber golden straw", "Rumpelstilzchen König Kammer goldenes Stroh", "Grimm Rumpel-Stilts-Kin Cruikshank 1876"],
    "beat-05-child-pact": ["Rumpelstiltskin first child bargain Grimm", "Rumpelstilzchen erstes Kind Versprechen", "Rumpel-Stilts-Kin miller's daughter first child"],
    "beat-06-claim": ["Rumpelstiltskin queen infant dwarf illustration", "Rumpelstilzchen Königin Kind Zwerg", "Grimm's Goblins Rumpel-Stilts-Kin 1876"],
    "beat-07-three-days": ["Rumpelstiltskin queen guesses name messenger", "Rumpelstilzchen Königin Namen Bote", "Rumpel-Stilts-Kin name Grimm Cruikshank"],
    "beat-08-forest-fire": ["Rumpelstiltskin dancing fire forest hut", "Rumpelstilzchen Feuer Waldhütte tanzend", "Rumpel-Stilts-Kin fire Grimm's Goblins"],
    "beat-09-foot-revelation": ["Rumpelstiltskin foot stuck floor ending", "Rumpelstilzchen Fuß Boden steckt Ende", "George Cruikshank Rumpel-Stilts-Kin Grimm's Goblins 1876"],
}
ALIASES = tuple(visual_policy.STORY_ALIASES)


def review_scene(raw: dict[str, Any], index: int, visual_mode: str = "exact") -> dict[str, Any]:
    sid = str(raw["id"])
    seed_files = [x["file_title"] for x in SEEDS if x["scene_id"] == sid]
    return visual_policy.build_review_scene(raw, index, visual_mode, seed_files)


def _font(size: int, bold: bool = False):
    candidates = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
                  ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), trial, font=font)[2] > width:
            lines.append(current); current = word
        else:
            current = trial
    if current: lines.append(current)
    return lines


def _story_role(candidate: dict[str, Any], beat_id: str) -> tuple[str, str]:
    role = visual_policy.classify_candidate(candidate, beat_id)
    labels = {
        "exact_story_illustration": "Exact story illustration — source metadata identifies this tale",
        "symbolic_contextual_asset": "Suitable symbolic asset — required visual objects/settings match",
        "unrelated_contextual_art": "Rejected — unrelated or unverified context",
    }
    return role, labels[role]


def _candidate_cell(canvas: Image.Image, box: tuple[int, int, int, int], record: dict[str, Any], beat_title: str,
                    base_dir: Path):
    draw = ImageDraw.Draw(canvas)
    x, y, w, h = box
    draw.rounded_rectangle((x, y, x+w, y+h), radius=18, fill=(43, 38, 34), outline=(113, 92, 70), width=2)
    source = Path(record["file"])
    if not source.is_absolute():
        source = base_dir / source
    img_box = (x+16, y+16, w-32, 330)
    if source.is_file():
        with Image.open(source) as im:
            im = im.convert("RGB")
            im.thumbnail((img_box[2], img_box[3]), Image.Resampling.LANCZOS)  # never upscale for the board
            px = x + (w-im.width)//2
            py = y + 16 + (330-im.height)//2
            canvas.paste(im, (px, py))
    draw.text((x+18, y+354), beat_title[:62], font=_font(20, True), fill=(245, 231, 207))
    role = record.get("visual_role_label", "Candidate")
    draw.text((x+18, y+382), role, font=_font(16, True), fill=(226, 182, 111))
    lines = [f"Creator: {record.get('author') or 'Not stated'}",
             f"Original: {record.get('dimensions', ['?', '?'])[0]} × {record.get('dimensions', ['?', '?'])[1]} px",
             f"Rights: {record.get('rights_statement', 'unavailable')}",
             f"CLIP: {record.get('clip_score', 'not scored')} | approved: false"]
    for i, line in enumerate(lines):
        draw.text((x+18, y+408+i*22), line[:72], font=_font(14), fill=(225, 216, 199))
    src_lines = _wrap(draw, record.get("source_url", ""), _font(12), w-36)
    for i, line in enumerate(src_lines[:3]):
        draw.text((x+18, y+500+i*18), line, font=_font(12), fill=(178, 196, 201))


def create_contact_sheet(plan: dict, candidates_by_scene: dict[str, list[dict]], seed_images: list[dict], out: Path) -> Path:
    width, cell_w, cell_h, margin = 1600, 500, 570, 30
    height = 150 + len(plan["scenes"]) * (cell_h + margin) + 650
    sheet = Image.new("RGB", (width, height), (24, 22, 21))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 24), "RUMPELSTILTSKIN — PRIVATE ASSET REVIEW", font=_font(36, True), fill=(247, 231, 205))
    draw.text((margin, 78), "Candidates that passed the repository's rights, source-size, duplicate, document/OCR and CLIP gates. All remain unapproved.",
              font=_font(18), fill=(209, 192, 168))
    y = 140
    for scene in plan["scenes"]:
        sid = scene["id"]
        group = candidates_by_scene.get(sid, [])
        draw.text((margin, y), f"{sid} · {scene.get('title', sid)}", font=_font(23, True), fill=(235, 197, 132))
        y += 36
        if not group:
            draw.rounded_rectangle((margin, y, width-margin, y+cell_h-36), radius=14, fill=(38, 35, 33), outline=(95, 81, 69), width=2)
            draw.text((margin+24, y+28), "No candidate passed all automatic gates for this beat.", font=_font(21), fill=(208, 196, 180))
            y += cell_h
            continue
        for j, candidate in enumerate(group[:3]):
            _candidate_cell(sheet, (margin + j*(cell_w+20), y, cell_w, cell_h-36), candidate,
                            scene.get("title", sid), out.parent)
        y += cell_h
    y += 8
    draw.text((margin, y), "Known seed checks — files shown here can still be rejected for final use.", font=_font(23, True), fill=(235, 197, 132))
    y += 40
    shown = 0
    for record in seed_images:
        if not record.get("file") or not Path(record["file"]).is_file(): continue
        _candidate_cell(sheet, (margin + shown*(cell_w+20), y, cell_w, cell_h-36), record,
                        "Known Commons seed — placement review", out.parent)
        draw.text((margin + shown*(cell_w+20)+18, y+286), record.get("review_status", "review"), font=_font(13, True), fill=(239, 137, 119))
        shown += 1
        if shown >= 3: break
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92)
    return out


def _seed_review(seed: dict, out: Path, config: dict) -> dict:
    base = {"seed_file_title": seed["file_title"], "scene_id": seed["scene_id"],
            "source_url": seed["source_url"], "approved": False}
    try:
        c = ar._commons_file_candidate(seed["file_title"])
        if not c:
            return {**base, "review_status": "rejected_or_uncertain_rights_metadata", "rights_status": "not accepted by existing rights gate"}
        base.update({"title": c["title"], "author": c["author"], "publication_date": c.get("date_text", ""),
                     "image_url": c["image_url"], "rights_statement": c["rights_statement"],
                     "rights_url": c["rights_url"], "original_dimensions": [c.get("width"), c.get("height")],
                     "rights_status": "passed existing resolver rights gate"})
        data = ar._download(c)
        digest = hashlib.sha256(data).hexdigest()
        from io import BytesIO
        with Image.open(BytesIO(data)) as im:
            im.verify()
        with Image.open(BytesIO(data)) as im:
            dims = list(im.size)
            decoded = hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()
            size_ok = ar._size_ok(im, config["asset_resolver"])
            suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "TIFF": ".tif"}.get(im.format, ".img")
        dest_dir = out / "seed_candidates"
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / (digest[:16] + suffix)
        file_path.write_bytes(data)
        rights_ok = ar._rights_ok(c["rights_statement"]) and (not ar._needs_attribution(c["rights_statement"]) or ar._has_author(c.get("author", "")))
        status = ("eligible_seed_pending_scene_relevance" if size_ok else "rejected_source_resolution") if rights_ok else "rejected_or_uncertain_rights"
        return {**base, "file": str(file_path), "dimensions": dims, "file_sha256": digest,
                "decoded_pixels_sha256": decoded, "byte_size": len(data),
                "resolution_status": "passed" if size_ok else "rejected: source below 1920×1080 requirement",
                "rights_status": "passed existing resolver rights gate" if rights_ok else "rejected or uncertain under existing rights gate",
                "review_status": status, "rights_statement": c["rights_statement"], "approved": False}
    except Exception as exc:
        return {**base, "review_status": "uncertain_download_or_decode", "error": f"{type(exc).__name__}: {exc}"}


def run(plan_path: Path, out: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    out = out.resolve()
    resolver_cfg = {"providers": list(ar.DEFAULT_PROVIDERS), "max_queries": 6,
                    "max_queries_per_provider": 2, "max_downloads": 20,
                    "top_candidates": 3, "min_short_side": 1080,
                    "min_long_side": 1920, "max_upscale": 1.25,
                    "review_candidates_dir": str((out / "candidate-files").resolve())}
    config = {"name": "The Grimm tale Rumpelstiltskin", "asset_resolver": resolver_cfg,
              "image_banned_terms": ["book cover", "title page", "frontispiece", "scanned page", "text page", "page scan", "catalogue page", "exhibition poster", "plate list", "contents page", "pdf", "djvu", "document scan", "report cover"]}
    seed_images = [_seed_review(seed, out, config) for seed in SEEDS]
    used: set[str] = set()
    results, candidates_by_scene = [], {}
    all_sources = {"provider": set(), "rights": set(), "size": set(), "clip": set()}
    rejected, resolver_errors = [], []
    for index, raw in enumerate(plan.get("scenes", []), 1):
        scene = review_scene(raw, index)
        result = {"scene_id": scene["id"], "beat_title": raw.get("title", scene["id"]),
                  "queries": scene["image_search_terms"], "status": "no_qualified_candidate",
                  "approved": False, "candidates": [], "diagnostics": {}}
        try:
            resolver_preview_dir = out / "resolver-jpegs" / scene["id"]
            resolver_preview_dir.mkdir(parents=True, exist_ok=True)
            _, resolved = ar.resolve_scene_image(scene, index, config,
                resolver_preview_dir, used, out)
            diag = resolved["diagnostics"]
            result["diagnostics"] = diag
            result["status"] = "candidates_available"
            for key, field in (("provider", "provider_source_urls"), ("rights", "rights_pass_source_urls"),
                               ("size", "size_pass_source_urls"), ("clip", "clip_pass_source_urls")):
                all_sources[key].update(diag.get(field, []))
            for candidate in resolved.get("review_candidates", []):
                candidate["file"] = str(Path(candidate["file"]).relative_to(out.resolve()))
                role, label = _story_role(candidate)
                candidate.update({"visual_role": role, "visual_role_label": label})
                candidate["beat_title"] = raw.get("title", scene["id"])
                candidate["approved"] = False
                result["candidates"].append(candidate)
            result["selected_candidate_id"] = result["candidates"][0]["candidate_id"] if result["candidates"] else None
            candidates_by_scene[scene["id"]] = result["candidates"]
        except Exception as exc:
            diag = getattr(exc, "diagnostics", {})
            result["diagnostics"] = diag
            if isinstance(diag, dict):
                for key, field in (("provider", "provider_source_urls"), ("rights", "rights_pass_source_urls"),
                                   ("size", "size_pass_source_urls"), ("clip", "clip_pass_source_urls")):
                    all_sources[key].update(diag.get(field, []))
                rejected.extend({"scene_id": scene["id"], **x} for x in diag.get("top_rejected", []))
                resolver_errors.extend({"scene_id": scene["id"], "provider": k, "error": v}
                                       for k, v in diag.get("provider_errors", {}).items())
            result["error"] = f"{type(exc).__name__}: {exc}"
            candidates_by_scene[scene["id"]] = []
        results.append(result)

    # Dedupe the contact board's candidate records by decoded pixels across all beats.
    seen_pixels = {}
    unique_count = 0
    for result in results:
        for candidate in result["candidates"]:
            digest = candidate.get("decoded_pixels_sha256")
            if digest and digest in seen_pixels:
                candidate["review_status"] = "rejected_duplicate"
                candidate["duplicate_of"] = seen_pixels[digest]
                candidate["approved"] = False
            elif digest:
                seen_pixels[digest] = candidate["candidate_id"]
                unique_count += 1
    for sid in candidates_by_scene:
        candidates_by_scene[sid] = [c for c in candidates_by_scene[sid] if c.get("review_status") != "rejected_duplicate"]

    # Attach relevance outcome for the two supplied seeds based on resolver diagnostics.
    for seed in seed_images:
        clip_urls = all_sources["clip"]
        matching = next((c for r in results for c in r["candidates"] if c.get("source_url") == seed.get("source_url")), None)
        if matching:
            seed["relevance_status"] = "passed CLIP threshold in " + matching["scene_id"]
        elif seed.get("source_url") in all_sources["size"]:
            seed["relevance_status"] = "not independently scored as a review-board candidate"
        else:
            seed["relevance_status"] = "not passed to CLIP (source-size or earlier gate); inspect rejection details"

    summary = {
        "beats": len(results),
        "assets_found_unique_source_pages": len(all_sources["provider"]),
        "unique_source_pages_passed_rights_and_attribution": len(all_sources["rights"]),
        "unique_source_pages_passed_resolution_format_ocr_and_duplicate_gates": len(all_sources["size"]),
        "unique_source_pages_passed_clip_relevance_threshold": len(all_sources["clip"]),
        "unique_candidate_visual_files_for_human_review": unique_count,
        "beats_with_qualified_candidates": sum(bool(x["candidates"]) for x in results),
        "beats_uncovered": [x["beat_title"] for x in results if not x["candidates"]],
        "all_candidates_approved": False,
        "clip_threshold": 0.22,
        "source_size_gate": "short side >= 1080 px; long side >= 1920 px; existing max-upscale <= 1.25; no enlargement performed",
        "style_assessment": "Human visual review required; contextual art is labelled and is not represented as a documented Rumpelstiltskin scene.",
    }
    manifest = {"project": plan.get("series"), "episode": plan.get("title"),
                "source_story_edition": plan.get("version_scope"), "summary": summary,
                "provider_scope": ["Wikimedia Commons official API", "The Metropolitan Museum of Art Open Access API",
                                  "Art Institute of Chicago Open Access", "Cleveland Museum of Art Open Access",
                                  "National Gallery of Art API", "Library of Congress API"],
                "seeds": seed_images, "beats": results, "rejected_or_uncertain": rejected,
                "provider_errors": resolver_errors,
                "review_rules": {"approved": False, "manual_approval_required": True,
                                 "licensing": "existing asset_resolver rights allowlist; no unknown, NC, or ND terms",
                                 "clip": "existing score/document/period thresholds unchanged",
                                 "resolution": "source image dimensions only; no upscaling"}}
    (out / "provenance-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    create_contact_sheet(plan, candidates_by_scene, seed_images, out / "contact-sheet.jpg")
    (out / "README.txt").write_text(
        "Private review artifact. Every item is an unapproved candidate.\n"
        "Candidate images passed the existing automatic rights, resolution, OCR/document, duplicate and CLIP checks.\n"
        "Seed images may be shown separately with a rejection status and are not cleared for rendering.\n"
        "See provenance-manifest.json for exact source file URL, source page, rights URL, creator, dates, dimensions, hashes, scores and rejection diagnostics.\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = run(args.plan, args.output)
    print(json.dumps(manifest["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
