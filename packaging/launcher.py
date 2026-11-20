# SPDX-FileCopyrightText: 2026 PiRK
# SPDX-License-Identifier: MIT

"""Entry script for PyInstaller (it needs a file, not ``python -m``)."""

import sys

from orbi2d.__main__ import main

sys.exit(main())
