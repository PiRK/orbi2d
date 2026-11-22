# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Game controller support through SDL2's game controller API (PySDL2).

SDL maps hundreds of controller models (Xbox, PlayStation, Switch Pro,
Logitech, generic...) to one standard layout, so "A", "B" and the shoulder
buttons mean the same physical buttons everywhere. If SDL can't be loaded,
``Gamepad.available`` is False and the game is keyboard-only, as before.

The controller is polled (no SDL event loop is needed alongside Qt's), and
plugged / unplugged at any time.
"""

from __future__ import annotations

import ctypes
import warnings
from dataclasses import dataclass, field

IMPORT_ERROR = ""
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # pysdl2-dll announces itself
        import sdl2
except Exception as exc:   # missing package or SDL2 library: keyboard only
    sdl2 = None
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

STICK_THRESHOLD = 0.5   # left stick deflection that counts as a direction

# Our names -> SDL standard buttons.
BUTTONS = {} if sdl2 is None else {
    "a": sdl2.SDL_CONTROLLER_BUTTON_A,
    "b": sdl2.SDL_CONTROLLER_BUTTON_B,
    "x": sdl2.SDL_CONTROLLER_BUTTON_X,
    "y": sdl2.SDL_CONTROLLER_BUTTON_Y,
    "back": sdl2.SDL_CONTROLLER_BUTTON_BACK,
    "start": sdl2.SDL_CONTROLLER_BUTTON_START,
    "lb": sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
    "rb": sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    "up": sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP,
    "down": sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN,
    "left": sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT,
    "right": sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
}


@dataclass
class PadState:
    """Controller state for one frame. Directions come from the D-pad or
    the left stick; ``pressed`` holds what went down since the last poll."""

    held: set[str] = field(default_factory=set)
    pressed: set[str] = field(default_factory=set)

    def __contains__(self, name: str) -> bool:
        return name in self.held


class Gamepad:
    def __init__(self) -> None:
        self.available = False
        self.error = IMPORT_ERROR   # why it isn't available (diagnostics)
        self.controller = None
        self.name = ""
        self._prev: set[str] = set()
        if sdl2 is None:
            return
        # Keep reading the controller when the window isn't focused.
        sdl2.SDL_SetHint(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
            self.error = "SDL_Init: " + sdl2.SDL_GetError().decode(errors="replace")
            return
        # We poll the state instead of reading SDL's event queue.
        sdl2.SDL_GameControllerEventState(sdl2.SDL_IGNORE)
        sdl2.SDL_JoystickEventState(sdl2.SDL_IGNORE)
        self.available = True

    # ---- connection -----------------------------------------------------
    def open(self, index: int) -> bool:
        """Use the controller at SDL device ``index``."""
        self.close()
        c = sdl2.SDL_GameControllerOpen(index)
        if not c:
            return False
        self.controller = c
        self.name = (sdl2.SDL_GameControllerName(c) or b"Controller").decode(errors="replace")
        return True

    def close(self) -> None:
        if self.controller:
            sdl2.SDL_GameControllerClose(self.controller)
        self.controller, self.name, self._prev = None, "", set()

    def _connect(self) -> None:
        if self.controller and sdl2.SDL_GameControllerGetAttached(self.controller):
            return
        self.close()
        for i in range(sdl2.SDL_NumJoysticks()):
            if sdl2.SDL_IsGameController(i) and self.open(i):
                return

    @property
    def connected(self) -> bool:
        return bool(self.controller)

    # ---- reading --------------------------------------------------------
    def poll(self) -> PadState:
        """Read the controller (connecting to one if needed)."""
        if not self.available:
            return PadState()
        sdl2.SDL_GameControllerUpdate()   # also detects (un)plugged devices
        self._connect()
        if not self.controller:
            return PadState()
        c = self.controller
        held = {name for name, b in BUTTONS.items() if sdl2.SDL_GameControllerGetButton(c, b)}
        x = sdl2.SDL_GameControllerGetAxis(c, sdl2.SDL_CONTROLLER_AXIS_LEFTX) / 32767.0
        y = sdl2.SDL_GameControllerGetAxis(c, sdl2.SDL_CONTROLLER_AXIS_LEFTY) / 32767.0
        if x < -STICK_THRESHOLD:
            held.add("left")
        elif x > STICK_THRESHOLD:
            held.add("right")
        if y < -STICK_THRESHOLD:   # SDL's y axis points down
            held.add("up")
        elif y > STICK_THRESHOLD:
            held.add("down")
        state = PadState(held=held, pressed=held - self._prev)
        self._prev = held
        return state


class VirtualPad:
    """A software controller (SDL virtual joystick), for tests and the
    self-test: press buttons from code, read them back through Gamepad."""

    def __init__(self, name: str = "orbi2d virtual pad") -> None:
        desc = sdl2.SDL_VirtualJoystickDesc()
        desc.version = sdl2.SDL_VIRTUAL_JOYSTICK_DESC_VERSION
        desc.type = sdl2.SDL_JOYSTICK_TYPE_GAMECONTROLLER
        desc.naxes = sdl2.SDL_CONTROLLER_AXIS_MAX
        desc.nbuttons = sdl2.SDL_CONTROLLER_BUTTON_MAX
        desc.button_mask = (1 << sdl2.SDL_CONTROLLER_BUTTON_MAX) - 1
        desc.axis_mask = (1 << sdl2.SDL_CONTROLLER_AXIS_MAX) - 1
        self._name = ctypes.create_string_buffer(name.encode())
        desc.name = ctypes.cast(self._name, ctypes.c_char_p)
        self.index = sdl2.SDL_JoystickAttachVirtualEx(ctypes.byref(desc))
        if self.index < 0:
            raise RuntimeError(sdl2.SDL_GetError().decode(errors="replace"))
        self._joy = sdl2.SDL_JoystickOpen(self.index)

    def set(self, button: str, down: bool) -> None:
        sdl2.SDL_JoystickSetVirtualButton(self._joy, BUTTONS[button], int(down))

    def stick(self, x: float, y: float = 0.0) -> None:
        sdl2.SDL_JoystickSetVirtualAxis(self._joy, sdl2.SDL_CONTROLLER_AXIS_LEFTX, int(x * 32767))
        sdl2.SDL_JoystickSetVirtualAxis(self._joy, sdl2.SDL_CONTROLLER_AXIS_LEFTY, int(y * 32767))

    def unplug(self) -> None:
        sdl2.SDL_JoystickClose(self._joy)
        sdl2.SDL_JoystickDetachVirtual(self.index)
