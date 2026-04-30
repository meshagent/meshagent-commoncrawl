from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_crawl_example() -> ModuleType:
    path = Path(__file__).parents[1] / "examples" / "crawl.py"
    spec = importlib.util.spec_from_file_location("meshagent_commoncrawl_example", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crawl = _load_crawl_example()


def test_crawl_example_defaults_to_exact_host_scope() -> None:
    assert crawl._domain("https://www.amazon.com") == "www.amazon.com"
    assert (
        crawl._url_filter("https://www.amazon.com")
        == r"^https?://www\.amazon\.com(/.*)?$"
    )


def test_crawl_example_domain_scope_includes_sibling_subdomains() -> None:
    assert crawl._domain("https://www.amazon.com", scope="domain") == "amazon.com"
    assert (
        crawl._url_filter("https://www.amazon.com", scope="domain")
        == r"^https?://([^/]+\.)?amazon\.com(/.*)?$"
    )


def test_crawl_example_host_scope_preserves_path_prefix() -> None:
    assert (
        crawl._url_filter("https://www.amazon.com/deals", scope="host")
        == r"^https?://www\.amazon\.com/deals(/.*)?$"
    )
