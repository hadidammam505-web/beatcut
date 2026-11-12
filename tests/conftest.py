import shutil
import subprocess
import wave

import numpy as np
import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not on PATH")


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def write_clicks(path, bpm=120.0, offset=0.25, seconds=8.0, sr=22050, noise=0.01):
    """A click track: alternating low and high clicks, accented every 4 beats."""
    y = np.zeros(int(sr * seconds), np.float32)
    k = np.arange(int(0.03 * sr))
    times = np.arange(offset, seconds, 60.0 / bpm)
    for i, t in enumerate(times):
        n = int(t * sr)
        amp = 1.0 if i % 4 == 0 else 0.6
        click = amp * np.sin(2 * np.pi * (1000 if i % 2 else 150) * k / sr) * np.exp(-k / (0.006 * sr))
        end = min(y.size, n + k.size)
        y[n:end] += click[: end - n]
    y += noise * np.random.default_rng(0).standard_normal(y.size).astype(np.float32)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return times


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """Synthetic reference edit (cuts at 1.0 s and 2.5 s), two source clips and a 120 BPM song."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not on PATH")
    d = tmp_path_factory.mktemp("media")
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1",
       "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=1.5",
       "-f", "lavfi", "-i", "mandelbrot=s=320x180:r=30",
       "-filter_complex", "[2]trim=duration=1,setpts=PTS-STARTPTS[m];[0][1][m]concat=n=3:v=1[v]",
       "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "ref.mp4"))
    (d / "clips").mkdir()
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(d / "clips" / "a.mp4"))
    ff("-f", "lavfi", "-i", "smptehdbars=s=320x180:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(d / "clips" / "b.mp4"))
    clicks = write_clicks(d / "song.wav")
    return {"dir": d, "ref": d / "ref.mp4", "song": d / "song.wav", "clicks": clicks}
