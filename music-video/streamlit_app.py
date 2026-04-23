"""Prism — Streamlit UI.

Run:
    streamlit run streamlit_app.py

Drop a song + clips, watch Claude Opus 4.7 direct the edit, get two polished
outputs (9:16 for TikTok/Reels, 16:9 for YouTube) with Claude's reasoning
visible per cut.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from prism.audio.analyze import analyze
from prism.assembly.render import render, write_directors_notes
from prism.director.plan import plan_edit
from prism.vision.ingest import SUPPORTED, ingest_folder
from prism.vision.tag import tag_all

st.set_page_config(page_title="Prism", page_icon="🎬", layout="wide")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style="padding: 1.2rem 1.5rem; border-radius: 16px;
                background: linear-gradient(135deg, #1a0033 0%, #4b0082 50%, #8b008b 100%);
                color: #fff; margin-bottom: 1.5rem;">
      <h1 style="margin:0; font-size: 2.4rem; letter-spacing: -0.02em;">🎬 Prism</h1>
      <p style="margin: 0.3rem 0 0; opacity: 0.85;">
        Claude Opus 4.7 as your music-video editor —
        beat-matched cuts for TikTok, Reels, and YouTube.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar: inputs ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("1. Song")
    song_file = st.file_uploader(
        "Copyright-free audio",
        type=["mp3", "wav", "m4a", "flac", "ogg"],
        accept_multiple_files=False,
    )

    st.header("2. Clips")
    clip_files = st.file_uploader(
        "Drop any mix of video + images",
        type=[ext.lstrip(".") for ext in SUPPORTED],
        accept_multiple_files=True,
    )

    st.header("3. Format")
    aspect = st.radio(
        "Render aspect",
        options=["both", "16:9", "9:16"],
        horizontal=True,
        help="`both` renders TikTok + YouTube versions in one run.",
    )

    st.header("4. Key")
    key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if key_ok:
        st.success("ANTHROPIC_API_KEY detected")
    else:
        st.error("Set ANTHROPIC_API_KEY before running.")
        st.caption(
            "`export ANTHROPIC_API_KEY=sk-ant-...` in the shell that launched streamlit."
        )

    go = st.button(
        "🎬  Make the video",
        type="primary",
        disabled=not (key_ok and song_file and clip_files),
        use_container_width=True,
    )

    st.caption(
        "Nothing you upload leaves your machine except: "
        "keyframes (images) + metadata → Anthropic's API for Claude's "
        "creative reasoning."
    )


# ── Main: pipeline ────────────────────────────────────────────────────────────
if not go:
    st.info(
        "Upload a song + some clips in the sidebar, then hit **Make the video**. "
        "Prism will:\n\n"
        "1. Detect the song's beats, tempo, and structure (librosa).\n"
        "2. Probe every clip for duration, motion, and keyframes (ffprobe + opencv).\n"
        "3. Ask **Claude Opus 4.7** to *watch* each clip and tag its mood, energy, motion, and best use.\n"
        "4. Ask **Claude Opus 4.7** to plan the edit — which clip on which beat, with reasoning.\n"
        "5. Render in 16:9 and/or 9:16 with ffmpeg, write `director.json` alongside each MP4."
    )
    st.stop()


# Stage files into a temp dir so existing CLI-style functions work unchanged
tmp_root = Path(tempfile.mkdtemp(prefix="prism_ui_"))
song_path = tmp_root / song_file.name
song_path.write_bytes(song_file.read())

clips_dir = tmp_root / "clips"
clips_dir.mkdir()
for cf in clip_files:
    (clips_dir / cf.name).write_bytes(cf.read())

out_dir = tmp_root / "out"
out_dir.mkdir()
cache_dir = tmp_root / "cache"
cache_dir.mkdir()

aspects = ["16:9", "9:16"] if aspect == "both" else [aspect]

# ── Stage 1: audio ────────────────────────────────────────────────────────────
with st.status("Analyzing song (librosa)…", expanded=True) as s:
    grid = analyze(str(song_path))
    s.update(
        label=(
            f"♫ {grid.tempo:.0f} BPM · {len(grid.beats)} beats · "
            f"{len(grid.sections)} sections · {grid.duration:.1f}s"
        ),
        state="complete",
    )

# ── Stage 2: clip probe ───────────────────────────────────────────────────────
with st.status("Probing clips (ffprobe + opencv)…", expanded=True) as s:
    profiles = ingest_folder(str(clips_dir), str(cache_dir))
    rows = [
        {
            "id": p.clip_id[:8],
            "file": Path(p.path).name,
            "kind": "image" if p.fps == 0 else "video",
            "duration": round(p.duration, 2),
            "motion": round(p.motion_energy, 3),
            "brightness": round(p.brightness, 2),
        }
        for p in profiles
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    s.update(label=f"🎞 {len(profiles)} clips probed", state="complete")

# ── Stage 3: Claude vision ────────────────────────────────────────────────────
with st.status("Claude Opus 4.7 reading every clip (vision)…", expanded=True) as s:
    tags = tag_all(profiles, str(cache_dir))
    rows = [
        {
            "id": t.clip_id[:8],
            "mood": t.mood,
            "energy": t.energy,
            "motion": t.motion_type,
            "best_use": t.best_use,
            "subject": t.subject,
            "director's note": t.directors_note,
        }
        for t in tags
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    s.update(label=f"🧠 {len(tags)} clips tagged by Opus 4.7", state="complete")

# ── Stage 4 + 5: plan + render per aspect ─────────────────────────────────────
cols = st.columns(len(aspects))
for col, a in zip(cols, aspects):
    with col:
        st.subheader(f"{a}")
        with st.status(f"Claude Opus 4.7 directing the {a} edit…", expanded=False) as s:
            plan = plan_edit(grid, tags, aspect=a)
            s.update(label=f"🎬 {len(plan.segments)} cuts planned", state="complete")

        st.markdown(
            f"""
            <div style="background:#1a0033; padding: 0.9rem 1.1rem; border-radius: 10px;
                        color: #eee; border-left: 3px solid #c080ff; margin-bottom: 1rem;">
              <div style="font-weight: 600; color: #c080ff; letter-spacing: 0.04em;
                          font-size: 0.78rem; text-transform: uppercase;">
                Claude's director's note
              </div>
              <div style="margin-top: 0.4rem;">{plan.directors_note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        suffix = a.replace(":", "x")
        out_video = out_dir / f"{song_path.stem}__{suffix}.mp4"
        out_notes = out_dir / f"{song_path.stem}__{suffix}__director.json"

        with st.status(f"Rendering {out_video.name} (ffmpeg)…", expanded=False) as s:
            render(plan, profiles, str(song_path), str(out_video),
                   work_dir=str(cache_dir / f"render_{suffix}"))
            write_directors_notes(plan, str(out_notes))
            s.update(label=f"✅ {out_video.name}", state="complete")

        st.video(str(out_video))

        with open(out_video, "rb") as f:
            st.download_button(
                f"⬇ Download {a} MP4",
                data=f.read(),
                file_name=out_video.name,
                mime="video/mp4",
                use_container_width=True,
            )

        with st.expander(f"📓 Why each cut ({len(plan.segments)})"):
            st.dataframe(
                [
                    {
                        "beat": f"{s.beat_start:.2f}–{s.beat_end:.2f}",
                        "clip": s.clip_id[:8],
                        "cut": s.cut_style,
                        "why": s.reasoning,
                    }
                    for s in plan.segments
                ],
                use_container_width=True, hide_index=True,
            )

st.success(f"Done. Outputs staged at `{out_dir}` for this session.")
