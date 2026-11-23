# orbi2d

![orbi2d start screen: the menu (Planetary Orbit, Lunar Transfer, Solar System, Quit) next to a planet with a ship on its orbit and a moon circling it](https://raw.githubusercontent.com/PiRK/orbi2d/master/docs/screenshot.png)

A 2D orbital-mechanics game in Python + Qt (PySide6). Your rocket starts on a
random orbit. Put it on the dashed green target orbit, to within 2% (the
largest radial gap between the two curves, relative to the target).

Pick a mode on the start screen:

- **Planetary Orbit**: start and target orbits are both around the planet.
- **Lunar Transfer**: a moon circles the planet. You start around one of them
  and the target orbit is around the other, so you have to fly from the
  planet to the moon or from the moon back to the planet.
- **Solar System**: a compressed solar system with the Sun, the blue planet
  and its moon, a red planet and a gas giant. You start around the blue
  planet, with two target orbits to choose from: around the gas giant (easy
  to reach but expensive) or around the small red planet (cheap, but a much
  harder target). Reaching either one wins.

This started as a vibe-coding project. The first few prompts are documented
for posterity in [claude_session.txt](https://github.com/PiRK/orbi2d/blob/master/claude_session.txt).

## Install and run

    pip install orbi2d
    orbi2d

From a clone of this repository:

    pip install -r requirements.txt
    python -m orbi2d

The game opens on the start screen: choose a mode with ↑/↓ and Enter, or
with the mouse.

## Standalone builds

Each GitHub release also gets standalone builds that don't need Python:
a Windows `.exe` and a Linux `.AppImage`. They are built by the
[Standalone builds](.github/workflows/standalone-builds.yml) workflow. To
build them yourself:

    pip install -r requirements.txt -r packaging/requirements.txt
    python packaging/build_exe.py        # on Windows -> dist/orbi2d-<version>-windows-x64.exe
    python packaging/build_appimage.py   # on Linux   -> dist/orbi2d-<version>-x86_64.AppImage

PyInstaller can't cross-compile, so the `.exe` must be built on Windows. An
AppImage runs on Linux distributions at least as new as the one it was built
on. The app icon is drawn by `packaging/make_icon.py`.

## Controls

| Key            | Action                                           |
|----------------|--------------------------------------------------|
| ← / →          | Side thrusters: rotate the ship (orientation only) |
| Space (or ↑)   | Main engine                                      |
| Shift (held)   | Fine control: 10% thrust, slower rotation        |
| 1–6            | Time warp presets ×0.25 / ×0.5 / ×1 / ×2 / ×4 / ×8 |
| + / −          | Time warp ×1.25 / ÷1.25 (range ×0.1 – ×16)       |
| P              | Pause                                            |
| R / N          | New random level (asks first during a flight; Enter also works after a game ends) |
| V              | Lunar Transfer / Solar System: toggle the whole-system view |
| H              | Toggle help                                      |
| Esc            | Back to the start screen (asks first during a flight; Esc there quits) |

### Game controller

Xbox, PlayStation, Switch Pro, Logitech and most other controllers work
(through SDL2's standard controller layout), plugged in before or during
the game. The keyboard keeps working alongside.

| Controller          | In game                                   | Start screen |
|---------------------|-------------------------------------------|--------------|
| D-pad / left stick  | ◀ ▶ rotate                                | ▲ ▼ choose   |
| A                   | Full thrust (new orbit after a game ends) | Start        |
| B                   | 10% thrust (and fine turning while held)  |              |
| LB / RB             | Time warp − / +                           |              |
| Y                   | Whole-system view                         |              |
| Start               | Pause                                     | Start        |
| Back / View         | Back to the start screen (asks first)     |              |

During a flight, leaving it or starting a new orbit asks first: time stops
and a dialog waits for **Enter / A** (yes) or **Esc / B** (no). After a win
or a crash there's nothing to lose, so these act right away.

The yellow circle next to the ship marks the **prograde** direction (where the
ship is moving). The red ✕ marks **retrograde**. Pe/Ap mark periapsis and
apoapsis.

The game starts at ×0.5 time warp. Turning always happens in real time, but
orbital motion and engine thrust follow the warp. Slow motion therefore also
makes burns finer: at ×0.25 a tap on Space changes your speed 4× less.

## Lunar Transfer mode

- The moon moves on a circular orbit, so you have to time your departure: a
  transfer only works if the moon is there when you arrive.
- The dotted circle around the moon is its **sphere of influence** (SOI).
  Inside it only the moon's gravity acts on the rocket; outside it only the
  planet's does. Your current orbit is drawn around whichever body you are
  orbiting.
- When your trajectory will cross the SOI, the game shows the prediction in
  purple: the crossing point (◇), where the moon will be at that moment, and
  your orbit after the crossing. The top-right corner shows the time until the
  encounter.
- Typical trip to the moon: burn prograde until the purple prediction shows an
  encounter, coast in, then burn retrograde near the moon's periapsis to be
  captured, and fine-tune. To go back, burn prograde around the moon until you
  leave its SOI.
- While you orbit the moon the camera zooms in on it. Back around the planet
  for a planet target, it zooms in on the planet as soon as your orbit can't
  reach the moon any more. Press V for the whole system.

## Solar System mode

- **Two targets.** Tab (or the controller's D-pad ▲/▼) switches the
  selected target; the transfer window, the closest-approach hints and the
  HUD follow it, and arriving in a target planet's SOI selects it. The red
  planet's SOI is tiny (729 units, vs 40,300 for the gas giant), so expect
  mid-course corrections; its target orbits are small and fast (a few
  seconds per orbit), so use slow motion; and the pass by the planet is too
  short for a capture burn: start braking as soon as you enter its SOI.
- Distances are compressed (the gas giant is ~270x farther from the Sun than
  the moon is from the blue planet, not ~23,000x as in reality), so the whole
  system stays playable.
- **Time warp adjusts itself.** Your setting (up to x1000, keys 1-9 or +/-)
  is a ceiling: the game runs at most 3 orbits per real second, slows down
  as the next sphere-of-influence crossing approaches, and stays at x8 or
  below while the engine fires. The HUD shows both, e.g.
  `Time warp x1000 (auto x70)`.
- **Prediction looks 3 crossings ahead**: leaving the blue planet, meeting
  the gas giant, leaving it again... each with the orbit that follows. A
  flyby changes your orbit around the Sun: that's a gravity assist
  (slingshot), and the prediction shows its effect before you get there.
- The camera follows the body you are orbiting and zooms on a log scale;
  V shows the whole system.
- Planets and moons are lit by the Sun: their bright side faces it, so even
  zoomed in on a planet you can tell which way the Sun is (and which side of
  your orbit faces it).

### Gravity assists

Slingshots are a bonus: the win screen shows the Δv you spent and the
free Δv you got from flybys. Aids for aiming them:

- **Transfer window** (target around the gas giant): the HUD shows how far
  ahead of the blue planet the gas giant is, the ideal angle for a direct
  (Hohmann) transfer, and the time until it comes round. Warp until then,
  and leave the blue planet moving along its own orbital motion.
- **Closest approach** (amber): before you have an encounter, the predicted
  path shows where it passes closest to the target's planet (and to other
  planets passed nearby), where that planet will be, and the distance
  next to the planet's SOI radius: you need to get below it. For the
  target's planet, a second line says whether you arrive early or late and
  which burn closes the gap, e.g. `115 s early: burn prograde to close in`.
  The game finds that burn by re-predicting your path with a tiny prograde
  and a tiny retrograde nudge (a simple "early → slow down" rule is often
  wrong: near the far end of a transfer, slowing down means not arriving at
  all). Short fine (Shift) bursts in that direction, at low warp, until
  the purple encounter appears. If no single burn helps, or the path only
  moves away from the planet, the marker says so: wait for the next window.
- **Predicted flyby**: `GAS GIANT ENCOUNTER in 415.5s (assist +166)` shows
  how much the flyby will change your speed around the Sun, and the
  predicted path is marked with the flyby's periapsis altitude (`Pe alt`).
  Passing behind the planet (relative to its motion) speeds you up, in
  front of it slows you down; closer means stronger.
- An orbit that would carry you out of the system (open, or reaching past
  the edge after a big slingshot) is drawn in red.

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
- In Lunar Transfer and Solar System modes the game uses *patched conics*:
  the bodies form a tree (Sun → planets → moons) and each one has a sphere of
  influence, `r_SOI = d · (m_body / m_parent)^0.4`. When the rocket crosses
  an edge, the position and velocity are converted to the other body's frame
  and the rocket continues on an exact conic around that body. While coasting
  at high warp, the game jumps straight to the next possible crossing, so
  even x1000 stays cheap and exact.
- You win when the engine is off, you are orbiting the target's body, and your
  orbit is within the tolerance of the target. Only the shape of the orbit counts, not the direction of travel.
  You lose if you hit the planet or escape.

Tuning constants are at the top of `orbi2d/game.py`.

## Tests

    python -m pytest

## License

MIT. See [LICENSE](https://github.com/PiRK/orbi2d/blob/master/LICENSE).
