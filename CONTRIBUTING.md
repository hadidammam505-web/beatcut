# Contributing

Thanks for helping. A few things keep beatcut easy to use and easy to trust:

1. **Keep dependencies to numpy and ffmpeg.** If a feature needs more, such as person masks, make it an optional extra.
2. **Add a test with a known answer.** The test suite builds synthetic media with ffmpeg (test patterns, a click track), so we always know where the cuts and beats really are.
3. **Frame-exact or it's a bug.** A render must have exactly `plan.total_frames` frames.

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

Open an issue first for big changes, so we can agree on the design.
