"""Find the cuts in a reference edit.

Frames are decoded small and grey by ffmpeg and compared with numpy. A cut is a frame whose
difference from the previous one is both large in absolute terms and much larger than the
local median, so fast camera motion inside one shot is not mistaken for a cut.

``crop`` limits the comparison to the picture area of a letterboxed reference: black bars
never change, and on a letterboxed edit they hid every cut from whole-frame detectors.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import ffmpeg

W, H = 96, 54


@dataclass
class CutResult:
    cuts: list[float]          # seconds, start of each new shot
    fps: float
    duration: float
    scores: np.ndarray         # per-frame difference, 0..1

    @property
    def shots(self) -> list[tuple[float, float]]:
        """(start, length) of every shot."""
        edges = [0.0, *self.cuts, self.duration]
        return [(round(a, 4), round(b - a, 4)) for a, b in zip(edges, edges[1:]) if b - a > 0]


def read_frames(path: str, crop: tuple[float, float, float, float] | None = None,
                fps: float | None = None) -> tuple[np.ndarray, float]:
    """Decode ``path`` to a (frames, H, W) uint8 array. ``crop`` is x0, y0, x1, y1 as fractions."""
    info = ffmpeg.probe(path)
    if not info["has_video"]:
        raise ffmpeg.FFmpegError(f"{path} has no video stream")
    rate = fps or info.get("fps") or 30.0
    vf = []
    if crop:
        x0, y0, x1, y1 = crop
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("crop must be fractions with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
        vf.append(f"crop=iw*{x1 - x0}:ih*{y1 - y0}:iw*{x0}:ih*{y0}")
    vf += [f"fps={rate}", f"scale={W}:{H}:flags=area", "format=gray"]
    raw = ffmpeg.run(["-i", path, "-an", "-vf", ",".join(vf), "-f", "rawvideo", "-"], capture=True)
    frames = np.frombuffer(raw, np.uint8)
    n = frames.size // (W * H)
    return frames[: n * W * H].reshape(n, H, W), float(rate)


def frame_scores(frames: np.ndarray) -> np.ndarray:
    """Difference of each frame from the previous one, 0..1. Element 0 is always 0.

    Mixes the mean absolute pixel change with the change of the brightness histogram, which
    catches cuts between shots of similar layout but different light.
    """
    if len(frames) < 2:
        return np.zeros(len(frames))
    f = frames.astype(np.float32)
    pix = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)) / 255.0
    hist = np.stack([np.histogram(x, bins=32, range=(0, 256))[0] for x in frames]).astype(np.float32)
    hist /= hist.sum(axis=1, keepdims=True)
    hd = 0.5 * np.abs(np.diff(hist, axis=0)).sum(axis=1)
    return np.concatenate([[0.0], 0.6 * pix + 0.4 * hd])


def pick_cuts(scores: np.ndarray, fps: float, threshold: float = 0.12, ratio: float = 3.0,
              min_shot: float = 0.1, window: int = 15) -> list[int]:
    """Frame indices where a new shot starts."""
    n = len(scores)
    if n < 2:
        return []
    min_gap = max(1, int(round(min_shot * fps)))
    cuts: list[int] = []
    for i in range(1, n):
        s = scores[i]
        if s < threshold:
            continue
        lo, hi = max(1, i - window), min(n, i + window + 1)
        neigh = np.concatenate([scores[lo:i], scores[i + 1:hi]])
        local = float(np.median(neigh)) if neigh.size else 0.0
        if s < ratio * max(local, 0.01):
            continue
        if not (s >= scores[i - 1] and (i + 1 >= n or s >= scores[i + 1])):
            continue
        if cuts and i - cuts[-1] < min_gap:
            if s > scores[cuts[-1]]:
                cuts[-1] = i
            continue
        cuts.append(i)
    return cuts


def detect_cuts(path: str, crop=None, threshold: float = 0.12, ratio: float = 3.0,
                min_shot: float = 0.1) -> CutResult:
    frames, fps = read_frames(path, crop)
    scores = frame_scores(frames)
    idx = pick_cuts(scores, fps, threshold, ratio, min_shot)
    return CutResult(cuts=[round(i / fps, 4) for i in idx], fps=fps, duration=round(len(frames) / fps, 4),
                     scores=scores)
