"""Compatibility entrypoint for ``python -m webwork.main``.

This module mirrors the behaviour of running ``python main.py`` from the
repository root.  It ensures that the project root is present on
``sys.path`` and then delegates execution to :func:`main.main` from the
legacy flat-layout script.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Sequence

__all__ = ["main"]


def _ensure_repo_root() -> None:
    """Add the repository root to ``sys.path`` if it is missing."""

    repo_root = Path(__file__).resolve().parent.parent
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the legacy ``main`` module and return its exit code.

    Parameters
    ----------
    argv:
        Optional sequence of command-line arguments to override ``sys.argv``
        for the delegated call.  When ``None`` (the default) the current
        ``sys.argv`` is preserved, matching the behaviour of ``python -m``.
    """

    _ensure_repo_root()
    if argv is not None:
        sys.argv = [sys.argv[0], *argv]
    main_module = importlib.import_module("main")
    entry = getattr(main_module, "main", None)
    if entry is None:
        raise RuntimeError("main module does not define main()")
    result = entry()
    return int(result) if result is not None else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
