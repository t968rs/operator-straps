"""Bound the diff a commit-message drafter reads (branch-commit-msg mechanics).

Messages are derived from diffs, but generated or data files (a regenerated report, a re-saved registry)
change thousands of lines whose meaning fits in a sentence. Per-path and per-block line budgets decide
which paths are read in full and which are reduced to a summary: key tallies for JSON, a hunk outline for a
text diff of several hunks, and a truncated head plus the definitions past it for a single hunk or a new file.
A per-block character budget then applies: while a block is over it, full diffs become summaries (the
highest demotion rank first, then the largest) before any path is cut to its header.
Every summary stays under a fixed line budget, so its size follows the hunk count, never the changed-line
count. Git is not run here; callers pass ``git diff --numstat -z`` and unified diff text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

PATH_BUDGET = 250
ADDED_PATH_BUDGET = 80
JSON_PATH_BUDGET = 40
BLOCK_BUDGET = 300
TEXT_HEAD_LINES = 40
JSON_TOP_KEYS = 12
SAMPLE_WIDTH = 100
LINE_WIDTH = 200
SECTION_CHAR_BUDGET = 12_000
# Under the 30,000-character tool output a shell call shows inline: longer output is saved to a file the
# drafter then reads back in chunks, one extra call each. The budget bounds the kept sections only: each
# path cut to its header adds that header and an omission line beyond it, so a block with hundreds of cut
# paths can still pass 30,000.
BLOCK_CHAR_BUDGET = 24_000
OUTLINE_LINES = 120
HUNK_SAMPLE_PER_SIDE = 3

_KEYED_LINE = re.compile(r'^([+-])\s*"([^"]+)"\s*:')
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_DEFINITION = re.compile(r"^\+\s*(?:(?:async\s+)?def|class|function|interface|enum|(?:export\s+)+\w+)\s+\w")
# Read as a heading only in Markdown: elsewhere a column-0 ``#`` line is a comment.
_HEADING = re.compile(r"^\+#{1,4}\s+\S")
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdx"})


@dataclass(frozen=True)
class DiffStat:
    """Added and deleted line counts for one path (binary files count as zero)."""

    path: str
    added: int
    deleted: int

    @property
    def changed(self) -> int:
        """Total changed lines."""
        return self.added + self.deleted


def _count(raw: str) -> int:
    """Parse a numstat count; ``-`` (binary) is zero."""
    return int(raw) if raw.isdigit() else 0


def parse_numstat_z(text: str) -> List[DiffStat]:
    """Parse ``git diff --numstat -M -z`` output; a rename is recorded under its new path."""
    tokens = text.split("\0")
    stats: List[DiffStat] = []
    pos = 0
    while pos < len(tokens) and tokens[pos]:
        added, deleted, path = tokens[pos].split("\t", 2)
        pos += 1
        if not path:
            path, pos = tokens[pos + 1], pos + 2
        stats.append(DiffStat(path, _count(added), _count(deleted)))
    return stats


def path_budget(path: str) -> int:
    """Changed-line budget for one path: tighter for JSON, whose diffs are mostly data."""
    return JSON_PATH_BUDGET if PurePosixPath(path).suffix.lower() == ".json" else PATH_BUDGET


def read_budget(stat: DiffStat) -> int:
    """Changed-line budget for one stat: a pure addition needs only its head (docstring, public names)."""
    budget = path_budget(stat.path)
    return min(budget, ADDED_PATH_BUDGET) if stat.added and not stat.deleted else budget


def plan_reads(stats: Sequence[DiffStat], block_budget: int = BLOCK_BUDGET) -> Dict[str, str]:
    """Map each path to ``full`` or ``summary``, in order; summarized paths consume no block budget."""
    modes: Dict[str, str] = {}
    spent = 0
    for stat in stats:
        full = stat.changed <= read_budget(stat) and spent + stat.changed <= block_budget
        modes[stat.path] = "full" if full else "summary"
        spent += stat.changed if full else 0
    return modes


def _trim(line: str) -> str:
    """Strip and cap a sample line."""
    return line.strip()[:SAMPLE_WIDTH]


def _json_tally(diff_text: str) -> Dict[str, Tuple[List[str], List[str]]]:
    """Group added and removed keyed lines by JSON key, in first-seen order."""
    tally: Dict[str, Tuple[List[str], List[str]]] = {}
    for line in diff_text.splitlines():
        match = _KEYED_LINE.match(line) if not line.startswith(("+++", "---")) else None
        if match:
            added, removed = tally.setdefault(match.group(2), ([], []))
            (added if match.group(1) == "+" else removed).append(line[1:])
    return tally


def _changed_count(diff_text: str) -> int:
    """Count added and removed diff lines, excluding ``+++`` / ``---`` file headers."""
    return sum(
        1
        for line in diff_text.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _tally_misses_most(tally: Dict[str, Tuple[List[str], List[str]]], diff_text: str) -> bool:
    """True when keyed lines cover under half the changed lines (array-only or scalar-list edits)."""
    keyed = sum(len(added) + len(removed) for added, removed in tally.values())
    return 2 * keyed < _changed_count(diff_text)


def _tally_lines(tally: Dict[str, Tuple[List[str], List[str]]]) -> List[str]:
    """One count line per key plus one sample line per side, largest keys first, top ``JSON_TOP_KEYS``."""
    ranked = sorted(tally.items(), key=lambda item: -(len(item[1][0]) + len(item[1][1])))
    lines: List[str] = []
    for key, (added, removed) in ranked[:JSON_TOP_KEYS]:
        lines.append(f"  {key}: +{len(added)} -{len(removed)}")
        lines += [f"    + {_trim(added[0])}"] if added else []
        lines += [f"    - {_trim(removed[0])}"] if removed else []
    return lines


def _summarize_json(path: str, diff_text: str) -> str:
    """Key tallies, plus the text summary (outline or head) when keyed lines miss most of the change."""
    tally = _json_tally(diff_text)
    shown = min(len(tally), JSON_TOP_KEYS)
    lines = [f"{path}: JSON diff summary, {len(tally)} keys changed (top {shown} shown)"]
    lines += _tally_lines(tally)
    if _tally_misses_most(tally, diff_text):
        lines += ["  most changed lines carry no key; text summary follows:"]
        lines.append(_summarize_text(path, diff_text))
    return "\n".join(lines)


def _split_hunks(lines: Sequence[str]) -> List[List[str]]:
    """The hunks of a unified diff, each opening with its ``@@`` line; file header lines are dropped."""
    hunks: List[List[str]] = []
    for line in lines:
        if _HUNK_HEADER.match(line):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
    return hunks


def _hunk_lines(hunk: Sequence[str], per_side: int) -> List[str]:
    """A hunk's ``@@`` line with its counts, then its first ``per_side`` removed and added lines."""
    removed = [line for line in hunk[1:] if line.startswith("-")]
    added = [line for line in hunk[1:] if line.startswith("+")]
    lines = [f"{hunk[0]}  [+{len(added)} -{len(removed)}]"]
    if not per_side:
        return lines
    shown = removed[:per_side] + added[:per_side]
    lines += [f"{line[0]} {_trim(line[1:])}" for line in shown]
    rest = len(removed) + len(added) - len(shown)
    return lines + ([f"  ... {rest} more changed lines"] if rest else [])


