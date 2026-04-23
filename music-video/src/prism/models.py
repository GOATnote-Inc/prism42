"""Shared pydantic contracts. Every inter-module value crosses these."""

from typing import Literal

from pydantic import BaseModel, Field


class BeatGrid(BaseModel):
    """librosa output for a single song."""

    path: str
    duration: float
    tempo: float
    beats: list[float]
    downbeats: list[float]
    energy: list[float]
    sections: list[dict]


class ClipProfile(BaseModel):
    """Technical profile of a video clip or still image."""

    clip_id: str
    path: str
    duration: float
    width: int
    height: int
    fps: float
    motion_energy: float
    brightness: float
    keyframe_paths: list[str]


class ClipTags(BaseModel):
    """Claude Opus 4.7's creative read of a clip."""

    clip_id: str
    mood: str
    energy: int = Field(ge=1, le=10)
    motion_type: Literal["static", "subtle", "tracking", "rapid", "chaotic"]
    subject: str
    best_use: Literal["intro", "build", "drop", "breakdown", "outro", "anywhere"]
    directors_note: str


class EditSegment(BaseModel):
    """One beat interval of the final edit."""

    clip_id: str
    source_start: float
    source_end: float
    beat_start: float
    beat_end: float
    cut_style: Literal["hard", "whip", "flash", "dip"]
    reasoning: str


class EditPlan(BaseModel):
    """Full edit plan for a single render."""

    song_path: str
    aspect: Literal["16:9", "9:16"]
    segments: list[EditSegment]
    directors_note: str
