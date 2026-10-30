"""skill_api driver: run a stdin heredoc against the public names of one ``harness_lib`` module.

The project's configuration is activated first. The module ``harness_lib.<module>`` is imported and each name
in its ``__all__`` is bound in the namespace the stdin code runs in; a module without ``__all__`` is refused.
``name`` (the skill name) is bound when given. Any exception, including one raised by the stdin code, is one
``problem: <ExceptionName>: <message>`` line on stderr with exit 1. Usage::

    skill_api.py [--repo DIR] <module> [<name>] < code.py

``--repo`` (default: the working directory) names a directory inside the project.
"""
import argparse
import importlib
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.config import activate, load_config
from harness_lib.project import project_root

PACKAGE = "harness_lib"
MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class LauncherError(Exception):
    """A refusal reported as a bare problem line, without the exception name."""


def _namespace(module: ModuleType, name: Optional[str]) -> Dict[str, Any]:
    """The globals of the stdin code: the module's ``__all__`` names, plus ``name`` when given."""
    names = getattr(module, "__all__", None)
    if names is None:
        raise LauncherError(f"{module.__name__} has no __all__")
    space: Dict[str, Any] = {"__name__": "__skill_api__", **{n: getattr(module, n) for n in names}}
    if name is not None:
        space["name"] = name
    return space


def _load_module(module: str) -> ModuleType:
    if not MODULE_NAME.fullmatch(module):
        raise LauncherError(f"{module!r} is not a module name")
    return importlib.import_module(f"{PACKAGE}.{module}")


def _problem_line(exc: BaseException) -> str:
    if isinstance(exc, LauncherError):
        text = str(exc)
    else:
        text = f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())


def _run(args: argparse.Namespace) -> None:
    activate(load_config(project_root(args.repo)))
    space = _namespace(_load_module(args.module), args.name)
    code = sys.stdin.read()
    exec(compile(code, "<stdin>", "exec"), space)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill_api.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help="Directory inside the project (default: cwd)")
    parser.add_argument("module", help="Module of harness_lib whose __all__ is bound.")
    parser.add_argument("name", nargs="?", default=None, help="Skill name bound as `name`.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a problem."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except Exception as exc:
        sys.stderr.write(f"problem: {_problem_line(exc)}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
