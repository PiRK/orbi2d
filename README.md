# orbi2d

A 2D orbital-mechanics game in Python + Qt (PySide6). Your rocket starts on a
random orbit around a planet. Put it on the dashed green target orbit, to
within 2% (the largest radial gap between the two curves, relative to the
target).

This started as a vibe-coding project. The first few prompts are documented
for posterity in [claude_session.txt](claude_session.txt).

## Run

    pip install -r requirements.txt
    python -m orbi2d            # or: python -m orbi2d --seed 42

## Controls

| Key            | Action                                           |
|----------------|--------------------------------------------------|
| ← / →          | Side thrusters: rotate the ship (orientation only) |
| ↑              | Main engine                                      |
| Shift (held)   | Fine control: 10% thrust, slower rotation        |
| 1–6            | Time warp presets ×0.25 / ×0.5 / ×1 / ×2 / ×4 / ×8 |
| + / −          | Time warp ×1.25 / ÷1.25 (range ×0.1 – ×16)       |
| P              | Pause                                            |
| R / N          | New random level                                 |
| H              | Toggle help                                      |
| Esc / Q        | Quit                                             |

The yellow circle next to the ship marks the **prograde** direction (where the
ship is moving). The red ✕ marks **retrograde**. Pe/Ap mark periapsis and
apoapsis.

The game starts at ×0.5 time warp. Turning always happens in real time, but
orbital motion and engine thrust follow the warp. Slow motion therefore also
makes burns finer: at ×0.25 a tap on ↑ changes your speed 4× less.

## Physics

- The rocket and planet form a two-body Kepler system. Coasting uses the
  analytic universal-variable solution, so the ship follows the drawn conic
  exactly with no numerical drift. This works for ellipses, parabolas and
  hyperbolas.
- The main engine is modelled as a finite burn. Each frame is split into short
  sub-steps, and each sub-step uses kick, exact Kepler coast, kick. After each
  frame the osculating orbit is recomputed from the state vector and redrawn.
  So a burn in any direction at any point of the orbit changes the orbit the
  way it would in reality. For example, a prograde burn at one apsis raises the
  other apsis, and a radial burn rotates the line of apsides.
- You win when the engine is off and your orbit is within the tolerance of
  the target. Only the shape of the orbit counts, not the direction of travel.
  You lose if you hit the planet or escape.

Tuning constants are at the top of `orbi2d/game.py`.

## Tests

    python -m pytest

## License

MIT. See [LICENSE](LICENSE).
