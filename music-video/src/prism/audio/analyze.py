"""Beat + structure analysis via librosa."""

from __future__ import annotations

import numpy as np
import librosa

from ..models import BeatGrid


def _as_float(x) -> float:
    if hasattr(x, "item"):
        try:
            return float(x.item())
        except Exception:
            pass
    if isinstance(x, np.ndarray):
        return float(x.flatten()[0]) if x.size else 120.0
    return float(x)


def analyze(path: str, sr: int = 22050, n_sections: int = 6) -> BeatGrid:
    y, sr = librosa.load(path, sr=sr, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    tempo = _as_float(tempo)
    beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Downbeats: every 4th beat. (Upgrade path: madmom RNN if needed.)
    downbeats = beats[::4]

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    if len(beat_frames) > 0:
        beat_energy = librosa.util.sync(
            onset_env[np.newaxis, :], beat_frames, aggregate=np.mean
        ).flatten()
        mx = float(beat_energy.max()) if beat_energy.size else 0.0
        if mx > 0:
            beat_energy = (beat_energy / mx).tolist()
        else:
            beat_energy = beat_energy.tolist()
    else:
        beat_energy = []

    # Section boundaries via agglomerative clustering on chroma.
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        bounds = librosa.segment.agglomerative(chroma, k=max(2, n_sections))
        bound_times = librosa.frames_to_time(bounds, sr=sr).tolist()
    except Exception:
        bound_times = [0.0]

    if not bound_times or bound_times[0] > 0:
        bound_times = [0.0] + bound_times
    # Filter sliver sections (agglomerative sometimes emits tiny boundaries).
    min_section = max(1.5, duration / 20.0)
    cleaned = [bound_times[0]]
    for t in bound_times[1:]:
        if t - cleaned[-1] >= min_section:
            cleaned.append(t)
    if cleaned[-1] < duration - min_section:
        cleaned.append(duration)
    else:
        cleaned[-1] = duration
    sections = []
    for i, start in enumerate(cleaned[:-1]):
        end = cleaned[i + 1]
        sections.append(
            {"start": float(start), "end": float(end), "label": f"section_{i+1}"}
        )

    return BeatGrid(
        path=path,
        duration=duration,
        tempo=tempo,
        beats=beats,
        downbeats=downbeats,
        energy=beat_energy,
        sections=sections,
    )
