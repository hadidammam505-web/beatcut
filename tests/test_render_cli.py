import json
import subprocess

from beatcut.cli import main
from beatcut.ffmpeg import probe
from beatcut.plan import Plan
from beatcut.render import RenderOptions, render

from .conftest import needs_ffmpeg


def frame_count(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def write_plan(d, **kw):
    data = {"output": "out/edit.mp4", "size": [320, 180], "fps": 30, "grade": "dark",
            "song": {"path": "song.wav", "start": 0.25},
            "shots": [
                {"src": "clips/a.mp4", "start": 0.5, "duration": 0.5, "motion": "push", "transition": "flash"},
                {"src": "clips/b.mp4", "start": 1, "duration": 0.5, "motion": "punch", "transition": "fade",
                 "crop": {"size": 0.6, "x": 0.2, "y": 0.2}},
                {"src": "clips/a.mp4", "start": 3, "duration": 1.0, "motion": "pull", "grade": "mono"},
                {"src": "clips/b.mp4", "start": 5.9, "duration": 0.5},   # runs past the end of the clip
                {"src": "clips/a.mp4", "start": 2, "duration": 1 / 30},  # a single frame
            ]}
    data.update(kw)
    f = d / "plan.json"
    f.write_text(json.dumps(data))
    return f


@needs_ffmpeg
def test_render_exact_frames_audio_and_cache(media):
    plan = Plan.load(write_plan(media["dir"]))
    msgs = []
    out = render(plan, RenderOptions(preset="ultrafast"), progress=msgs.append)
    info = probe(out)
    assert frame_count(out) == plan.total_frames == 76
    assert (info["width"], info["height"]) == (320, 180)
    assert info["has_audio"]
    assert abs(info["duration"] - plan.duration) < 0.06

    msgs.clear()
    render(plan, RenderOptions(preset="ultrafast"), progress=msgs.append)
    assert sum("cached" in m for m in msgs) == 5


@needs_ffmpeg
def test_preview_build_and_sheet_via_cli(media):
    f = write_plan(media["dir"], output="out/cli.mp4")
    assert main(["build", str(f), "--preview", "--sheet"]) == 0
    prev = media["dir"] / "out" / "cli.preview.mp4"
    assert prev.exists() and (media["dir"] / "out" / "cli.preview.sheet.png").exists()
    assert probe(prev)["width"] == 106  # one third of 320, rounded to even


@needs_ffmpeg
def test_analyze_scaffold_check(media, tmp_path):
    an = tmp_path / "an.json"
    assert main(["analyze", str(media["ref"]), "-o", str(an), "--no-audio"]) == 0
    assert json.loads(an.read_text())["cuts"] == [1.0, 2.5]

    plan = media["dir"] / "scaffold.json"
    assert main(["scaffold", str(an), str(media["dir"] / "clips"), "-o", str(plan),
                 "--song", "song.wav", "--size", "320", "180"]) == 0
    p = Plan.load(plan)
    assert [s.duration for s in p.shots] == [1.0, 1.5, 1.0]
    assert [s.src for s in p.shots] == ["clips/a.mp4", "clips/b.mp4", "clips/a.mp4"]
    assert p.shots[0].start != p.shots[2].start   # a repeated clip shows a different moment
    assert main(["check", str(plan)]) == 0


def test_errors_are_reported_not_raised(tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text('{"shots": []}')
    assert main(["check", str(f)]) == 2
    assert "non-empty" in capsys.readouterr().err


def test_grades_command(capsys):
    assert main(["grades"]) == 0
    assert "dark-vivid" in capsys.readouterr().out
