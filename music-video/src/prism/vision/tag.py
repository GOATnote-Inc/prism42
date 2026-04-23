"""Per-clip Claude Opus 4.7 vision tagging."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from anthropic import Anthropic

from ..models import ClipProfile, ClipTags

DEFAULT_MODEL = os.environ.get("PRISM_MODEL", "claude-opus-4-7")

SYSTEM = """You are a music-video editor analyzing a clip for use in a beat-matched edit.

Given up to four keyframes and technical stats, reply with ONLY this JSON object:
{
  "mood": "<single adjective>",
  "energy": <integer 1-10>,
  "motion_type": "static|subtle|tracking|rapid|chaotic",
  "subject": "<brief content description, under 12 words>",
  "best_use": "intro|build|drop|breakdown|outro|anywhere",
  "directors_note": "<one sentence, under 20 words, your creative take on where this shot belongs>"
}

No prose outside the JSON. No markdown fences. Just the object."""


def _encode_image(path: str) -> dict:
    ext = Path(path).suffix.lower().lstrip(".")
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        ext, "image/jpeg"
    )
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def tag_clip(client: Anthropic, profile: ClipProfile, cache_dir: Path,
             model: str = DEFAULT_MODEL) -> ClipTags:
    cache_file = cache_dir / profile.clip_id / "tags.json"
    if cache_file.exists():
        try:
            return ClipTags.model_validate_json(cache_file.read_text())
        except Exception:
            pass

    keyframes = profile.keyframe_paths[:4]
    content: list[dict] = [_encode_image(kf) for kf in keyframes]
    content.append(
        {
            "type": "text",
            "text": (
                f"Clip stats: duration={profile.duration:.2f}s, "
                f"motion_energy={profile.motion_energy:.3f}, "
                f"brightness={profile.brightness:.2f}, "
                f"resolution={profile.width}x{profile.height}, "
                f"fps={profile.fps:.1f}."
            ),
        }
    )

    msg = client.messages.create(
        model=model,
        max_tokens=500,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    text = msg.content[0].text if msg.content and hasattr(msg.content[0], "text") else ""
    data = _extract_json(text)
    data["clip_id"] = profile.clip_id
    tags = ClipTags(**data)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(tags.model_dump_json(indent=2))
    return tags


def tag_all(profiles: list[ClipProfile], cache_dir: str = ".prism-cache",
            model: str = DEFAULT_MODEL) -> list[ClipTags]:
    client = Anthropic()
    cache = Path(cache_dir)
    return [tag_clip(client, p, cache, model=model) for p in profiles]
