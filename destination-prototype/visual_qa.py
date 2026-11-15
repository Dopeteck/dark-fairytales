"""Visual quality control for generated fairytale artwork.

Technical checks (integrity, dimensions, aspect ratio, blank pixels, checksum)
are enforced automatically. Semantic checks (relevance to the narrated event,
correct characters, character consistency, duplicate compositions, malformed
lettering, anatomical defects, empty or confusing compositions) cannot be
reliably verified with the free stack, so they are flagged for human review and
never silently converted into a pass.
"""
from __future__ import annotations

import hashlib
import io
from typing import Any

from PIL import Image

MIN_WIDTH = 700
MIN_HEIGHT = 1200
PORTRAIT_RATIO = 9 / 16
PORTRAIT_TOLERANCE = 0.035
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def technical_checks(data: bytes, expected_sha: str | None = None) -> list[str]:
    """Return a list of technical problems; empty means technically valid."""
    problems: list[str] = []
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format
            bbox = image.getbbox()
    except Exception as exc:
        return [f"image is not a valid image file: {type(exc).__name__}"]
    if image_format not in ALLOWED_FORMATS:
        problems.append(f"unsupported image format: {image_format}")
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        problems.append(f"image too small: {width}x{height}")
    if abs((width / height) - PORTRAIT_RATIO) > PORTRAIT_TOLERANCE:
        problems.append(f"not portrait 9:16: {width}x{height}")
    if bbox is None:
        problems.append("blank image")
    if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
        problems.append("checksum mismatch")
    return problems


def semantic_flags(shot: dict[str, Any]) -> list[str]:
    """Flags that require human review; not reliable enough to automate."""
    from shot_planner import shot_quality_flags
    return shot_quality_flags(shot)


def review_image(data: bytes, shot: dict[str, Any],
                 expected_sha: str | None = None) -> dict[str, Any]:
    """Classify one generated image.

    Returns {"status": "pass"|"review_needed"|"fail", "technical": [...], "semantic": [...]}
    A technically invalid image fails. A technically valid image whose semantic
    quality cannot be verified automatically goes to review_needed.
    """
    technical = technical_checks(data, expected_sha)
    if technical:
        return {"status": "fail", "technical": technical, "semantic": []}
    semantic = semantic_flags(shot)
    status = "review_needed" if semantic else "pass"
    return {"status": status, "technical": technical, "semantic": semantic}
