# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import os
import signal
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from .game import MOON_MODE, SOLAR
from .gamepad import Gamepad
from .menu import MenuWidget
from .view import GameWidget

# Set to 1 to run a short self-test and exit (used by CI on the built .exe
# and AppImage): exit code 0 if everything ran, 1 on any Python error.
SMOKE_TEST_ENV = "ORBI2D_SMOKE_TEST"


class MainWindow(QMainWindow):
    """Main menu and game screen in one window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("orbi2d")
        self.menu = MenuWidget()
        self.game = GameWidget()
        # One game controller, read by whichever screen is showing.
        self.pad = Gamepad()
        self.menu.pad = self.game.pad = self.pad
        self.stack = QStackedWidget()
        self.stack.addWidget(self.menu)
        self.stack.addWidget(self.game)
        self.setCentralWidget(self.stack)
        self.menu.start_requested.connect(self.start_game)
        self.menu.quit_requested.connect(self.close)
        self.game.exit_requested.connect(self.show_menu)
        self.show_menu()

    def start_game(self, mode: str) -> None:
        self.game.start_game(mode)
        self.stack.setCurrentWidget(self.game)
        self.game.setFocus()

    def show_menu(self) -> None:
        self.stack.setCurrentWidget(self.menu)
        self.menu.setFocus()


def smoke_test_controller(app: QApplication, win: MainWindow) -> None:
    """Plug in a virtual controller and fire the engine with A. With
    ORBI2D_SMOKE_PAD=1 (CI builds), missing controller support fails too."""
    if not win.pad.available:
        if os.environ.get("ORBI2D_SMOKE_PAD") == "1":
            print("smoke test: game controller support (SDL2) is missing", file=sys.stderr)
            QTimer.singleShot(0, lambda: app.exit(1))
        return
    from .gamepad import VirtualPad

    pad = VirtualPad("orbi2d smoke-test pad")
    win.pad.open(pad.index)

    def release_and_check() -> None:
        pad.set("a", False)
        if win.game.game.burn_dv <= 0:
            print("smoke test: controller A did not fire the engine", file=sys.stderr)
            app.exit(1)

    QTimer.singleShot(650, lambda: pad.set("a", True))
    QTimer.singleShot(900, release_and_check)


def main() -> int:
    app = QApplication(sys.argv[:1])
    # Ctrl+C in the terminal: quit cleanly. Python only runs signal handlers
    # between bytecodes, which happens often enough thanks to the screens'
    # 16 ms timers (otherwise Qt's C++ event loop would never yield).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    win = MainWindow()
    win.resize(1100, 850)
    win.show()
    if os.environ.get(SMOKE_TEST_ENV) == "1":
        smoke_test(app, win)
    return app.exec()


def smoke_test(app: QApplication, win: MainWindow) -> None:
    """Start a Lunar Transfer game, then a Solar System game at high time
    warp, go back to the menu and quit.

    PySide reports exceptions raised in Qt callbacks through sys.excepthook
    and then keeps running, so the hook turns any error into exit code 1.
    """
    def fail(exc_type, exc, tb) -> None:
        traceback.print_exception(exc_type, exc, tb)
        app.exit(1)

    sys.excepthook = fail
    def solar() -> None:
        win.start_game(SOLAR)
        win.game.game.set_warp(1000.0)

    QTimer.singleShot(500, lambda: win.start_game(MOON_MODE))
    smoke_test_controller(app, win)
    QTimer.singleShot(1000, solar)
    QTimer.singleShot(1500, win.show_menu)
    QTimer.singleShot(2000, lambda: app.exit(0))


if __name__ == "__main__":
    sys.exit(main())
