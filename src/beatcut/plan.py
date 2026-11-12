"""The edit plan: a JSON file that describes every shot of an edit.

Example::

    {
      "output": "out/edit.mp4",
      "size": [1920, 1080],
      "fps": 30,
      "grade": "dark",
      "song": {"path": "song.wav", "start": 0, "gain_db": 0, "fade_out": 0.5},
      "shots": [
        {"src": "clips/squat.mov", "start": 22.7, "duration": 0.7,
         "crop": {"size": 0.8, "x": 0.05, "y": 0.08}, "motion": "push", "transition": "flash"},
        {"src": "clips/bench.mov", "start": 4.0, "duration": 1.1}
      ]
    }

Relative paths are resolved against the folder that holds the plan file.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .grades import grade_filter

MOTIONS = ("none", "push", "pull", "punch")
TRANSITIONS = ("cut", "flash", "fade")


class PlanError(ValueError):
    """The plan file is not valid."""


@dataclass
class Crop:
    """A square-ratio crop as fractions of the source frame: ``size`` of width/height, top-left at x, y."""

    size: float = 1.0
    x: float = 0.0
    y: float = 0.0

    def validate(self, where: str) -> None:
        if not 0.05 <= self.size <= 1.0:
            raise PlanError(f"{where}: crop.size must be between 0.05 and 1, got {self.size}")
        for k in ("x", "y"):
            v = getattr(self, k)
            if not 0.0 <= v <= 1.0 - self.size + 1e-9:
                raise PlanError(f"{where}: crop.{k}={v} puts the crop outside the frame (size {self.size})")


@dataclass
class Shot:
    src: str
    start: float
    duration: float
    crop: Crop = field(default_factory=Crop)
    motion: str = "none"
    transition: str = "cut"
    grade: str | None = None
    speed: float = 1.0

    def validate(self, i: int, fps: int) -> None:
        where = f"shot {i + 1}"
        if self.start < 0:
            raise PlanError(f"{where}: start must be >= 0")
        if self.duration * fps < 1:
            raise PlanError(f"{where}: duration {self.duration}s is shorter than one frame")
        if self.motion not in MOTIONS:
            raise PlanError(f"{where}: motion must be one of {MOTIONS}, got {self.motion!r}")
        if self.transition not in TRANSITIONS:
            raise PlanError(f"{where}: transition must be one of {TRANSITIONS}, got {self.transition!r}")
        if not 0.1 <= self.speed <= 4:
            raise PlanError(f"{where}: speed must be between 0.1 and 4")
        if self.grade is not None:
            try:
                grade_filter(self.grade)
            except KeyError as e:
                raise PlanError(f"{where}: {e.args[0]}") from None
        self.crop.validate(where)


@dataclass
class Song:
    path: str
    start: float = 0.0
    gain_db: float = 0.0
    fade_out: float = 0.5


@dataclass
class Plan:
    shots: list[Shot]
    output: str = "edit.mp4"
    size: tuple[int, int] = (1920, 1080)
    fps: int = 30
    grade: str = "none"
    song: Song | None = None
    crf: int = 16
    base_dir: Path = field(default=Path("."), repr=False)

    # ---- loading -------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict, base_dir: Path | str = ".") -> Plan:
        if not isinstance(data, dict):
            raise PlanError("plan must be a JSON object")
        raw_shots = data.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise PlanError("plan needs a non-empty 'shots' list")
        shots = []
        for i, s in enumerate(raw_shots):
            if not isinstance(s, dict):
                raise PlanError(f"shot {i + 1} must be an object")
            missing = [k for k in ("src", "start", "duration") if k not in s]
            if missing:
                raise PlanError(f"shot {i + 1} is missing {', '.join(missing)}")
            crop = s.get("crop") or {}
            shots.append(Shot(
                src=str(s["src"]), start=float(s["start"]), duration=float(s["duration"]),
                crop=Crop(**{k: float(v) for k, v in crop.items() if k in ("size", "x", "y")}),
                motion=s.get("motion", "none"), transition=s.get("transition", "cut"),
                grade=s.get("grade"), speed=float(s.get("speed", 1.0)),
            ))
        song = data.get("song")
        if isinstance(song, str):
            song = {"path": song}
        size = data.get("size", (1920, 1080))
        plan = cls(
            shots=shots,
            output=str(data.get("output", "edit.mp4")),
            size=(int(size[0]), int(size[1])),
            fps=int(data.get("fps", 30)),
            grade=str(data.get("grade", "none")),
            song=Song(**song) if song else None,
            crf=int(data.get("crf", 16)),
            base_dir=Path(base_dir),
        )
        plan.validate()
        return plan

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise PlanError(f"{path} is not valid JSON: {e}") from None
        return cls.from_dict(data, base_dir=path.parent)

    # ---- checks and helpers ---------------------------------------------
    def validate(self) -> None:
        w, h = self.size
        if w % 2 or h % 2 or w < 16 or h < 16:
            raise PlanError(f"size must be even and at least 16x16, got {w}x{h}")
        if not 1 <= self.fps <= 120:
            raise PlanError("fps must be between 1 and 120")
        try:
            grade_filter(self.grade)
        except KeyError as e:
            raise PlanError(e.args[0]) from None
        for i, s in enumerate(self.shots):
            s.validate(i, self.fps)

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (self.base_dir / path)

    def frames(self, shot: Shot) -> int:
        return max(1, round(shot.duration * self.fps))

    @property
    def total_frames(self) -> int:
        return sum(self.frames(s) for s in self.shots)

    @property
    def duration(self) -> float:
        return self.total_frames / self.fps

    def cut_times(self) -> list[float]:
        """Time of every cut (the start of shots 2..n), in seconds."""
        t, out = 0, []
        for s in self.shots[:-1]:
            t += self.frames(s)
            out.append(round(t / self.fps, 4))
        return out

    def to_dict(self) -> dict:
        d = {
            "output": self.output, "size": list(self.size), "fps": self.fps, "grade": self.grade,
            "crf": self.crf, "shots": [],
        }
        if self.song:
            d["song"] = asdict(self.song)
        for s in self.shots:
            sd = asdict(s)
            if sd["grade"] is None:
                del sd["grade"]
            if sd["speed"] == 1.0:
                del sd["speed"]
            d["shots"].append(sd)
        return d
