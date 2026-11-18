"""``harness_lib.commit_txt.subject_parts``: the one Conventional-Commit subject parser, public.

``merge-commit-msg`` squash mode checks a PR title with it, so the parser that ``read_commit_txt`` uses for
commit blocks is the only regex for ``Type(scope): summary``. The private name stays as an alias for the
module's own callers.
"""
from __future__ import annotations

CASES = (
    ("Fix(workers): pool crash on spawn", ("Fix", "workers", "pool crash on spawn")),
    ("Fix(workers):", ("Fix", "workers", "")),
    ("Docs: README key table", ("Docs", None, "README key table")),
    ("[BUG] Worker pool crash on spawn", (None, None, None)),
    ("Merge PR #7 -- Fix(workers): x", (None, None, None)),
    (None, (None, None, None)),
)


def test_subject_parts_splits_type_scope_summary() -> None:
    from harness_lib.commit_txt import subject_parts

    for header, parts in CASES:
        assert subject_parts(header) == parts, header


def test_private_name_is_the_same_function() -> None:
    from harness_lib import commit_txt
    from harness_lib.commit_txt import subject_parts

    assert commit_txt._subject_parts is subject_parts
