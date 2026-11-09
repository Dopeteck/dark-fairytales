"""Download only explicitly approved archival stills from known institutional hosts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from destination_history import COMMERCIAL_LICENSES

ALLOWED_HOSTS = {
    "archive.org", "upload.wikimedia.org", "commons.wikimedia.org",
    "loc.gov", "tile.loc.gov", "images.nara.gov", "catalog.archives.gov",
    "images-assets.nasa.gov", "ids.si.edu", "si.edu",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
TIMEOUT = (10, 60)


def _safe_host(url: str) -> bool:
    """Accept HTTPS only on a literal host or its true subdomains."""
    try:
        parsed = urlparse(str(url))
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme == "https" and any(host == allowed or host.endswith("." + allowed)
                                                 for allowed in ALLOWED_HOSTS)
    except (TypeError, ValueError):
        return False


def download_approved_item(item: dict, asset_root: Path) -> dict:
    if not isinstance(item, dict) or item.get("approved") is not True:
        raise ValueError("Asset must be explicitly approved after human review")
    rights = str(item.get("license") or item.get("rights_statement", "")).strip()
    if rights not in COMMERCIAL_LICENSES:
        raise ValueError("Asset rights statement is missing or not in the approved license categories")
    if item.get("review_flags"):
        raise ValueError("Asset has unresolved review flags")
    url = str(item.get("download_url", ""))
    if not _safe_host(url):
        raise ValueError("Download URL must use HTTPS on an institutional host")
    for field in ("source_url", "rights_url"):
        if not str(item.get(field, "")).startswith("https://"):
            raise ValueError(f"{field} must be retained as an HTTPS provenance URL")
    if str(item.get("media_type", "")).lower() not in {"still", "image", "photo"}:
        raise ValueError("Only approved still images are supported by this downloader")
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError("Download URL must have an unambiguous image extension")

    response = requests.get(url, timeout=TIMEOUT, allow_redirects=False,
                            headers={"User-Agent": "HistoryOfPlacesArchivalDownloader/1.0"})
    if 300 <= response.status_code < 400:
        raise ValueError("External redirects are not followed by the archival downloader")
    response.raise_for_status()
    data = response.content
    if not data:
        raise ValueError("Downloaded image is empty")
    try:
        from io import BytesIO
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").lower()
    except Exception as exc:
        raise ValueError("Downloaded file is not a valid image") from exc
    if max(width, height) < 1920 or min(width, height) < 1080:
        raise ValueError("Image must be at least 1920×1080")

    root = Path(asset_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    asset_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(item.get("asset_id") or "archival_asset"))[:100]
    digest = hashlib.sha256(data).hexdigest()
    destination = root / f"{asset_id}_{digest[:12]}{ext}"
    destination.write_bytes(data)
    result = dict(item)
    result.update({"local_filename": destination.name, "download_validated": True,
                   "download_sha256": digest, "download_bytes": len(data),
                   "dimensions": [width, height], "image_format": image_format,
                   "needs_human_review": bool(result.get("review_flags"))})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise ValueError("Manifest must contain a JSON array")
    errors = []
    for item in manifest:
        if not isinstance(item, dict) or item.get("approved") is not True or item.get("download_validated") is True:
            continue
        try:
            item.update(download_approved_item(item, args.assets))
            item.pop("download_error", None)
        except Exception as exc:
            item["download_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(item["asset_id"])
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Processed approved stills; failed assets: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
