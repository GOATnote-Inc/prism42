"""Clip probing: duration, resolution, motion, keyframes for Claude."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

from ..models import ClipProfile

SUPPORTED_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
SUPPORTED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED = SUPPORTED_VIDEO | SUPPORTED_IMAGE


def ffprobe(path: str) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)


def clip_hash(path: str) -> str:
    st = os.stat(path)
    key = f"{Path(path).name}:{st.st_size}:{st.st_mtime_ns}".encode()
    return hashlib.sha256(key).hexdigest()[:16]


def _profile_image(path: Path, clip_id: str, cache_dir: Path) -> ClipProfile:
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"cv2 could not read {path}")
    h, w = img.shape[:2]
    kf_dir = cache_dir / clip_id
    kf_dir.mkdir(parents=True, exist_ok=True)
    kf_path = kf_dir / "f0.jpg"
    cv2.imwrite(str(kf_path), img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return ClipProfile(
        clip_id=clip_id,
        path=str(path),
        duration=2.0,
        width=int(w),
        height=int(h),
        fps=0.0,
        motion_energy=0.0,
        brightness=float(gray.mean() / 255.0),
        keyframe_paths=[str(kf_path)],
    )


def _profile_video(path: Path, clip_id: str, cache_dir: Path) -> ClipProfile:
    info = ffprobe(str(path))
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"].get("duration", vstream.get("duration", 0)) or 0)
    w, h = int(vstream["width"]), int(vstream["height"])
    fr = vstream.get("r_frame_rate", "30/1")
    if "/" in fr:
        num, den = fr.split("/")
        den = float(den) or 1.0
        fps = float(num) / den
    else:
        fps = float(fr)

    num_kf = min(6, max(1, int(duration / 2)))
    ts = np.linspace(0.2, max(0.2, duration - 0.2), num_kf)
    kf_dir = cache_dir / clip_id
    kf_dir.mkdir(parents=True, exist_ok=True)
    kf_paths: list[str] = []
    brightness_samples: list[float] = []
    motion_samples: list[float] = []

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cv2 could not open {path}")
    prev_gray = None
    try:
        for i, t in enumerate(ts):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            out_path = kf_dir / f"f{i}.jpg"
            cv2.imwrite(str(out_path), frame)
            kf_paths.append(str(out_path))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness_samples.append(float(gray.mean() / 255.0))
            if prev_gray is not None and prev_gray.shape == gray.shape:
                diff = np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16))
                motion_samples.append(float(diff.mean() / 255.0))
            prev_gray = gray
    finally:
        cap.release()

    return ClipProfile(
        clip_id=clip_id,
        path=str(path),
        duration=duration,
        width=w, height=h, fps=fps,
        motion_energy=float(np.mean(motion_samples)) if motion_samples else 0.0,
        brightness=float(np.mean(brightness_samples)) if brightness_samples else 0.5,
        keyframe_paths=kf_paths,
    )


def profile_clip(path: str, cache_dir: Path) -> ClipProfile:
    p = Path(path)
    clip_id = clip_hash(path)
    cache_profile = cache_dir / clip_id / "profile.json"
    if cache_profile.exists():
        try:
            return ClipProfile.model_validate_json(cache_profile.read_text())
        except Exception:
            pass

    suffix = p.suffix.lower()
    if suffix in SUPPORTED_IMAGE:
        prof = _profile_image(p, clip_id, cache_dir)
    elif suffix in SUPPORTED_VIDEO:
        prof = _profile_video(p, clip_id, cache_dir)
    else:
        raise ValueError(f"unsupported extension: {p.suffix}")

    cache_profile.parent.mkdir(parents=True, exist_ok=True)
    cache_profile.write_text(prof.model_dump_json(indent=2))
    return prof


def ingest_folder(folder: str, cache_dir: str = ".prism-cache") -> list[ClipProfile]:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    profiles: list[ClipProfile] = []
    for p in sorted(Path(folder).iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            try:
                profiles.append(profile_clip(str(p), cache))
            except Exception as e:
                print(f"[prism] skip {p.name}: {e}")
    if not profiles:
        raise RuntimeError(f"no usable clips found in {folder}")
    return profiles
