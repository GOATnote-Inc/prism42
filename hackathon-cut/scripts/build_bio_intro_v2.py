"""build_bio_intro_v2.py — proper bio intro using Runway gwm1 lip-synced Ken.

Inputs:
  ../runway-pipeline/ken_lipsync.mp4  (28.8s, Ken speaking the full bio VO)
  ../assets/Fizzlepuff.mp4            (5.2s, dancing with glowstick)
  ../vo/bio-intro-mix.mp3             (28.8s — already baked into ken_lipsync.mp4 via SOURCE)

Output: ../final/bio-intro-v2.mp4 (29.5s, 1920x1080 24fps H.264 + AAC)

Strategy (per viral-hooks.md drop-in shot table, simplified for ken_lipsync.mp4):
  - Use ken_lipsync.mp4 as primary visual scaled to 1920x1080
  - At 19.9s, hard cut to Fizzlepuff for 0.9s "ASSISTANT!" yell
  - Cut back to ken_lipsync at 20.8s
  - Layer credential PNG overlays at: 4.5s EMT, 8s MEDICAL SCHOOL, 12s TRAUMA RESIDENCY,
    17.5s ASSISTANT PROFESSOR · 6.5 YEARS, 24s AI RESEARCH
  - Lower-third "DR. BRANDON DENT" at 1.5s, fade out at 5.0s
  - Corner mark "PRISM 42" top-right from 0.5s onwards
  - Audio: bio-intro-mix.mp3 (already in ken_lipsync.mp4 — keep it)
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
FINAL = PROJECT / "final"
WORK = PROJECT / "work_v2"
KEN = PROJECT / "runway-pipeline" / "ken_lipsync.mp4"
FIZZ = PROJECT / "assets" / "Fizzlepuff.mp4"
VO_MIX = PROJECT / "vo" / "bio-intro-mix.mp3"
FINAL.mkdir(parents=True, exist_ok=True)
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True, exist_ok=True)

FFMPEG = "/opt/homebrew/bin/ffmpeg"
W, H, FPS = 1920, 1080, 24
MINT = (127, 227, 196)
WHITE = (255, 255, 255)


def font(sz: int):
    for p in ["/System/Library/Fonts/HelveticaNeue.ttc",
              "/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"]:
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def make_credential_stamp(text: str, out_path: Path, two_line: bool = False) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if two_line:
        lines = text.split(" · ")
        f = font(64)
        line_h = 90
        total_h = line_h * len(lines) + 18
        y0 = int(H * 0.12) - total_h // 2 + 50
        for i, line in enumerate(lines):
            bbox = d.textbbox((0, 0), line, font=f)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            y = y0 + i * line_h
            d.text((x + 3, y + 3), line, fill=(0, 0, 0, 220), font=f)
            d.text((x, y), line, fill=WHITE, font=f)
        u_y = y0 + total_h
        d.rectangle([(W - 220) // 2, u_y, (W + 220) // 2, u_y + 6], fill=(*MINT, 255))
    else:
        f = font(72)
        bbox = d.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        y = int(H * 0.10)
        d.text((x + 3, y + 3), text, fill=(0, 0, 0, 220), font=f)
        d.text((x, y), text, fill=WHITE, font=f)
        u_y = y + 88
        d.rectangle([(W - 200) // 2, u_y, (W + 200) // 2, u_y + 5], fill=(*MINT, 255))
    img.save(out_path, "PNG")


def make_lower_third(name: str, role: str, out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    strip_top = int(H * 0.84)
    strip_h = int(H * 0.11)
    d.rectangle([0, strip_top, W, strip_top + strip_h], fill=(0, 0, 0, 200))
    d.rectangle([0, strip_top, 14, strip_top + strip_h], fill=(*MINT, 255))
    d.text((60, strip_top + 16), name, fill=WHITE, font=font(48))
    d.text((60, strip_top + 76), role, fill=MINT, font=font(28))
    img.save(out_path, "PNG")


def make_corner_mark(out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    text = "PRISM 42"
    f = font(38)
    bbox = d.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    x = W - tw - 48
    y = 36
    d.rectangle([x - 14, y - 6, x + tw + 14, y + 56], fill=(0, 0, 0, 200))
    d.text((x, y), text, fill=WHITE, font=f)
    d.rectangle([x - 14, y + 52, x + tw + 14, y + 58], fill=(*MINT, 255))
    img.save(out_path, "PNG")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(cmd[:6]), "...")
        print(r.stderr[-1000:])
        raise RuntimeError(f"ffmpeg failed exit {r.returncode}")


def main() -> None:
    # Render overlay PNGs
    print("==> rendering overlay PNGs")
    p_emt = WORK / "ovr_emt.png"
    p_med = WORK / "ovr_med.png"
    p_trauma = WORK / "ovr_trauma.png"
    p_assist = WORK / "ovr_assist.png"
    p_ai = WORK / "ovr_ai.png"
    p_lt = WORK / "ovr_lt.png"
    p_corner = WORK / "ovr_corner.png"
    make_credential_stamp("EMT", p_emt)
    make_credential_stamp("MEDICAL SCHOOL", p_med)
    make_credential_stamp("TRAUMA RESIDENCY", p_trauma)
    make_credential_stamp("ASSISTANT PROFESSOR · 6.5 YEARS", p_assist, two_line=True)
    make_credential_stamp("AI RESEARCH", p_ai)
    make_lower_third("DR. BRANDON DENT", "physician · AI researcher", p_lt)
    make_corner_mark(p_corner)

    # === Build the visual track ===
    # Step 1: scale ken_lipsync to 1920x1080 (pad with letterbox)
    print("==> scale ken_lipsync to 1920x1080 (letterbox)")
    ken_1080 = WORK / "ken_1080.mp4"
    run([FFMPEG, "-y", "-i", str(KEN),
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:-1:-1:color=black",
         "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
         "-pix_fmt", "yuv420p", "-an", str(ken_1080)])

    # Step 2: cut ken into A (0–19.9s) and B (20.8s–end)
    print("==> cut ken into A (pre-cutaway) and B (post-cutaway)")
    ken_a = WORK / "ken_a.mp4"
    run([FFMPEG, "-y", "-i", str(ken_1080), "-t", "19.9",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-an", str(ken_a)])
    ken_b = WORK / "ken_b.mp4"
    run([FFMPEG, "-y", "-ss", "20.8", "-i", str(ken_1080),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-an", str(ken_b)])

    # Step 3: extract 0.9s of Fizzlepuff (start at 1.5s into source for active glowstick swing)
    print("==> extract 0.9s Fizzlepuff cutaway")
    fizz_cut = WORK / "fizz_cut.mp4"
    run([FFMPEG, "-y", "-ss", "1.5", "-i", str(FIZZ),
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:-1:-1:color=black",
         "-frames:v", str(int(round(0.9 * FPS))),
         "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
         "-pix_fmt", "yuv420p", "-an", str(fizz_cut)])

    # Step 4: concat A + Fizz + B
    print("==> concat A + Fizz + B")
    concat_txt = WORK / "concat.txt"
    concat_txt.write_text("\n".join([
        f"file '{ken_a.resolve()}'",
        f"file '{fizz_cut.resolve()}'",
        f"file '{ken_b.resolve()}'",
    ]))
    visual_no_overlays = WORK / "visual_no_overlays.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
         "-c", "copy", str(visual_no_overlays)])

    # Step 5: layer overlays (corner mark always on, lower-third 1.5–5s, credential stamps at timings)
    print("==> layer overlays")
    visual_overlaid = WORK / "visual_overlaid.mp4"
    # Filter chain: progressively add each overlay with timing
    fc = (
        # Corner mark always
        f"[0:v][1:v]overlay=0:0:enable='gte(t,0.5)'[v1];"
        # Lower-third 1.5–5.0
        f"[v1][2:v]overlay=0:0:enable='between(t,1.5,5.0)'[v2];"
        # EMT stamp 4.5–7.0
        f"[v2][3:v]overlay=0:0:enable='between(t,4.5,7.0)'[v3];"
        # MEDICAL SCHOOL 8.0–11.0
        f"[v3][4:v]overlay=0:0:enable='between(t,8.0,11.0)'[v4];"
        # TRAUMA RESIDENCY 12.0–15.0
        f"[v4][5:v]overlay=0:0:enable='between(t,12.0,15.0)'[v5];"
        # ASSISTANT PROFESSOR 17.5–19.6 (cut before fizz interrupt)
        f"[v5][6:v]overlay=0:0:enable='between(t,17.5,19.6)'[v6];"
        # AI RESEARCH 24.0–27.5
        f"[v6][7:v]overlay=0:0:enable='between(t,24.0,27.5)'[outv]"
    )
    # IMPORTANT: -loop 1 on PNG inputs makes them infinite; -shortest is unreliable
    # with filter_complex chains. Use explicit -frames:v to cap output frame count.
    n_frames = int(round(29.0 * FPS))  # 29s cap (covers 28.8s VO)
    run([FFMPEG, "-y",
         "-i", str(visual_no_overlays),
         "-loop", "1", "-i", str(p_corner),
         "-loop", "1", "-i", str(p_lt),
         "-loop", "1", "-i", str(p_emt),
         "-loop", "1", "-i", str(p_med),
         "-loop", "1", "-i", str(p_trauma),
         "-loop", "1", "-i", str(p_assist),
         "-loop", "1", "-i", str(p_ai),
         "-filter_complex", fc,
         "-map", "[outv]",
         "-frames:v", str(n_frames),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
         "-pix_fmt", "yuv420p",
         str(visual_overlaid)])

    # Step 6: mux with bio-intro-mix.mp3 (clean re-mux — ken_lipsync.mp4's audio is the AVATAR's voice,
    # NOT our ElevenLabs narrator. Replace it with the canonical bio-intro-mix.mp3.)
    print("==> mux with bio-intro-mix.mp3 (canonical narrator)")
    out_master = FINAL / "bio-intro-v2.mp4"
    run([FFMPEG, "-y",
         "-i", str(visual_overlaid),
         "-i", str(VO_MIX),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-map", "0:v", "-map", "1:a",
         "-shortest", str(out_master)])

    # Probe
    r = subprocess.run([FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
                        "-show_entries", "format=duration,size",
                        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
                        "-of", "default=noprint_wrappers=1", str(out_master)],
                       capture_output=True, text=True)
    print(f"\n==> done -> {out_master}")
    print(r.stdout)


if __name__ == "__main__":
    main()
