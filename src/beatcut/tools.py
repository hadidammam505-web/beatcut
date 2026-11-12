"""Helpers around the plan: scaffold a plan from a reference, and contact sheets for checking by eye."""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg
from .plan import Plan

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}


def list_clips(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    clips = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXT and p.is_file())
    if not clips:
        raise FileNotFoundError(f"no video files in {folder}")
    return clips


def scaffold(shot_lengths: list[float], clips: list[Path], plan_dir: Path, *, song: str | None = None,
             song_start: float = 0.0, size=(1920, 1080), fps: int = 30, grade: str = "dark",
             output: str = "edit.mp4") -> Plan:
    """A first plan: one shot per reference shot, same lengths, clips used in turn.

    In points are spread through each clip so repeated uses show different moments. It is a
    starting point: pick the real moments (full, hard reps) by editing ``start`` afterwards.
    """
    if not shot_lengths:
        raise ValueError("the reference has no shots")
    durations = {c: ffmpeg.probe(c)["duration"] for c in clips}
    uses = {c: 0 for c in clips}
    total_uses = {c: 0 for c in clips}
    for k in range(len(shot_lengths)):
        total_uses[clips[k % len(clips)]] += 1
    shots = []
    for k, length in enumerate(shot_lengths):
        c = clips[k % len(clips)]
        span = max(0.0, durations[c] - length)
        start = span * (uses[c] + 0.5) / total_uses[c] if total_uses[c] else 0.0
        uses[c] += 1
        try:
            src = str(c.resolve().relative_to(plan_dir.resolve())).replace("\\", "/")
        except ValueError:
            src = str(c.resolve())
        shots.append({"src": src, "start": round(start, 3), "duration": round(length, 4),
                      "motion": "none", "transition": "cut"})
    data = {"output": output, "size": list(size), "fps": fps, "grade": grade, "shots": shots}
    if song:
        data["song"] = {"path": song, "start": song_start, "gain_db": 0, "fade_out": 0.5}
    return Plan.from_dict(data, base_dir=plan_dir)


def contact_sheet(video: str | Path, out: str | Path, cols: int = 6, rows: int = 4, width: int = 320) -> Path:
    """One image with ``cols * rows`` evenly spaced frames of ``video``."""
    info = ffmpeg.probe(video)
    dur = info["duration"] or 1.0
    n = cols * rows
    rate = n / dur
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(video), "-an", "-vf",
                f"fps={rate:.6f},scale={width}:-2,tile={cols}x{rows}:padding=4:margin=4:color=black",
                "-frames:v", "1", str(out)])
    return out
