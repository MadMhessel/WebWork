"""newsbot package compatibility helpers."""

from __future__ import annotations

import os
import sys

_pkg_dir = os.path.dirname(__file__)
if _pkg_dir and _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)
