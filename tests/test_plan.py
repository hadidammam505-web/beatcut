import json

import pytest

from beatcut.plan import Plan, PlanError


def shots(*durs, **extra):
    return [{"src": "a.mp4", "start": 0, "duration": d, **extra} for d in durs]


def test_frames_and_cut_times():
    p = Plan.from_dict({"fps": 30, "shots": shots(0.5, 1.0, 0.0334)})
    assert [p.frames(s) for s in p.shots] == [15, 30, 1]
    assert p.total_frames == 46
    assert p.cut_times() == [0.5, 1.5]


def test_song_as_string_and_defaults():
    p = Plan.from_dict({"song": "s.wav", "shots": shots(1)})
    assert p.song.path == "s.wav" and p.song.fade_out == 0.5
    assert p.size == (1920, 1080) and p.grade == "none"


@pytest.mark.parametrize("bad, msg", [
    ({"shots": []}, "non-empty"),
    ({"shots": [{"src": "a", "start": 0}]}, "missing duration"),
    ({"shots": shots(1, motion="spin")}, "motion"),
    ({"shots": shots(1, transition="wipe")}, "transition"),
    ({"shots": shots(0.001)}, "shorter than one frame"),
    ({"size": [1921, 1080], "shots": shots(1)}, "even"),
    ({"grade": "sepia-ish", "shots": shots(1)}, "unknown grade"),
    ({"shots": shots(1, crop={"size": 0.5, "x": 0.6})}, "outside the frame"),
    ({"shots": shots(1, speed=10)}, "speed"),
])
def test_invalid_plans(bad, msg):
    with pytest.raises(PlanError, match=msg):
        Plan.from_dict(bad)


def test_custom_grade_is_accepted():
    Plan.from_dict({"grade": "custom:hue=s=0", "shots": shots(1)})


def test_round_trip(tmp_path):
    src = {"output": "o.mp4", "size": [640, 360], "fps": 25, "grade": "dark",
           "song": {"path": "s.wav", "start": 1.5, "gain_db": -3, "fade_out": 1},
           "shots": shots(1, motion="push", transition="flash", crop={"size": 0.8, "x": 0.1, "y": 0.1})}
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(src))
    p = Plan.load(f)
    again = Plan.from_dict(p.to_dict(), base_dir=tmp_path)
    assert again.to_dict() == p.to_dict()
    assert p.resolve("a.mp4") == tmp_path / "a.mp4"


def test_bad_json(tmp_path):
    f = tmp_path / "plan.json"
    f.write_text("{nope")
    with pytest.raises(PlanError, match="not valid JSON"):
        Plan.load(f)
