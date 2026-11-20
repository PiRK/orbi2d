# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import argparse
import signal
import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from .game import MODES, SINGLE
from .view import GameWidget


def main() -> int:
    parser = argparse.ArgumentParser(description="Bring your rocket into the target orbit.")
    parser.add_argument("--seed", type=int, default=None, help="seed for the first level")
    parser.add_argument(
        "--mode", choices=MODES, default=SINGLE,
        help="single: one planet; moon: travel between a planet and its moon (default: single)",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    # Ctrl+C in the terminal: quit cleanly. Python only runs signal handlers
    # between bytecodes, which happens often enough thanks to the game's
    # 16 ms timer (otherwise Qt's C++ event loop would never yield).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    win = QMainWindow()
    win.setWindowTitle("orbi2d")
    widget = GameWidget(seed=args.seed, mode=args.mode)
    win.setCentralWidget(widget)
    win.resize(1100, 850)
    win.show()
    widget.setFocus()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
