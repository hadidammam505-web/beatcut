"""Onsets, tempo and a beat grid from audio, with numpy only.

This is deliberately small: spectral-flux onsets, tempo from the autocorrelation of the onset
envelope, and a beat grid placed at the phase that best matches the onsets. It is accurate on
the steady, drum-led music that gym and montage edits use. For songs with rubato, check by ear.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import ffmpeg

SR = 22050
N_FFT = 1024
HOP = 256


@dataclass
class BeatResult:
    tempo: float
    beats: list[float]
    onsets: list[float]
    duration: float


def load_audio(path: str, sr: int = SR, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    args = []
    if start:
        args += ["-ss", f"{start}"]
    args += ["-i", path]
    if duration:
        args += ["-t", f"{duration}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = ffmpeg.run(args, capture=True)
    return np.frombuffer(raw, np.float32).copy()


def onset_envelope(y: np.ndarray, sr: int = SR, hop: int = HOP) -> np.ndarray:
    """Half-wave rectified spectral flux of the log magnitude spectrum, one value per hop."""
    # centre each window on its hop, so frame i describes time i * hop / sr
    y = np.pad(y, (N_FFT // 2, N_FFT // 2), mode="reflect" if y.size > N_FFT else "constant")
    win = np.hanning(N_FFT).astype(np.float32)
    n = 1 + (y.size - N_FFT) // hop
    idx = np.arange(N_FFT)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * win, axis=1))
    logm = np.log1p(100.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    env = np.concatenate([[0.0], flux])
    # remove the slowly varying floor (noise, pads, reverb) with a running median
    k = max(3, int(0.5 * sr / hop) | 1)
    padded = np.pad(env, (k // 2, k // 2), mode="edge")
    floor = np.median(np.lib.stride_tricks.sliding_window_view(padded, k), axis=1)
    env = np.maximum(0.0, env - floor)
    env[: 2] = 0.0  # the first frames only see the file starting, not a hit
    peak = env.max()
    return env / peak if peak > 0 else env


def pick_onsets(env: np.ndarray, sr: int = SR, hop: int = HOP, delta: float = 0.15,
                wait: float = 0.05) -> np.ndarray:
    """Local maxima of ``env`` that rise ``delta`` above the local mean. Returns seconds."""
    fr = sr / hop
    pre = max(1, int(0.03 * fr))
    avg = max(1, int(0.1 * fr))
    gap = max(1, int(wait * fr))
    out, last = [], -gap
    for i in range(1, len(env) - 1):
        lo, hi = max(0, i - pre), min(len(env), i + pre + 1)
        if env[i] < env[lo:hi].max():
            continue
        if env[i] < env[max(0, i - avg):min(len(env), i + avg + 1)].mean() + delta:
            continue
        if i - last < gap:
            continue
        out.append(i)
        last = i
    return np.asarray(out) * hop / sr


def estimate_tempo(env: np.ndarray, sr: int = SR, hop: int = HOP, lo: float = 60, hi: float = 200) -> float:
    """BPM from the autocorrelation of the onset envelope, preferring 80-180 BPM."""
    fr = sr / hop
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(len(ac))
    valid = (lags >= fr * 60 / hi) & (lags <= fr * 60 / lo)
    if not valid.any() or ac[0] <= 0:
        return 0.0
    bpm = 60 * fr / np.maximum(lags, 1)
    # mild log-Gaussian prior around 120 BPM settles octave ambiguity
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = np.where(valid, ac * prior, -np.inf)
    lag = int(np.argmax(score))
    # parabolic refinement for sub-frame accuracy
    if 1 <= lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        if den:
            lag = lag + 0.5 * (a - c) / den
    return float(60 * fr / lag)


def beat_grid(env: np.ndarray, tempo: float, duration: float, sr: int = SR, hop: int = HOP) -> list[float]:
    """Evenly spaced beats at ``tempo``, shifted to the phase with the most onset energy."""
    if tempo <= 0:
        return []
    fr = sr / hop
    period = 60.0 / tempo
    phases = np.linspace(0, period, 64, endpoint=False)
    best, best_phase = -1.0, 0.0
    for ph in phases:
        ts = np.arange(ph, duration, period)
        idx = np.clip(np.round(ts * fr).astype(int), 0, len(env) - 1)
        s = env[idx].sum()
        if s > best:
            best, best_phase = s, ph
    return [round(float(t), 4) for t in np.arange(best_phase, duration, period)]


def analyze_audio(path: str, start: float = 0.0, duration: float | None = None) -> BeatResult:
    y = load_audio(path, start=start, duration=duration)
    if y.size == 0:
        raise ffmpeg.FFmpegError(f"{path} has no audio")
    dur = y.size / SR
    env = onset_envelope(y)
    tempo = estimate_tempo(env)
    return BeatResult(
        tempo=round(tempo, 2),
        beats=beat_grid(env, tempo, dur),
        onsets=[round(float(t), 4) for t in pick_onsets(env)],
        duration=round(dur, 4),
    )


def align(cuts: list[float], marks: list[float]) -> list[dict]:
    """For each cut, the nearest mark and the offset in ms (positive: the cut is late)."""
    m = np.asarray(marks, float)
    out = []
    for c in cuts:
        if m.size == 0:
            out.append({"cut": c, "nearest": None, "offset_ms": None})
            continue
        j = int(np.argmin(np.abs(m - c)))
        out.append({"cut": round(c, 4), "nearest": round(float(m[j]), 4),
                    "offset_ms": int(round((c - m[j]) * 1000))})
    return out
