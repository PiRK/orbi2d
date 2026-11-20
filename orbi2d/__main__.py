# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

import signal
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from .menu import MenuWidget
from .view import GameWidget


class MainWindow(QMainWindow):
    """Main menu and game screen in one window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("orbi2d")
        self.menu = MenuWidget()
        self.game = GameWidget()
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


def main() -> int:
    app = QApplication(sys.argv[:1])
    # Ctrl+C in the terminal: quit cleanly. Python only runs signal handlers
    # between bytecodes, which happens often enough thanks to the screens'
    # 16 ms timers (otherwise Qt's C++ event loop would never yield).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    win = MainWindow()
    win.resize(1100, 850)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
