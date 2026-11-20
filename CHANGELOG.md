# Changelog

All notable changes to orbi2d are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-11-20

### Added
- Standalone builds that don't need Python: a Windows `.exe` (PyInstaller)
  and a Linux AppImage, with an app icon. A GitHub workflow builds both and
  attaches them to each release.
- Smoke test of both standalone builds in CI: the built `.exe` (on Windows)
  and AppImage are launched with `ORBI2D_SMOKE_TEST=1`, run a short
  Lunar Transfer session and must exit cleanly.
- This changelog.

### Changed
- Lunar Transfer: back around the planet for a planet target, the camera
  zooms in on the planet once the orbit can't reach the moon, instead of
  always keeping the moon's whole orbit on screen.
- The README screenshot shows the start screen.

## [0.2.0] - 2026-11-20

### Added
- Start screen: an animated menu (planet, orbiting moon, a ship on its
  orbit) offering **Planetary Orbit**, **Lunar Transfer** and **Quit**,
  usable with ↑/↓ + Enter or the mouse. Esc in a game returns to it.
- Lunar Transfer mode: a moon circles the planet; you start around one body
  and must reach a target orbit around the other. Gravity uses patched
  conics with the moon's sphere of influence (SOI).
- Prediction of the next SOI crossing: crossing point, the moon's position
  at that time, and the orbit after the crossing, with a countdown.
- Camera that zooms on the moon while orbiting it; V toggles the
  whole-system view.

### Changed
- Space is the main engine key; ↑ still works as an alternative.
- After a game ends, Enter (not Space) starts a new level.

### Fixed
- Ctrl+C in the terminal quits the game cleanly instead of printing a
  traceback and being ignored.

### Removed
- The `--mode` and `--seed` command-line options and the M key, replaced by
  the start screen.

## [0.1.0] - 2026-11-20

### Added
- First release: bring a rocket from a random orbit onto a random target
  orbit around a planet, to within 2%.
- Exact two-body Kepler physics: analytic universal-variable propagation
  while coasting, finite burns in any direction, osculating orbit redrawn
  every frame.
- Side thrusters (←/→) for orientation, main engine (↑), Shift for fine
  control.
- Time warp from ×0.1 to ×16, presets on keys 1–6 and +/− for small steps;
  the game starts at ×0.5.
- MIT license.

[Unreleased]: https://github.com/PiRK/orbi2d/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/PiRK/orbi2d/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/PiRK/orbi2d/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/PiRK/orbi2d/releases/tag/v0.1.0
