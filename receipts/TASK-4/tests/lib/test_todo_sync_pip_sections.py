"""harness_lib.todo_sync.pip_sections: PIP headings, section ranges, checkbox states."""
from __future__ import annotations

import pytest

from harness_lib.todo_sync.pip_sections import find_section, parse_pip, section_key, slug

PIP = """# 0001 Sample

Intro text.

## ABC-1 (critical): first item

- [x] done
- [X] also done
  - [ ] nested open
* [x] star bullet

### Sub heading inside ABC-1

- [ ] deep open

## ABC-10: tenth item

- [x] only box

## `ABC-2`: quoted key

```bash
# not a heading
- [ ] not a box
```

- [x] real box

## dsgn-1 Design Finalize

Prose only.
"""


@pytest.fixture()
def doc():
    return parse_pip(PIP)


def test_headings_skip_fenced_code(doc) -> None:
    texts = [h.text for h in doc.headings]
    assert "not a heading" not in texts
    assert texts[0] == "0001 Sample"
    assert [h.level for h in doc.headings][:3] == [1, 2, 3]


def test_section_runs_to_next_heading_of_same_level(doc) -> None:
    section = find_section(doc, "ABC-1")
    assert section is not None
    assert section.heading.line == 5
    states = [b.checked for b in section.boxes]
    assert states == [True, True, False, True, False]
    assert section.unchecked[0].line == 9


def test_prefix_needs_a_boundary(doc) -> None:
    section = find_section(doc, "ABC-10")
    assert section is not None and section.heading.text.startswith("ABC-10")
    assert [b.checked for b in section.boxes] == [True]


def test_prefix_is_case_insensitive_and_ignores_backticks(doc) -> None:
    section = find_section(doc, "abc-2")
    assert section is not None
    assert [b.checked for b in section.boxes] == [True]


def test_slug_match(doc) -> None:
    section = find_section(doc, "dsgn-1-design-finalize")
    assert section is not None and section.boxes == ()


def test_unknown_key(doc) -> None:
    assert find_section(doc, "ZZZ-9") is None


@pytest.mark.parametrize("raw,key", [
    ("BFX-1", "BFX-1"), ("#mdl-1", "mdl-1"), ("docs/PLANS/x_PIP.md#tree-1", "tree-1"), ("  #a-1 ", "a-1"),
])
def test_section_key(raw: str, key: str) -> None:
    assert section_key(raw) == key


def test_slug_shape() -> None:
    assert slug("DSGN-1: Design (finalize)!") == "dsgn-1-design-finalize"
    assert slug("`MDL-1` model") == "mdl-1-model"


TEMPLATE_PIP = """# Plan

### Task FCC-1 — Title from the harness PIP template

- [x] a

### Task FCC-10 — Tenth

- [ ] b

### #bblk-1 — `helper()` with a literal hash

- [ ] c
"""


@pytest.mark.parametrize("key,line", [
    ("FCC-1", 3), ("fcc-10", 7), ("task-fcc-1", 3), ("#task-fcc-1", 3), ("bblk-1", 11),
])
def test_template_and_anchor_headings(key: str, line: int) -> None:
    section = find_section(parse_pip(TEMPLATE_PIP), section_key(key))
    assert section is not None and section.heading.line == line


def test_slug_prefix_needs_a_boundary() -> None:
    assert find_section(parse_pip(TEMPLATE_PIP), "task-fc") is None


def test_last_section_runs_to_end_of_file() -> None:
    doc = parse_pip("## A-1\n\n- [ ] x\n- [x] y\n")
    section = find_section(doc, "A-1")
    assert [b.checked for b in section.boxes] == [False, True]
