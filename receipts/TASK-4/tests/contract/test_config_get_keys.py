"""Every ``config --get <key>`` an agent or skill prompt asks for resolves in ``pr_review.py config``.

``config --get`` walks the loaded configuration dataclasses (``config_data``), not the raw
``.claude/harness.json``, so a key the loader flattens (``todo.gh.repo`` becomes ``todo.gh_repo``) only
resolves in its flattened form. A prompt that asks for the file's nested form gets ``unknown key`` on
every run. Each key is checked through ``config_value(config_data(), key)`` against a project with no
``harness.json``, so the plugin defaults alone supply the values.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator, List, Tuple

import pytest

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib.config import activate, load_config

WALK_ROOTS = ("plugins/",)

_PLUGINS = REPO_ROOT / "plugins"
_SCRIPT = PLUGIN_ROOT / "scripts" / "pr_review.py"
_CALL = re.compile(r"\bconfig((?:[\s\\]+--get\s+[A-Za-z_][\w.-]*)+)")
_KEY = re.compile(r"--get\s+([A-Za-z_][\w.-]*)")


def _prompt_files() -> List[Path]:
    """The agent, command and skill markdown files of every plugin, including a skill's reference files."""
    agents = _PLUGINS.glob("*/agents/*.md")
    commands = _PLUGINS.glob("*/commands/*.md")
    skills = _PLUGINS.glob("*/skills/**/*.md")
    return sorted({*agents, *commands, *skills})


def _get_keys() -> List[Tuple[str, str]]:
    """``(repo-relative file, key)`` for each ``--get`` key of each ``config`` call in the prompt files."""
    found = []
    for path in _prompt_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for call in _CALL.finditer(path.read_text(encoding="utf-8")):
            found.extend((rel, key.rstrip(".")) for key in _KEY.findall(call.group(1)))
    return found


_FOUND = _get_keys()


@pytest.fixture(scope="module")
def script() -> Iterator[ModuleType]:
    """Import pr_review.py by absolute path, registered in ``sys.modules`` so annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_review_config_keys", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_the_scan_finds_the_known_lookups() -> None:
    """The pattern still matches the prompts' calls, so an empty scan cannot pass the check below."""
    keys = {key for _, key in _FOUND}
    assert {"todo.catalog", "artifacts.scratch", "artifacts.reviews", "state_dir"} <= keys


@pytest.mark.parametrize(("rel", "key"), _FOUND, ids=[f"{rel}:{key}" for rel, key in _FOUND])
def test_config_get_key_resolves_against_the_plugin_defaults(script: ModuleType, make_project,
                                                             rel: str, key: str) -> None:
    activate(load_config(make_project()))
    try:
        script.config_value(script.config_data(), key)
    except script.CaptureError as exc:
        pytest.fail(f"{rel} asks `config --get {key}`, which does not resolve: {exc}")
