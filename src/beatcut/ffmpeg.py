"""Find and run ffmpeg / ffprobe."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe failed, or could not be found."""


def _find(name: str) -> str:
    env = os.environ.get("BEATCUT_" + name.upper())
    if env:
        return env
    if name == "ffprobe" and os.environ.get("BEATCUT_FFMPEG"):
        sibling = Path(os.environ["BEATCUT_FFMPEG"]).with_name(
            "ffprobe" + Path(os.environ["BEATCUT_FFMPEG"]).suffix
        )
        if sibling.exists():
            return str(sibling)
    found = shutil.which(name)
    if not found:
        raise FFmpegError(
            f"{name} not found. Install ffmpeg and put it on PATH, or set BEATCUT_{name.upper()}."
        )
    return found


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")


def run(args: list[str], *, capture: bool = False) -> bytes:
    """Run ffmpeg with ``args``. Returns stdout when ``capture`` is set."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE)
    if proc.returncode:
        tail = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}):\n{tail}")
    return proc.stdout if capture else b""


def probe(path: str | os.PathLike) -> dict:
    """Return duration, fps, size and whether the file has audio / video."""
    cmd = [ffprobe_bin(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode:
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.decode('utf-8', 'replace')}")
    data = json.loads(proc.stdout)
    info: dict = {"duration": float(data.get("format", {}).get("duration", 0) or 0),
                  "has_video": False, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            w, h = int(s.get("width", 0)), int(s.get("height", 0))
            rot = _rotation(s)
            if rot in (90, 270):
                w, h = h, w
            info["width"], info["height"] = w, h
            info["fps"] = _rate(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1")
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def _rate(text: str) -> float:
    num, _, den = text.partition("/")
    try:
        return float(num) / float(den or 1) if float(den or 1) else 0.0
    except ValueError:
        return 0.0


def _rotation(stream: dict) -> int:
    """Phones store portrait clips as landscape plus a rotation tag; ffmpeg auto-rotates on decode."""
    tags = stream.get("tags", {})
    if "rotate" in tags:
        return abs(int(float(tags["rotate"]))) % 360
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return abs(int(float(side["rotation"]))) % 360
    return 0
