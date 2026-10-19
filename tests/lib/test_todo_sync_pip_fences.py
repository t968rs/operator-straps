"""PIP fence handling: only a matching fence closes a fenced block."""
from __future__ import annotations

from harness_lib.todo_sync.pip_sections import parse_pip

_TILDE_INSIDE_BACKTICKS = "````md\n~~~\n# not a heading\n- [ ] not a box\n````\n# real\n- [x] real box\n"
_SHORT_INSIDE_LONG = "````\n```\n## fake\n- [ ] fake\n```\n````\n## real\n"


def test_other_fence_character_does_not_close_block() -> None:
    doc = parse_pip(_TILDE_INSIDE_BACKTICKS)
    assert [h.text for h in doc.headings] == ["real"]
    assert [(b.checked, b.line) for b in doc.boxes] == [(True, 7)]


def test_shorter_fence_does_not_close_block() -> None:
    doc = parse_pip(_SHORT_INSIDE_LONG)
    assert [(h.text, h.line) for h in doc.headings] == [("real", 7)]
    assert doc.boxes == ()


def test_fence_with_info_string_does_not_close_block() -> None:
    doc = parse_pip("```\n```python\n# hidden\n```\n# shown\n")
    assert [h.text for h in doc.headings] == ["shown"]
