import importlib
import sys
from pathlib import Path


def test_webwork_main_delegates_to_legacy_main(monkeypatch):
    import main as legacy_main

    calls: list[int] = []

    def fake_main() -> int:
        calls.append(1)
        return 42

    monkeypatch.setattr(legacy_main, "main", fake_main)

    module = importlib.import_module("webwork.main")
    result = module.main()

    assert result == 42
    assert calls == [1]


def test_webwork_main_injects_repo_root(monkeypatch):
    import main as legacy_main

    repo_root = str(Path(__file__).resolve().parents[1])
    monkeypatch.setattr(legacy_main, "main", lambda: 0)
    # Remove repo root from sys.path copy so that the entrypoint has to add it
    filtered_path = [p for p in sys.path if p != repo_root]
    monkeypatch.setattr(sys, "path", filtered_path, raising=False)

    module = importlib.import_module("webwork.main")
    module.main()

    assert repo_root in sys.path
