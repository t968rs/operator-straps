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
        "tests/lib/test_a.py::test_fast",
        "tests/lib/test_c.py::test_zero",
    ]
    assert catalog["tests"][0]["share"] == 0.9
    assert catalog["tests"][1]["share"] == 0.1
    assert catalog["tests"][2]["share"] == 0.0


def test_xunit1_ids_keep_the_class(script: ModuleType, tmp_path: Path) -> None:
    """Same-named methods in different classes of one file stay distinct, as pytest node ids."""
    xml = tmp_path / "junit.xml"
    xml.write_text(
        """<testsuites><testsuite>
<testcase classname='tests.test_dup.TestA' name='test_same' file='tests\\test_dup.py' time='0.4'/>
<testcase classname='tests.test_dup.TestB.TestInner' name='test_same' file='tests\\test_dup.py' time='0.3'/>
<testcase classname='tests.test_dup.TestB' name='test_same' file='tests\\test_dup.py' time='0.2'/>
<testcase classname='tests.test_dup' name='test_same' file='tests/test_dup.py' time='0.1'/>
</testsuite></testsuites>
""",
        encoding="utf-8",
    )

    ids = [test["test"] for test in script.build_catalog(xml)["tests"]]
    assert ids == [
        "tests/test_dup.py::TestA::test_same",
        "tests/test_dup.py::TestB::TestInner::test_same",
        "tests/test_dup.py::TestB::test_same",
        "tests/test_dup.py::test_same",
    ]


def _catalog(script: ModuleType, tmp_path: Path, body: str) -> dict:
    xml = tmp_path / "junit.xml"
    xml.write_text(body, encoding="utf-8")
    return script.build_catalog(xml, root=tmp_path)


def test_xunit2_ids_become_node_ids(script: ModuleType, tmp_path: Path) -> None:
    """Without ``file`` the module comes from ``classname``, so both JUnit families give the same ids."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_a.TestX' name='test_y' time='0.2'/>"
        "<testcase classname='tests.lib.test_a.TestX.TestInner' name='test_y' time='0.1'/>"
        "</testsuite></testsuites>"
    ))
    assert [test["test"] for test in catalog["tests"]] == [
        "tests/lib/test_a.py::TestX::test_y",
        "tests/lib/test_a.py::TestX::TestInner::test_y",
    ]


def test_modules_total_their_tests(script: ModuleType, tmp_path: Path) -> None:
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase file='tests/lib/test_a.py' classname='tests.lib.test_a' name='test_1' time='0.1'/>"
        "<testcase file='tests/lib/test_a.py' classname='tests.lib.test_a.TestX' name='test_2' time='0.2'/>"
        "<testcase file='tests/hooks/test_b.py' classname='tests.hooks.test_b' name='test_3' time='0.7'/>"
        "</testsuite></testsuites>"
    ))
    assert catalog["module_count"] == 2
    assert catalog["modules"] == [
        {"module": "tests/hooks/test_b.py", "test_count": 1, "seconds": 0.7, "share": 0.7},
        {"module": "tests/lib/test_a.py", "test_count": 2, "seconds": 0.3, "share": 0.3},
    ]


def test_run_block_separates_overhead_from_test_time(script: ModuleType, tmp_path: Path) -> None:
    """The suite's wall time minus the summed test times is collection and import overhead."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite name='pytest' time='5.000' timestamp='2026-10-14T17:00:00'>"
        "<testcase classname='tests.lib.test_a' name='test_1' time='1.0'/>"
        "</testsuite></testsuites>"
    ))
    assert catalog["run"] == {
        "timestamp": "2026-10-14T17:00:00", "wall_seconds": 5.0, "overhead_seconds": 4.0,
    }


def test_outcome_per_test(script: ModuleType, tmp_path: Path) -> None:
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_a' name='test_pass' time='0.3'/>"
        "<testcase classname='tests.lib.test_a' name='test_skip' time='0.2'><skipped/></testcase>"
        "<testcase classname='tests.lib.test_a' name='test_fail' time='0.1'><failure/></testcase>"
        "<testcase classname='tests.lib.test_a' name='test_err' time='0.0'><error/></testcase>"
        "</testsuite></testsuites>"
    ))
    assert [test["outcome"] for test in catalog["tests"]] == ["passed", "skipped", "failed", "error"]


def test_error_outranks_skip_in_one_testcase(script: ModuleType, tmp_path: Path) -> None:
    """A skipped test whose teardown errors carries both elements; the error wins."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_a' name='test_s' time='0.1'><skipped/><error/></testcase>"
        "</testsuite></testsuites>"
    ))
    assert catalog["tests"][0]["outcome"] == "error"


def test_split_testcases_merge_into_one_test(script: ModuleType, tmp_path: Path) -> None:
    """pytest writes a call failure and a teardown error as two testcases with one id."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_a' name='test_t' time='0.3'><failure/></testcase>"
        "<testcase classname='tests.lib.test_a' name='test_t' time='0.1'><error/></testcase>"
        "</testsuite></testsuites>"
    ))
    assert catalog["test_count"] == 1
    assert catalog["modules"][0]["test_count"] == 1
    assert catalog["tests"] == [
        {"test": "tests/lib/test_a.py::test_t", "outcome": "error", "seconds": 0.4, "share": 1.0},
    ]


def test_xunit1_file_of_an_inherited_test_is_ignored(script: ModuleType, tmp_path: Path) -> None:
    """xunit1 ``file`` names where the function is defined; the collecting module comes from classname."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_t.TestKid' name='test_inherited' "
        "file='tests\\lib\\shared_base.py' time='0.1'/>"
        "</testsuite></testsuites>"
    ))
    assert catalog["tests"][0]["test"] == "tests/lib/test_t.py::TestKid::test_inherited"
    assert catalog["modules"][0]["module"] == "tests/lib/test_t.py"


def test_module_is_found_on_disk_under_the_rootdir(script: ModuleType, tmp_path: Path) -> None:
    """A lowercase class name is not mistaken for a module when the real module file exists."""
    (tmp_path / "tests" / "lib").mkdir(parents=True)
    (tmp_path / "tests" / "lib" / "test_a.py").write_text("", encoding="utf-8")
    xml = tmp_path / "junit.xml"
    xml.write_text(
        "<testsuites><testsuite>"
        "<testcase classname='tests.lib.test_a.lowercase_cls' name='test_y' time='0.1'/>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    catalog = script.build_catalog(xml, root=tmp_path)
    assert catalog["tests"][0]["test"] == "tests/lib/test_a.py::lowercase_cls::test_y"


@pytest.mark.parametrize("extra", ["", " file='tests/lib/test_broken.py'"])
def test_collection_error_is_charged_to_its_module(script: ModuleType, tmp_path: Path, extra: str) -> None:
    """A module that fails to import has an empty classname and its dotted path as the name."""
    catalog = _catalog(script, tmp_path, (
        "<testsuites><testsuite>"
        f"<testcase classname='' name='tests.lib.test_broken'{extra} time='0.0'><error/></testcase>"
        "</testsuite></testsuites>"
    ))
    assert catalog["tests"][0]["test"] == "tests/lib/test_broken.py"
    assert catalog["modules"][0]["module"] == "tests/lib/test_broken.py"


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
    assert payload["tests"][0]["test"] == "tests/lib/test_a.py::test_one"
    assert payload["tests"][0]["share"] == 1.0
