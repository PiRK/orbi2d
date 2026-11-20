# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import argparse
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
