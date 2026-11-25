"""Quote-aware scan of a POSIX shell command line for anything that runs a second command.

Permission hooks match allow rules with a ``*`` glob that spans any text, so a rule such as ``ls *`` also
matches ``ls x; rm y``. A hook calls ``is_single_command`` before trusting a glob match: one command, with no
unquoted separator, pipe, background ``&``, group, ANSI-C string or command substitution.
"""
from __future__ import annotations

_STOPS = frozenset(";|()`\n\r")
_REDIRECTS = frozenset("<>")


def is_single_command(command: str, allow_redirects: bool = False) -> bool:
    """True when ``command`` runs exactly one command and closes every quote.

    ``<`` / ``>`` stop the scan unless ``allow_redirects``; with it, an ``&`` that belongs to a redirect
    (``2>&1``, ``&>``) is part of the redirect rather than a background job.
    """
    quote, i = "", 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            quote = "" if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote == '"':
            if ch == "`" or command.startswith("$(", i):
                return False
            quote = "" if ch == '"' else quote
        elif _is_stop(command, i, allow_redirects):
            return False
        elif ch in "'\"":
            quote = ch
        i += 1
    return not quote


def _is_stop(command: str, i: int, allow_redirects: bool) -> bool:
    """True when the unquoted character at ``i`` ends the command or starts a nested one."""
    ch = command[i]
    if ch in _STOPS or command.startswith("$'", i):
        return True
    if ch in _REDIRECTS:
        return not allow_redirects
    if ch == "&":
        return not (allow_redirects and _is_fd_redirect(command, i))
    return False


def _is_fd_redirect(command: str, i: int) -> bool:
    """True when the ``&`` at ``i`` is part of ``>&``, ``<&`` or ``&>``."""
    return (i > 0 and command[i - 1] in _REDIRECTS) or command.startswith("&>", i)
