"""Turn a pytest JUnit XML report into a runtime catalog: per run, per module and per test.

Usage: ci_test_runtime_catalog.py XML OUT [--rootdir DIR]

Test ids are pytest node ids (``tests/lib/test_a.py::TestX::test_y``) for both JUnit families. ``classname``
is the source of truth: its module is the longest dotted prefix that exists as a file under ``--rootdir``
(default: the working directory), else the parts before the trailing capitalised ones. xunit1's ``file``
is used only when it names that module, because for an inherited or imported test it names the defining
file instead. Directory names containing dots resolve only through xunit1's ``file``.

Each test's seconds are pytest's setup + call + teardown, so a session-, module- or class-scoped fixture
is charged to the test that sets it up and the test that tears it down. The ``run`` block's overhead
(suite wall time minus summed test time) is collection, import and plugin time outside every test.
A call failure plus a teardown error is two testcases with one id in the XML; they merge into one row.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

UNKNOWN_MODULE = "<unknown>"
OUTCOME_RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


def _dotted_file(dotted: str) -> str:
    return dotted.replace(".", "/") + ".py"


def _module_cut(parts: List[str], root: Path) -> int:
    """How many leading ``classname`` parts name the module: found on disk first, capitalisation second."""
    for cut in range(len(parts), 0, -1):
        if (root / _dotted_file(".".join(parts[:cut]))).is_file():
            return cut
    cut = len(parts)
    while cut > 1 and parts[cut - 1][:1].isupper():
        cut -= 1
    return cut


def _split_classname(class_name: str, root: Path) -> Tuple[str, str]:
    """``classname`` as (module file, ``::``-joined classes)."""
    parts = class_name.split(".")
    cut = _module_cut(parts, root)
    return _dotted_file(".".join(parts[:cut])), "::".join(parts[cut:])


def _class_path(file_name: str, class_name: str) -> Optional[str]:
    """The ``::``-joined classes past the module ``file_name`` names; None when it names another module."""
    module = (file_name[:-3] if file_name.endswith(".py") else file_name).replace("/", ".")
    if class_name == module:
        return ""
    if class_name.startswith(module + "."):
        return class_name[len(module) + 1:].replace(".", "::")
    return None


def _module_and_classes(file_name: str, class_name: str, root: Path) -> Tuple[str, str]:
    classes = _class_path(file_name, class_name) if file_name else None
    if classes is not None:
        return file_name, classes
    return _split_classname(class_name, root)


def _identify(case: ElementTree.Element, root: Path) -> Tuple[str, str]:
    """(node id, module file) for one testcase; an empty ``classname`` is a module's collection error."""
    name = case.attrib.get("name", "")
    file_name = case.attrib.get("file", "").replace("\\", "/")
    class_name = case.attrib.get("classname", "")
    if not class_name:
        module = file_name or (_dotted_file(name) if name else UNKNOWN_MODULE)
        return module, module
    module, classes = _module_and_classes(file_name, class_name, root)
    return "::".join(part for part in (module, classes, name or "unknown") if part), module


def _outcome(case: ElementTree.Element) -> str:
    for tag, outcome in (("error", "error"), ("failure", "failed"), ("skipped", "skipped")):
        if case.find(tag) is not None:
            return outcome
    return "passed"


def _merge(rows: Dict[str, Dict[str, object]], case: ElementTree.Element, root: Path) -> None:
    """Add one testcase to ``rows``, summing seconds and keeping the worst outcome per node id."""
    test, module = _identify(case, root)
    seconds = float(case.attrib.get("time") or 0.0)
    outcome = _outcome(case)
    row = rows.setdefault(test, {"test": test, "module": module, "outcome": outcome, "seconds": 0.0})
    row["seconds"] = round(float(row["seconds"]) + seconds, 6)
    if OUTCOME_RANK[outcome] > OUTCOME_RANK[str(row["outcome"])]:
        row["outcome"] = outcome


def _share(seconds: float, total: float) -> float:
    return 0.0 if total == 0 else round(seconds / total, 6)


def _modules(rows: List[Dict[str, object]], total: float) -> List[Dict[str, object]]:
    """Per-module test count, summed seconds and share of the summed test time, slowest first."""
    seconds: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        seconds[str(row["module"])] += float(row["seconds"])
        counts[str(row["module"])] += 1
    modules = [
        {"module": m, "test_count": counts[m], "seconds": round(s, 6), "share": _share(s, total)}
        for m, s in seconds.items()
    ]
    return sorted(modules, key=lambda m: (-float(m["seconds"]), m["module"]))


def _run(root: ElementTree.Element, total: float) -> Dict[str, object]:
    """The run's start time, wall seconds and the overhead no test owns."""
    suites = list(root.iter("testsuite"))
    times = [float(s.attrib["time"]) for s in suites if s.attrib.get("time")]
    wall = round(sum(times), 6) if times else None
    return {
        "timestamp": suites[0].attrib.get("timestamp") if suites else None,
        "wall_seconds": wall,
        "overhead_seconds": None if wall is None else round(wall - total, 6),
    }


def build_catalog(xml_path: Path, root: Optional[Path] = None) -> Dict[str, object]:
    """The catalog for one JUnit report; ``root`` is pytest's rootdir, for locating module files."""
    report = ElementTree.parse(xml_path).getroot()
    merged: Dict[str, Dict[str, object]] = {}
    for case in report.iter("testcase"):
        _merge(merged, case, Path.cwd() if root is None else root)
    rows = list(merged.values())
    total = round(sum(float(row["seconds"]) for row in rows), 6)
    modules = _modules(rows, total)
    for row in rows:
        row["share"] = _share(float(row["seconds"]), total)
        del row["module"]
    rows.sort(key=lambda row: -float(row["seconds"]))
    return {
        "source": str(xml_path),
        "run": _run(report, total),
        "test_count": len(rows),
        "total_seconds": total,
        "module_count": len(modules),
        "modules": modules,
        "tests": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a per-run, per-module and per-test runtime catalog from pytest JUnit XML"
    )
    parser.add_argument("xml", type=Path, help="Path to the pytest JUnit XML report")
    parser.add_argument("out", type=Path, help="Output JSON catalog path")
    parser.add_argument("--rootdir", type=Path, default=None,
                        help="pytest's rootdir, for locating module files (default: working directory)")
    args = parser.parse_args(argv)

    catalog = build_catalog(args.xml, root=args.rootdir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
