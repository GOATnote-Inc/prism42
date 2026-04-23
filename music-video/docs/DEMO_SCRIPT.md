# 3-Minute Demo Video Script

Hackathon requires a **3-minute maximum** demo video (YouTube, Loom, or similar)
that holds up live and is "genuinely cool to watch" (Demo = 25% of score).

## Shot list (target: 2:45–2:55)

### 0:00 – 0:15 · Hook
> Full-screen text: "**I dropped 30 clips and a song into Prism.**"
> *(beat)*
> "**Claude Opus 4.7 cut the music video.**"
> *(beat — show a 3-second slice of the finished 16:9 output, no audio for suspense)*
> Play first two beats of output video with audio. **Cut sharp on a downbeat.**

### 0:15 – 0:40 · The inputs
- Show terminal:
  ```
  ls examples/clips/
  clip_00_crimson.mp4  clip_04_emerald.mp4  still_00_dark.png
  clip_01_amber.mp4    clip_05_sunset.mp4   still_01_light.png
  ... (30 total)
  ```
- Play 2 seconds of `song.mp3` so viewer hears the beat.
- Voice-over (VO): "These are the ingredients. A song, a folder of clips. Prism hands both to Claude."

### 0:40 – 1:30 · The pipeline, live
- Run `prism cut --song ... --clips ... --out out` in a real terminal.
- Let the Rich progress stream play. Screen capture, no cuts.
- VO, as each stage flashes:
  - "First: librosa pulls the beat grid. 117 BPM. 41 beats. Two sections."
  - "Next: Claude watches every clip through vision and tags it — mood, energy, motion, best use. Here's its take on the crimson clip."
  - *(freeze on one director's note, read it aloud)*
  - "Then — and this is where it's interesting — Claude receives the whole beat grid and every clip tag, and writes the edit plan."

### 1:30 – 2:00 · Claude's voice
- Zoom in on the "Claude's director's note" panel.
- Read aloud, verbatim, the overall `directors_note` from Claude for this run.
- Then cut to a table view (streamlit UI) of `beat | clip | cut | why`.
- VO: "Claude isn't just matching vibes. It's justifying every cut."

### 2:00 – 2:40 · The outputs
- Split screen: 9:16 phone frame + 16:9 youtube frame, both playing simultaneously, synced.
- Let them play for 30 seconds.
- Lower-third callouts, subtle: "**TikTok / Reels — ready**" and "**YouTube — ready**".

### 2:40 – 2:55 · Close
- Full-screen:
  > "Prism. MIT licensed. Built in 5 days with Opus 4.7.
  > github.com/GOATnote-Inc/prism/tree/main/music-video"
- Beat lands on the final BPM hit of the song.

## Tools
- **Screen recording:** macOS built-in `⌘⇧5` is fine; or QuickTime; or Loom.
- **Edit:** iMovie or DaVinci Resolve for the split-screen and lower thirds.
- **Export:** 1080p, MP4, H.264. Target ≤150 MB. Upload as unlisted YouTube.

## Pre-record checklist
- [ ] Generate a *real* music video: replace synthetic clips with ~20 real Creative-Commons clips + one CC-BY song. Use Pixabay + Pexels.
- [ ] Confirm repo is public before recording URL.
- [ ] Record one clean take of the terminal; the UI split-screen can be pre-rendered.
- [ ] Write lower-third labels in advance.
