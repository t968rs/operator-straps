"""skill_api driver: run a stdin heredoc against the public names of one API module (harness_lib or --file).

The project's configuration is activated first. The module ``harness_lib.<module>`` is imported and each name
in its ``__all__`` is bound in the namespace the stdin code runs in; a module without ``__all__`` is refused.
``--file PATH`` loads an API module by path instead, with its folder appended to ``sys.path`` so a sibling
module imports (appended, so a file named like a standard library module never shadows it); exactly one of
``<module>`` and ``--file`` is accepted, and with ``--file`` a lone positional is the skill name. A relative
``--file`` is resolved against the caller's directory. A ``--file`` module is loaded, and its heredoc runs,
with the activated project root as the working directory (restored afterwards), so a module that resolves its
repository at import time or from the working directory writes into the project ``--repo`` names.
``name`` (the skill name) is bound when given. Any exception, including one raised by the stdin code, is one
``problem: <ExceptionName>: <message>`` line on stderr with exit 1. Usage::

    skill_api.py [--repo DIR] <module> [<name>] < code.py
    skill_api.py [--repo DIR] --file PATH [<name>] < code.py

``--repo`` (default: the working directory) names a directory inside the project.
"""
import argparse
import importlib
import importlib.util
import itertools
import os
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
_FILE_IDS = itertools.count(1)


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


def _load_file(raw: Path) -> ModuleType:
    """Load the API module at ``raw`` under a unique name, its folder appended to ``sys.path``."""
    path = raw.resolve()
    if not path.is_file():
        raise LauncherError(f"no API module at {path}")
    spec = importlib.util.spec_from_file_location(f"_skill_api_file_{next(_FILE_IDS)}", path)
    if spec is None or spec.loader is None:
        raise LauncherError(f"{path} is not a Python module")
    folder = str(path.parent)
    if folder not in sys.path:
        sys.path.append(folder)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _select(args: argparse.Namespace) -> ModuleType:
    """The API module named by exactly one of the positional module and ``--file``."""
    if args.file is None:
        if args.module is None:
            raise LauncherError("give a module name or --file PATH")
        return _load_module(args.module)
    if args.name is not None:
        raise LauncherError("give a module name or --file PATH, not both")
    args.name = args.module
    return _load_file(args.file)


def _problem_line(exc: BaseException) -> str:
    if isinstance(exc, LauncherError):
        text = str(exc)
    else:
        text = f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())


def _exec_heredoc(module: ModuleType, name: Optional[str]) -> None:
    """Run the stdin code with the names of ``module`` bound."""
    space = _namespace(module, name)
    code = sys.stdin.read()
    exec(compile(code, "<stdin>", "exec"), space)


def _run(args: argparse.Namespace) -> None:
    cfg = activate(load_config(project_root(args.repo)))
    if args.file is None:
        _exec_heredoc(_select(args), args.name)
        return
    args.file = args.file.resolve()
    before = os.getcwd()
    os.chdir(cfg.project_root)
    try:
        _exec_heredoc(_select(args), args.name)
    finally:
        os.chdir(before)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill_api.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help="Directory inside the project (default: cwd)")
    parser.add_argument("--file", type=Path, default=None, help="API module to load by path.")
    parser.add_argument("module", nargs="?", default=None,
                        help="Module of harness_lib whose __all__ is bound (not with --file).")
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
