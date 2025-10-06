"""Module entrypoint to run WebWork via ``python -m webwork``."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    runpy.run_module("main", run_name="__main__")


if __name__ == "__main__":  # pragma: no cover
    main()
