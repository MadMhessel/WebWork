from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from WebWork import sources_nn


def _load_sources_module(tmp_path: Path, yaml_text: str, module_name: str) -> object:
    """Load a temporary copy of ``sources_nn`` with custom YAML contents."""

    pkg_root = Path(__file__).resolve().parents[1]
    module_path = tmp_path / "sources_nn.py"
    module_path.write_text((pkg_root / "sources_nn.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "sources_nn.yaml").write_text(yaml_text, encoding="utf-8")

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[assignment]
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def test_sources_by_domain_keeps_multiple_entries():
    dom_sources = sources_nn.SOURCES_BY_DOMAIN.get("domostroynn.ru")
    assert dom_sources is not None
    assert len(dom_sources) >= 2


def test_duplicate_source_id_raises(tmp_path):
    yaml_text = dedent(
        """
        version: 2
        defaults:
          type: rss
          trust_level: 2
        sources:
          - name: "A"
            url: "https://example.com/news"
            type: rss
            trust_level: 2
          - name: "B"
            url: "https://example.com/news"
            type: rss
            trust_level: 2
        """
    )

    with pytest.raises(ValueError):
        _load_sources_module(tmp_path, yaml_text, "sources_nn_duplicate")


def test_domain_normalization_for_schema_less_and_idn(tmp_path):
    yaml_text = dedent(
        """
        version: 2
        defaults:
          type: html
          trust_level: 2
        sources:
          - name: "IDN 1"
            url: "//пример.рф/press"
            type: html
            trust_level: 2
          - name: "IDN 2"
            url: "https://xn--e1afmkfd.xn--p1ai/press"
            type: html
            trust_level: 2
        """
    )

    module_name = "sources_nn_idn"
    module = _load_sources_module(tmp_path, yaml_text, module_name)
    try:
        domain_key = "xn--e1afmkfd.xn--p1ai"
        assert domain_key in module.SOURCES_BY_DOMAIN
        expected = module.SOURCES_BY_DOMAIN[domain_key]
        assert module.get_sources_by_domain("пример.рф") == expected
        assert module.get_sources_by_domain("https://пример.рф/path") == expected
    finally:
        sys.modules.pop(module_name, None)
