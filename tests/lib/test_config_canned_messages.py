"""The ``canned_messages`` config key: a project's own canned sets, loaded as ``CannedSet`` tuples.

Each set is ``{"patterns": [...], "message": "..."}``; the load keeps the project's order and refuses a
malformed set, with ``jsonschema`` and without it (the builder's own check).
"""
from __future__ import annotations

import sys

import pytest

from harness_lib.config import CannedSet, ConfigError, load_config

REPORT = {"patterns": ["offlineTestReport.json", "reports/*.xml"],
          "message": "Chore(tests): refresh the offline test report"}
COVERAGE = {"patterns": ["coverage.json"], "message": "Chore(tests): refresh coverage"}
MALFORMED = [
    {"patterns": [], "message": "Chore: x"},
    {"patterns": [""], "message": "Chore: x"},
    {"patterns": ["a.json"], "message": ""},
    {"patterns": ["a.json"]},
    {"patterns": ["a.json"], "message": "Chore: x", "extra": 1},
    "a.json",
]


def test_the_default_is_no_project_sets(make_project) -> None:
    assert load_config(make_project()).canned_messages == ()


def test_project_sets_load_in_order(make_project) -> None:
    cfg = load_config(make_project({"canned_messages": [REPORT, COVERAGE]}))
    assert cfg.canned_messages == (
        CannedSet(("offlineTestReport.json", "reports/*.xml"), REPORT["message"]),
        CannedSet(("coverage.json",), COVERAGE["message"]),
    )


@pytest.mark.parametrize("bad", MALFORMED)
def test_a_malformed_set_fails_the_load(make_project, bad) -> None:
    with pytest.raises(ConfigError, match="canned_messages"):
        load_config(make_project({"canned_messages": [bad]}))


@pytest.mark.parametrize("bad", MALFORMED)
def test_a_malformed_set_fails_without_jsonschema(make_project, monkeypatch, bad) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match="canned_messages"):
        load_config(make_project({"canned_messages": [bad]}))


def test_a_non_list_value_fails_without_jsonschema(make_project, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match="canned_messages"):
        load_config(make_project({"canned_messages": REPORT}))
