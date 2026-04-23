from prism.models import BeatGrid, ClipTags, EditPlan, EditSegment


def test_beat_grid_roundtrip():
    g = BeatGrid(
        path="/a.mp3",
        duration=10.0,
        tempo=120.0,
        beats=[0.0, 0.5, 1.0],
        downbeats=[0.0],
        energy=[0.8, 0.6, 0.4],
        sections=[{"start": 0.0, "end": 10.0, "label": "section_1"}],
    )
    j = g.model_dump_json()
    assert BeatGrid.model_validate_json(j) == g


def test_edit_plan_validates_enum():
    seg = EditSegment(
        clip_id="abc",
        source_start=0.0, source_end=0.5,
        beat_start=0.0, beat_end=0.5,
        cut_style="hard",
        reasoning="test",
    )
    EditPlan(
        song_path="/a.mp3",
        aspect="16:9",
        segments=[seg],
        directors_note="",
    )


def test_clip_tags_energy_range():
    t = ClipTags(
        clip_id="x", mood="calm", energy=5, motion_type="static",
        subject="tree", best_use="intro", directors_note="ok",
    )
    assert 1 <= t.energy <= 10
