from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree


def _class_path(file_name: str, class_name: str) -> str:
    """The ``::``-joined classes in ``class_name`` past the module that ``file_name`` names."""
    module = file_name[:-3] if file_name.endswith(".py") else file_name
    module = module.replace("/", ".")
    if class_name == module:
        return ""
    if class_name.startswith(module + "."):
        class_name = class_name[len(module) + 1:]
    return class_name.replace(".", "::")


def _node_id(case: ElementTree.Element) -> str:
    file_name = case.attrib.get("file", "").replace("\\", "/")
    name = case.attrib.get("name", "unknown")
    class_name = case.attrib.get("classname")
    if file_name:
        classes = _class_path(file_name, class_name) if class_name else ""
        return "::".join(part for part in (file_name, classes, name) if part)
    if class_name:
        return f"{class_name}::{name}"
    return name


def _seconds(case: ElementTree.Element) -> float:
    raw = case.attrib.get("time")
    if raw is None:
        return 0.0
    return float(raw)


def _rows(root: ElementTree.Element) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for case in root.findall(".//testcase"):
        seconds = _seconds(case)
        rows.append({"test": _node_id(case), "seconds": round(seconds, 6)})
    return rows


def build_catalog(xml_path: Path) -> Dict[str, object]:
    root = ElementTree.parse(xml_path).getroot()
    tests = _rows(root)
    total_seconds = sum(test["seconds"] for test in tests)
    for test in tests:
        seconds = float(test["seconds"])
        test["share"] = 0.0 if total_seconds == 0 else round(seconds / total_seconds, 6)
    tests.sort(key=lambda test: float(test["seconds"]), reverse=True)
    return {
        "source": str(xml_path),
        "test_count": len(tests),
        "total_seconds": round(total_seconds, 6),
        "tests": tests,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a per-test runtime contribution catalog from pytest JUnit XML"
    )
    parser.add_argument("xml", type=Path, help="Path to the pytest JUnit XML report")
    parser.add_argument("out", type=Path, help="Output JSON catalog path")
    args = parser.parse_args(argv)

    catalog = build_catalog(args.xml)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
