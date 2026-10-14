from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "ci_test_runtime_catalog.py"


@pytest.fixture(scope="module")
def script() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("ci_test_runtime_catalog_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module


def test_build_catalog_orders_and_computes_share(script: ModuleType, tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<testsuites>
  <testsuite name='pytest' tests='3'>
    <testcase classname='tests.lib.test_a' name='test_fast' time='0.100'/>
    <testcase file='tests/lib/test_b.py' classname='tests.lib.test_b' name='test_slow' time='0.900'/>
    <testcase classname='tests.lib.test_c' name='test_zero' time='0.000'/>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    catalog = script.build_catalog(xml)
    assert catalog["test_count"] == 3
    assert catalog["total_seconds"] == 1.0
    assert [test["test"] for test in catalog["tests"]] == [
        "tests/lib/test_b.py::test_slow",
        "tests.lib.test_a::test_fast",
        "tests.lib.test_c::test_zero",
    ]
    assert catalog["tests"][0]["share"] == 0.9
    assert catalog["tests"][1]["share"] == 0.1
    assert catalog["tests"][2]["share"] == 0.0


def test_main_writes_json(script: ModuleType, tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        (
            "<testsuites><testsuite>"
            "<testcase classname='tests.lib.test_a' name='test_one' time='0.250'/>"
            "</testsuite></testsuites>"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "catalog.json"

    rc = script.main([str(xml), str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["total_seconds"] == 0.25
    assert payload["tests"][0]["test"] == "tests.lib.test_a::test_one"
    assert payload["tests"][0]["share"] == 1.0
