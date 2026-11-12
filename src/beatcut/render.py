"""Render an edit plan with ffmpeg.

Each shot becomes its own segment file with exactly the planned number of frames, then the
segments are joined with the concat *filter* and the song is laid under them. Joining with the
concat demuxer and stream copy looked fine but dropped one-frame segments and stretched frozen
ones by a frame, so every segment is re-timed and filtered instead.

Segments are cached by a hash of everything that affects them, so changing one shot re-renders
only that shot.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .grades import grade_filter
from .plan import Plan, Shot

FLASH_OUT, FLASH_IN = 3, 5     # frames: fade to white at the end of a shot, in from white after the cut
FADE_OUT, FADE_IN = 4, 4       # frames: dip to black


@dataclass
class RenderOptions:
    preview: bool = False          # one-third size, fast encode
    workdir: Path | None = None
    force: bool = False            # ignore the segment cache
    preset: str = "medium"


def _even(n: float) -> int:
    return max(16, int(round(n / 2)) * 2)


def output_size(plan: Plan, preview: bool) -> tuple[int, int]:
    w, h = plan.size
    return (_even(w / 3), _even(h / 3)) if preview else (w, h)


def motion_filter(motion: str, frames: int, fps: int, size: tuple[int, int]) -> str:
    """zoompan expression for a shot's camera move; ``on`` is the output frame number."""
    if motion == "none":
        return ""
    w, h = size
    n = max(frames - 1, 1)
    if motion == "push":           # slow push-in across the shot
        z = f"1+0.08*on/{n}"
    elif motion == "pull":         # starts close and eases out to reveal the whole rep
        z = f"1+0.6*pow(1-min(1\\,on/({n}*0.8))\\,2)"
    elif motion == "punch":        # fast punch-in over 0.35 s, then hold
        p = max(1, int(0.35 * fps + 0.5))   # round half up: round() would give 10 frames at 30 fps
        z = f"1+0.25*min(1\\,on/{p})"
    else:
        raise ValueError(motion)
    return (f"zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}")


def shot_filters(plan: Plan, i: int, size: tuple[int, int]) -> str:
    """The full -vf chain for shot ``i``."""
    shot: Shot = plan.shots[i]
    prev = plan.shots[i - 1] if i else None
    fps, frames = plan.fps, plan.frames(shot)
    w, h = size
    c = shot.crop
    parts = []
    if shot.speed != 1.0:
        parts.append(f"setpts=PTS/{shot.speed}")
    if (c.size, c.x, c.y) != (1.0, 0.0, 0.0):
        parts.append(f"crop=trunc(iw*{c.size}/2)*2:trunc(ih*{c.size}/2)*2:iw*{c.x}:ih*{c.y}")
    parts += [f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
              f"crop={w}:{h}", "setsar=1", f"fps={fps}",
              f"tpad=stop_mode=clone:stop={frames}"]   # a source that ends early holds its last frame
    mf = motion_filter(shot.motion, frames, fps, size)
    if mf:
        parts.append(mf)
    g = grade_filter(shot.grade if shot.grade is not None else plan.grade)
    if g:
        parts.append(g)
    if prev is not None and prev.transition == "flash":
        parts.append(f"fade=t=in:s=0:n={min(FLASH_IN, frames)}:color=white")
    if prev is not None and prev.transition == "fade":
        parts.append(f"fade=t=in:s=0:n={min(FADE_IN, frames)}")
    if shot.transition == "flash" and i < len(plan.shots) - 1:
        n = min(FLASH_OUT, frames)
        parts.append(f"fade=t=out:s={frames - n}:n={n}:color=white")
    if shot.transition == "fade" and i < len(plan.shots) - 1:
        n = min(FADE_OUT, frames)
        parts.append(f"fade=t=out:s={frames - n}:n={n}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def _segment_args(plan: Plan, i: int, size, opts: RenderOptions, out: Path) -> list[str]:
    shot = plan.shots[i]
    frames = plan.frames(shot)
    src_len = frames / plan.fps * shot.speed + 0.5
    crf = 28 if opts.preview else plan.crf
    preset = "ultrafast" if opts.preview else opts.preset
    return ["-ss", f"{shot.start:.4f}", "-t", f"{src_len:.4f}", "-i", str(plan.resolve(shot.src)),
            "-an", "-vf", shot_filters(plan, i, size), "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-r", str(plan.fps), str(out)]


def _key(args: list[str], src: Path) -> str:
    st = src.stat()
    blob = json.dumps([args[:-1], str(src.resolve()), st.st_size, int(st.st_mtime)])
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def render(plan: Plan, opts: RenderOptions | None = None,
           progress: Callable[[str], None] | None = None) -> Path:
    """Render ``plan`` and return the output path."""
    opts = opts or RenderOptions()
    say = progress or (lambda _m: None)
    size = output_size(plan, opts.preview)
    out = plan.resolve(plan.output)
    if opts.preview:
        out = out.with_name(out.stem + ".preview" + out.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(opts.workdir) if opts.workdir else out.parent / "beatcut-work"
    work.mkdir(parents=True, exist_ok=True)

    for s in plan.shots:
        if not plan.resolve(s.src).exists():
            raise FileNotFoundError(f"source not found: {plan.resolve(s.src)}")

    segs: list[Path] = []
    for i in range(len(plan.shots)):
        src = plan.resolve(plan.shots[i].src)
        probe_args = _segment_args(plan, i, size, opts, Path("x.mp4"))
        seg = work / f"seg{i + 1:03d}-{_key(probe_args, src)}.mp4"
        if seg.exists() and not opts.force:
            say(f"shot {i + 1}/{len(plan.shots)} cached")
        else:
            say(f"shot {i + 1}/{len(plan.shots)} rendering")
            tmp = seg.with_suffix(".tmp.mp4")
            ffmpeg.run(_segment_args(plan, i, size, opts, tmp))
            os.replace(tmp, seg)
        segs.append(seg)

    say("joining")
    args: list[str] = []
    for s in segs:
        args += ["-i", str(s)]
    n = len(segs)
    graph = "".join(f"[{k}:v]setpts=PTS-STARTPTS[v{k}];" for k in range(n))
    graph += "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    total = plan.duration
    maps = ["-map", "[v]"]
    if plan.song:
        song = plan.song
        args += ["-ss", f"{song.start:.4f}", "-t", f"{total:.4f}", "-i", str(plan.resolve(song.path))]
        af = f"[{n}:a]atrim=duration={total:.4f},asetpts=PTS-STARTPTS,volume={song.gain_db}dB"
        if song.fade_out > 0:
            af += f",afade=t=out:st={max(0.0, total - song.fade_out):.4f}:d={song.fade_out:.4f}"
        graph += ";" + af + ",apad[a]"
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "256k", "-t", f"{total:.4f}"]
    crf = 28 if opts.preview else plan.crf
    ffmpeg.run([*args, "-filter_complex", graph, *maps, "-frames:v", str(plan.total_frames),
                "-c:v", "libx264", "-preset", "ultrafast" if opts.preview else opts.preset,
                "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(plan.fps),
                "-movflags", "+faststart", str(out)])
    say(f"done: {out}")
    return out