def _outline(hunks: Sequence[Sequence[str]]) -> str:
    """Hunks under ``OUTLINE_LINES``: samples shrink as hunks grow, then only headers are listed, and
    past ``OUTLINE_LINES - 2`` headers the remaining hunks are only counted."""
    per_hunk = (OUTLINE_LINES - 1) // len(hunks)
    per_side = max(0, min(HUNK_SAMPLE_PER_SIDE, (per_hunk - 2) // 2))
    listed = hunks if per_side else hunks[:OUTLINE_LINES - 2]
    lines = [f"{len(hunks)} hunks, each with its first changed lines; the counts cover the whole hunk"]
    for hunk in listed:
        lines += _hunk_lines(hunk, per_side)
    left = len(hunks) - len(listed)
    return "\n".join(lines + ([f"... {left} more hunks omitted"] if left else []))


def _is_markdown(path: str) -> bool:
    """True for a Markdown path, whose ``#`` lines are headings rather than comments."""
    return PurePosixPath(path).suffix.lower() in _MARKDOWN_SUFFIXES


def _is_definition(line: str, markdown: bool) -> bool:
    """True for an added ``def``/``class``/``export ...`` line, or a ``#`` heading in Markdown."""
    return bool(_DEFINITION.match(line) or (markdown and _HEADING.match(line)))


def _definitions(lines: Sequence[str], markdown: bool) -> List[str]:
    """Added ``def``, ``class`` and ``export ...`` lines, plus ``#`` headings in Markdown, capped."""
    found = [f"+ {_trim(line[1:])}" for line in lines if _is_definition(line, markdown)]
    return found[:OUTLINE_LINES - TEXT_HEAD_LINES - 2]


def _head(lines: Sequence[str], markdown: bool) -> str:
    """First ``TEXT_HEAD_LINES`` diff lines, a count of the rest, and the definitions added past the head."""
    if len(lines) <= TEXT_HEAD_LINES:
        return "\n".join(lines)
    omitted = len(lines) - TEXT_HEAD_LINES
    kept = [*lines[:TEXT_HEAD_LINES], f"... {omitted} more diff lines omitted"]
    names = _definitions(lines[TEXT_HEAD_LINES:], markdown)
    return "\n".join(kept + (["definitions past the head:", *names] if names else []))


def _summarize_text(path: str, diff_text: str) -> str:
    """A hunk outline for a diff of several hunks, else the head and the definitions past it."""
    lines = diff_text.rstrip("\n").splitlines()
    hunks = _split_hunks(lines)
    return _outline(hunks) if len(hunks) > 1 else _head(lines, _is_markdown(path))


def _clip_line(line: str) -> str:
    """Cap one line at ``LINE_WIDTH`` characters, noting how many were cut."""
    if len(line) <= LINE_WIDTH:
        return line
    return f"{line[:LINE_WIDTH]} ...[+{len(line) - LINE_WIDTH} chars]"


def clip_text(text: str, char_budget: int = SECTION_CHAR_BUDGET) -> str:
    """Bound ``text`` by characters, not lines: each line capped at ``LINE_WIDTH``, output at ``char_budget``.

    A minified or generated file can put megabytes on one changed line, so line counts alone do not
    bound output.
    """
    lines = text.rstrip("\n").splitlines()
    kept: List[str] = []
    spent = 0
    for index, line in enumerate(lines):
        clipped = _clip_line(line)
        if spent + len(clipped) + 1 > char_budget:
            kept.append(f"... {len(lines) - index} more diff lines omitted (character budget)")
            break
        kept.append(clipped)
        spent += len(clipped) + 1
    return "\n".join(kept)


def render_section(stat: DiffStat, mode: str, text: str) -> str:
    """One ``=== path [mode, +A -D] ===`` section: the diff ``text`` (character-clipped) or its summary."""
    body = clip_text(text) if mode == "full" else summarize_diff(stat.path, text)
    return f"=== {stat.path} [{mode}, +{stat.added} -{stat.deleted}] ===\n{body}"


def _demote_largest(
        stats: Sequence[DiffStat], modes: Dict[str, str], texts: Mapping[str, str], rendered: Dict[str, str],
        rank: Mapping[str, int],
) -> bool:
    """Swap a full section that a summary shortens for that summary, the highest ``rank`` (least needed in
    full) and then the largest first; False when no summary shortens any."""
    for stat in sorted(stats, key=lambda s: (-rank.get(s.path, 0), -len(rendered[s.path]))):
        if modes[stat.path] != "full":
            continue
        summary = render_section(stat, "summary", texts[stat.path])
        modes[stat.path] = "summary"
        if len(summary) < len(rendered[stat.path]):
            rendered[stat.path] = summary
            return True
        modes[stat.path] = "full"
    return False


def fit_sections(
        stats: Sequence[DiffStat], modes: Mapping[str, str], texts: Mapping[str, str],
        budget: int = BLOCK_CHAR_BUDGET, rank: Optional[Mapping[str, int]] = None,
) -> List[str]:
    """Rendered sections in ``stats`` order, the kept ones under ``budget`` characters.

    While the block is over budget, a full section becomes its summary (highest ``rank`` first, a path
    absent from it ranking 0, then the largest), so every path keeps some content before any is cut; a
    section that still does not fit keeps only its header line, and a later, smaller one may still fit.
    Each cut section adds its header and an omission line beyond ``budget``, without a ceiling.
    """
    current = dict(modes)
    rendered = {s.path: render_section(s, current[s.path], texts[s.path]) for s in stats}
    while sum(len(text) + 1 for text in rendered.values()) > budget:
        if not _demote_largest(stats, current, texts, rendered, rank or {}):
            break
    return _fit_cut([rendered[s.path] for s in stats], budget)


def _omitted(section: str) -> str:
    """A section cut to its header line."""
    return f"{section.split(chr(10), 1)[0]}\n[omitted: block output budget spent]"


def cap_sections(sections: Sequence[str], budget: int = BLOCK_CHAR_BUDGET) -> List[str]:
    """Keep sections whole until ``budget`` characters are spent; later ones keep only their header line."""
    capped: List[str] = []
    spent = 0
    for section in sections:
        if spent >= budget:
            capped.append(_omitted(section))
        else:
            capped.append(section)
            spent += len(section) + 1
    return capped


def _fit_cut(sections: Sequence[str], budget: int) -> List[str]:
    """Keep each section that still fits in ``budget`` (the first always does); the rest keep their header.

    The headers of cut sections count toward ``spent`` but are never cut themselves, so the total can pass
    ``budget`` by one header pair per cut section.
    """
    kept: List[str] = []
    spent = 0
    for section in sections:
        cut = bool(spent) and spent + len(section) + 1 > budget
        kept.append(_omitted(section) if cut else section)
        spent += len(kept[-1]) + 1
    return kept


def summarize_diff(path: str, diff_text: str) -> str:
    """Bounded stand-in for a full unified diff: key tallies for JSON, a hunk outline or a head otherwise."""
    if PurePosixPath(path).suffix.lower() == ".json":
        return clip_text(_summarize_json(path, diff_text))
    return clip_text(_summarize_text(path, diff_text))
