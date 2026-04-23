"""Synthesize a copyright-free test song and colored test clips.

Produces:
  examples/song.mp3           (20s, 120 BPM — sine tone + metronome clicks)
  examples/clips/clip_NN.mp4  (8 short colored clips, 4-6s each, varied motion)
  examples/clips/still_NN.png (2 stills for image-path coverage)

Purely synthetic. Nothing copyrighted. Smoke-tests the whole pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_SONG = ROOT / "examples" / "song.mp3"
OUT_CLIPS = ROOT / "examples" / "clips"

# 8 colored clips with distinct motion / color signatures
CLIPS = [
    ("crimson",  "0x8B0000", 5.0, "zoompan"),
    ("amber",    "0xFFA500", 4.0, "wave"),
    ("teal",     "0x008B8B", 6.0, "hue"),
    ("violet",   "0x8A2BE2", 5.0, "zoompan"),
    ("emerald",  "0x006400", 4.5, "noise"),
    ("sunset",   "0xFF4500", 5.5, "wave"),
    ("cobalt",   "0x0047AB", 4.0, "hue"),
    ("ivory",    "0xFFFAF0", 5.0, "noise"),
]


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {' '.join(cmd)}\n--- stderr ---\n{r.stderr[-800:]}"
        )


def make_song() -> None:
    """20s, 120 BPM. Sine bass + metronome clicks so librosa detects real beats."""
    OUT_SONG.parent.mkdir(parents=True, exist_ok=True)
    # Tone: A2 @ 110Hz; Clicks every 0.5s (120 BPM) via short bursts
    filter_complex = (
        "sine=frequency=110:duration=20,volume=0.35[tone];"
        "sine=frequency=1800:duration=20,"
        "volume='if(lt(mod(t\\,0.5)\\,0.03)\\,1.0\\,0)':eval=frame[click];"
        "[tone][click]amix=inputs=2:duration=first[a]"
    )
    run([
        "ffmpeg", "-y",
        "-filter_complex", filter_complex,
        "-map", "[a]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(OUT_SONG),
    ])
    print(f"song  → {OUT_SONG.relative_to(ROOT)}")


def make_clip(idx: int, name: str, color: str, duration: float, motion: str) -> None:
    """Create a colored clip with motion so Claude sees variation."""
    out = OUT_CLIPS / f"clip_{idx:02d}_{name}.mp4"

    if motion == "zoompan":
        # d=1 → one zoompan step per input frame (not N per input frame)
        vf = "zoompan=z='min(zoom+0.002,1.3)':d=1:s=1280x720:fps=30"
    elif motion == "wave":
        vf = "scale=1280:720,geq=r='r(X,Y)':g='g(X,Y+20*sin(T+X/50))':b='b(X,Y)'"
    elif motion == "hue":
        vf = "hue=h=t*45"
    else:  # noise
        vf = "noise=alls=20:allf=t"

    run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=1280x720:r=30:d={duration}",
        "-vf", vf,
        "-t", f"{duration}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        str(out),
    ])
    print(f"clip  → {out.relative_to(ROOT)}")


def make_still(idx: int, color: str, label: str) -> None:
    out = OUT_CLIPS / f"still_{idx:02d}_{label}.png"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=1280x720:d=1",
        "-frames:v", "1",
        str(out),
    ])
    print(f"still → {out.relative_to(ROOT)}")


def main() -> None:
    OUT_CLIPS.mkdir(parents=True, exist_ok=True)
    make_song()
    for i, (name, color, dur, motion) in enumerate(CLIPS):
        make_clip(i, name, color, dur, motion)
    make_still(0, "0x202020", "dark")
    make_still(1, "0xFFF0F0", "light")
    print("\nReady. Smoke test:")
    print("  prism cut --song examples/song.mp3 --clips examples/clips --out out")


if __name__ == "__main__":
    main()
