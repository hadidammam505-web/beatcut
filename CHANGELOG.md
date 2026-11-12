# Changelog

## 0.1.0 (2026-11-12)

First release.

- `analyze`: cut detection (pixel + histogram difference, local-median test, optional crop for letterboxed references), tempo, beat grid, onsets, cut-to-onset offsets.
- `beats`, `align`: song analysis and per-cut offsets from the nearest onset or beat.
- `scaffold`: a first plan from a reference analysis and a folder of clips.
- `check`: plan validation, missing files, and cut timing against the song.
- `build`: frame-exact rendering with crop, push / pull / punch motion, flash and fade transitions, per-shot grades, speed, a cached segment per shot, `--preview` and `--sheet`.
- `sheet`: contact sheets.
- Grades: `dark`, `dark-vivid`, `cinematic`, `mono`, `warm`, and `custom:`.
