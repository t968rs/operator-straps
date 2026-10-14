"""Bound the diff a commit-message drafter reads (branch-commit-msg mechanics).

Messages are derived from diffs, but generated or data files (a regenerated report, a re-saved registry)
change thousands of lines whose meaning fits in a sentence. Per-path and per-block line budgets decide
which paths are read in full and which are reduced to a summary: key tallies for JSON, a truncated head
for everything else. Git is not run here; callers pass ``git diff --numstat -z`` and unified diff text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Sequence, Tuple

PATH_BUDGET = 250
ADDED_PATH_BUDGET = 80
JSON_PATH_BUDGET = 40
BLOCK_BUDGET = 300
TEXT_HEAD_LINES = 40
JSON_TOP_KEYS = 12
SAMPLE_WIDTH = 100
LINE_WIDTH = 200
SECTION_CHAR_BUDGET = 12_000
BLOCK_CHAR_BUDGET = 30_000

_KEYED_LINE = re.compile(r'^([+-])\s*"([^"]+)"\s*:')


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
    """Key tallies, plus a truncated diff head when keyed lines miss most of the change."""
    tally = _json_tally(diff_text)
    shown = min(len(tally), JSON_TOP_KEYS)
    lines = [f"{path}: JSON diff summary, {len(tally)} keys changed (top {shown} shown)"]
    lines += _tally_lines(tally)
    if _tally_misses_most(tally, diff_text):
        lines += ["  most changed lines carry no key; diff head follows:", _summarize_text(diff_text)]
    return "\n".join(lines)


def _summarize_text(diff_text: str) -> str:
    """First ``TEXT_HEAD_LINES`` diff lines plus a count of the rest."""
    lines = diff_text.rstrip("\n").splitlines()
    if len(lines) <= TEXT_HEAD_LINES:
        return "\n".join(lines)
    omitted = len(lines) - TEXT_HEAD_LINES
    return "\n".join([*lines[:TEXT_HEAD_LINES], f"... {omitted} more diff lines omitted"])


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


def cap_sections(sections: Sequence[str], budget: int = BLOCK_CHAR_BUDGET) -> List[str]:
    """Keep sections whole until ``budget`` characters are spent; later ones keep only their header line."""
    capped: List[str] = []
    spent = 0
    for section in sections:
        if spent >= budget:
            capped.append(f"{section.split(chr(10), 1)[0]}\n[omitted: block output budget spent]")
        else:
            capped.append(section)
            spent += len(section) + 1
    return capped


def summarize_diff(path: str, diff_text: str) -> str:
    """Bounded stand-in for a full unified diff: key tallies for JSON, a truncated head otherwise."""
    if PurePosixPath(path).suffix.lower() == ".json":
        return clip_text(_summarize_json(path, diff_text))
    return clip_text(_summarize_text(diff_text))
