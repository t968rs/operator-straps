"""Behavior of harness_lib.shell_scan.is_single_command."""
from __future__ import annotations

import pytest

from harness_lib.shell_scan import is_single_command


@pytest.mark.parametrize("command", [
    "ls -la",
    "echo 'a; b | c && d'",
    "echo \"a; b | c\"",
    "python -c 'x = 1\n# note\nprint(x)'",
    "echo a\\;b",
    "echo \"$HOME\"",
])
def test_one_command_passes(command: str) -> None:
    assert is_single_command(command)


@pytest.mark.parametrize("command", [
    "ls x; rm y",
    "ls x\nrm y",
    "ls x\r\nrm y",
    "ls x && rm y",
    "ls x || rm y",
    "ls x | sh",
    "ls x & rm y",
    "ls $(rm y)",
    "ls \"$(rm y)\"",
    "ls `rm y`",
    "ls \"`rm y`\"",
    "(rm y)",
    "ls $'a\\' ; rm y ; \\''",
    "ls 'unterminated",
    "ls \"unterminated",
])
def test_second_command_fails(command: str) -> None:
    assert not is_single_command(command)
    assert not is_single_command(command, allow_redirects=True)


@pytest.mark.parametrize("command", ["ls > out.txt", "ls 2>&1", "ls &> log", "wc -l < in.txt", "ls >&2"])
def test_redirects_need_the_flag(command: str) -> None:
    assert not is_single_command(command)
    assert is_single_command(command, allow_redirects=True)
