import numpy as np

from beatcut.beats import align, analyze_audio, estimate_tempo
from beatcut.cuts import detect_cuts, frame_scores, pick_cuts

from .conftest import needs_ffmpeg


def test_pick_cuts_ignores_steady_motion():
    rng = np.random.default_rng(1)
    scores = 0.05 + 0.01 * rng.random(90)   # constant motion: never a cut
    scores[30] = scores[60] = 0.5
    assert pick_cuts(scores, 30) == [30, 60]


def test_pick_cuts_min_shot_keeps_strongest():
    scores = np.zeros(60)
    scores[20], scores[21] = 0.4, 0.6
    assert pick_cuts(scores, 30, min_shot=0.2) == [21]


def test_frame_scores_shape():
    frames = np.zeros((5, 10, 10), np.uint8)
    frames[3:] = 255
    s = frame_scores(frames)
    assert s.shape == (5,) and s[0] == 0 and s.argmax() == 3


def test_align_signs():
    rows = align([1.0, 2.04], [0.98, 2.0])
    assert [r["offset_ms"] for r in rows] == [20, 40]
    assert align([1.0], [])[0]["nearest"] is None


def test_tempo_from_synthetic_envelope():
    fr = 22050 / 256
    env = np.zeros(int(fr * 10))
    env[(np.arange(0, 10, 0.5) * fr).astype(int)] = 1.0     # 120 BPM impulses
    assert abs(estimate_tempo(env) - 120) < 1.5


@needs_ffmpeg
def test_detect_cuts_exact(media):
    r = detect_cuts(str(media["ref"]))
    assert r.cuts == [1.0, 2.5]
    assert r.shots == [(0.0, 1.0), (1.0, 1.5), (2.5, 1.0)]


@needs_ffmpeg
def test_crop_still_finds_cuts(media):
    r = detect_cuts(str(media["ref"]), crop=(0.0, 0.0, 0.5, 0.5))
    assert r.cuts == [1.0, 2.5]


@needs_ffmpeg
def test_beats_and_onsets(media):
    b = analyze_audio(str(media["song"]))
    assert abs(b.tempo - 120) < 1.0
    on = np.array(b.onsets)
    hits = [np.min(np.abs(on - t)) for t in media["clicks"]]
    assert max(hits) < 0.025, "every click found within 25 ms"
    assert len(on) == len(media["clicks"]), "no false onsets"
    assert np.min(np.abs(np.array(b.beats) - 0.25)) < 0.03
