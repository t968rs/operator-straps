"""``plugins/harness/scripts/todo_sync.md``, the usage document of ``todo_sync.py``, keeps up with its parser.

Every leaf command of the parser (``check``, ``inbox put``, ``lease release``, ...) has a ``### `<command>```
section, every option of that command is named in backticks inside its section, and the two global options
(``--project``, ``--config``) are named once in the document. The snapshot page's Render info block links the
document's GitHub copy from its ``todo_sync.py`` name, and that link points at this file.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib.todo_sync import snapshot_html as sh  # noqa: E402

REPO_ROOT = PLUGIN_ROOT.parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "todo_sync.py"
DOC = PLUGIN_ROOT / "scripts" / "todo_sync.md"
GLOBALS = ("--project", "--config")


def _parser() -> argparse.ArgumentParser:
    spec = importlib.util.spec_from_file_location("todo_sync_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._parser()


Command = Tuple[str, argparse.ArgumentParser]


def _leaves(parser: argparse.ArgumentParser, path: Tuple[str, ...] = ()) -> Iterator[Command]:
    """Each command that takes no further subcommand, named by its full path (``lease release``)."""
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield " ".join(path), parser
        return
    for name, child in subs[0].choices.items():
        yield from _leaves(child, (*path, name))


def _options(parser: argparse.ArgumentParser) -> List[str]:
    return [o for a in parser._actions for o in a.option_strings if o not in ("-h", "--help", *GLOBALS)]


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _section(doc: str, name: str) -> str:
    start = doc.index(f"### `{name}`\n")
    end = doc.find("\n### ", start + 1)
    return doc[start:] if end == -1 else doc[start:end]


def test_every_command_has_a_section() -> None:
    names = [name for name, _ in _leaves(_parser())]
    assert len(names) >= 14
    missing = [name for name in names if f"### `{name}`\n" not in _doc()]
    assert missing == []


def test_every_option_is_named_in_its_command_section() -> None:
    doc = _doc()
    missing = [(name, opt) for name, cmd in _leaves(_parser()) for opt in _options(cmd)
               if f"`{opt}" not in _section(doc, name)]
    assert missing == []


def test_the_global_options_are_named() -> None:
    doc = _doc()
    assert all(f"`{opt}" in doc for opt in GLOBALS)


def test_the_render_info_links_the_document() -> None:
    assert sh.USAGE.endswith("/blob/main/" + DOC.relative_to(REPO_ROOT).as_posix())
    assert sh.USAGE.startswith("https://github.com/")
