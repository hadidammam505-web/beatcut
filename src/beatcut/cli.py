"""beatcut command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import __version__
from .ffmpeg import FFmpegError
from .grades import DESCRIPTIONS
from .plan import Plan, PlanError


def _dump(data, out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)


def _summary(offsets: list[dict]) -> str:
    vals = [o["offset_ms"] for o in offsets if o["offset_ms"] is not None]
    if not vals:
        return "no marks to compare against"
    a = np.abs(vals)
    return (f"{len(vals)} cuts: median |offset| {int(np.median(a))} ms, "
            f"worst {int(a.max())} ms, {int((a <= 40).sum())} within 40 ms")


# ---- commands -------------------------------------------------------------
def cmd_analyze(a) -> int:
    from .beats import align, analyze_audio
    from .cuts import detect_cuts

    res = detect_cuts(a.reference, crop=a.crop, threshold=a.threshold, min_shot=a.min_shot)
    data = {"reference": a.reference, "fps": res.fps, "duration": res.duration, "cuts": res.cuts,
            "shots": [{"start": s, "duration": d} for s, d in res.shots]}
    if not a.no_audio:
        try:
            b = analyze_audio(a.reference)
            data.update(tempo=b.tempo, beats=b.beats, onsets=b.onsets,
                        cut_to_onset=align(res.cuts, b.onsets))
            print(f"tempo {b.tempo} BPM; " + _summary(data["cut_to_onset"]), file=sys.stderr)
        except FFmpegError:
            print("no audio in the reference; skipped beats", file=sys.stderr)
    print(f"{len(res.cuts)} cuts, {len(res.shots)} shots in {res.duration}s", file=sys.stderr)
    _dump(data, a.output)
    return 0


def cmd_beats(a) -> int:
    from .beats import analyze_audio

    b = analyze_audio(a.audio, start=a.start, duration=a.duration)
    print(f"tempo {b.tempo} BPM, {len(b.beats)} beats, {len(b.onsets)} onsets", file=sys.stderr)
    _dump({"audio": a.audio, "tempo": b.tempo, "beats": b.beats, "onsets": b.onsets,
           "duration": b.duration}, a.output)
    return 0


def _load_cuts(src: str) -> list[float]:
    p = Path(src)
    if p.suffix.lower() == ".json" and p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        if "shots" in data and data["shots"] and "src" in data["shots"][0]:
            return Plan.from_dict(data, base_dir=p.parent).cut_times()
        return [float(c) for c in data["cuts"]]
    return [float(x) for x in src.replace(",", " ").split()]


def cmd_align(a) -> int:
    from .beats import align, analyze_audio

    cuts = _load_cuts(a.cuts)
    b = analyze_audio(a.audio, start=a.start)
    marks = b.beats if a.to == "beats" else b.onsets
    rows = align(cuts, marks)
    for r in rows:
        flag = "" if r["offset_ms"] is None or abs(r["offset_ms"]) <= 40 else "  <-- off"
        print(f"cut {r['cut']:8.3f}s  nearest {a.to[:-1]} {r['nearest']:8.3f}s  {r['offset_ms']:+5d} ms{flag}")
    print(_summary(rows))
    return 0


def cmd_scaffold(a) -> int:
    from .tools import list_clips, scaffold

    ref = json.loads(Path(a.analysis).read_text(encoding="utf-8"))
    lengths = [s["duration"] for s in ref["shots"]]
    out = Path(a.output)
    plan = scaffold(lengths, list_clips(a.clips), out.parent, song=a.song, song_start=a.song_start,
                    size=tuple(a.size), fps=a.fps, grade=a.grade)
    _dump(plan.to_dict(), str(out))
    print(f"{len(plan.shots)} shots, {plan.duration:.2f}s. Now set each shot's start to a real moment.",
          file=sys.stderr)
    return 0


def cmd_check(a) -> int:
    plan = Plan.load(a.plan)
    missing = [s.src for s in plan.shots if not plan.resolve(s.src).exists()]
    print(f"{len(plan.shots)} shots, {plan.total_frames} frames, {plan.duration:.2f}s "
          f"at {plan.size[0]}x{plan.size[1]} {plan.fps}fps, grade {plan.grade}")
    for m in missing:
        print(f"missing source: {m}")
    if plan.song and not a.no_audio and plan.resolve(plan.song.path).exists():
        from .beats import align, analyze_audio
        b = analyze_audio(str(plan.resolve(plan.song.path)), start=plan.song.start, duration=plan.duration + 1)
        print("cuts vs song onsets: " + _summary(align(plan.cut_times(), b.onsets)))
    return 1 if missing else 0


def cmd_build(a) -> int:
    from .render import RenderOptions, render

    plan = Plan.load(a.plan)
    out = render(plan, RenderOptions(preview=a.preview, force=a.force, preset=a.preset),
                 progress=lambda m: print(m, file=sys.stderr))
    if a.sheet:
        from .tools import contact_sheet
        sheet = contact_sheet(out, out.with_suffix(".sheet.png"))
        print(f"contact sheet: {sheet}", file=sys.stderr)
    return 0


def cmd_sheet(a) -> int:
    from .tools import contact_sheet

    out = a.output or str(Path(a.video).with_suffix(".sheet.png"))
    print(contact_sheet(a.video, out, cols=a.cols, rows=a.rows, width=a.width))
    return 0


def cmd_grades(_a) -> int:
    for name, desc in DESCRIPTIONS.items():
        print(f"{name:12s} {desc}")
    print(f"{'custom:...':12s} Any ffmpeg filter chain, e.g. custom:eq=contrast=1.2,hue=s=0.8")
    return 0


# ---- parser ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="beatcut",
        description="Copy a reference edit's cuts and rhythm, then render your own footage on the beat.")
    p.add_argument("--version", action="version", version=f"beatcut {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze", help="find the cuts, tempo and onsets of a reference edit")
    s.add_argument("reference")
    s.add_argument("-o", "--output", help="write JSON here (default: stdout)")
    s.add_argument("--crop", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                   help="compare only this area (fractions), e.g. the picture of a letterboxed edit")
    s.add_argument("--threshold", type=float, default=0.12, help="minimum frame difference for a cut (0-1)")
    s.add_argument("--min-shot", type=float, default=0.1, help="shortest shot in seconds")
    s.add_argument("--no-audio", action="store_true", help="skip tempo and onsets")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("beats", help="tempo, beat grid and onsets of a song")
    s.add_argument("audio")
    s.add_argument("-o", "--output")
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--duration", type=float)
    s.set_defaults(func=cmd_beats)

    s = sub.add_parser("align", help="how far each cut is from the nearest beat or onset")
    s.add_argument("cuts", help="plan.json, analysis.json, or a list like '0.5 1.2 2.0'")
    s.add_argument("audio")
    s.add_argument("--to", choices=("onsets", "beats"), default="onsets")
    s.add_argument("--start", type=float, default=0.0, help="where the edit starts in the song")
    s.set_defaults(func=cmd_align)

    s = sub.add_parser("scaffold", help="first plan from a reference analysis and a folder of clips")
    s.add_argument("analysis", help="JSON from 'beatcut analyze'")
    s.add_argument("clips", help="folder of source clips")
    s.add_argument("-o", "--output", default="plan.json")
    s.add_argument("--song")
    s.add_argument("--song-start", type=float, default=0.0)
    s.add_argument("--size", nargs=2, type=int, default=[1920, 1080], metavar=("W", "H"))
    s.add_argument("--fps", type=int, default=30)
    s.add_argument("--grade", default="dark")
    s.set_defaults(func=cmd_scaffold)

    s = sub.add_parser("check", help="validate a plan and measure its cuts against the song")
    s.add_argument("plan")
    s.add_argument("--no-audio", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("build", help="render a plan")
    s.add_argument("plan")
    s.add_argument("--preview", action="store_true", help="one-third size, fast encode")
    s.add_argument("--force", action="store_true", help="re-render every shot, ignoring the cache")
    s.add_argument("--preset", default="medium", help="x264 preset for the final render")
    s.add_argument("--sheet", action="store_true", help="also write a contact sheet of the result")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("sheet", help="contact sheet of a video, for checking an edit by eye")
    s.add_argument("video")
    s.add_argument("-o", "--output")
    s.add_argument("--cols", type=int, default=6)
    s.add_argument("--rows", type=int, default=4)
    s.add_argument("--width", type=int, default=320)
    s.set_defaults(func=cmd_sheet)

    s = sub.add_parser("grades", help="list colour grades")
    s.set_defaults(func=cmd_grades)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (PlanError, FFmpegError, FileNotFoundError, ValueError) as e:
        print(f"beatcut: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
