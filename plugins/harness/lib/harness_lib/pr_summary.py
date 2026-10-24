"""PR summary model and renderer (pr-sum mechanics).

``PrFacts`` holds what local git and one ``gh pr view`` read establish about a PR. ``PrDraft`` holds the
prose an agent writes: the derived title, the Summary, one description per listed source file and, from
level 2 up, the flowchart, diagram and table sections. ``render_summary`` lays both out as the summary
markdown the driver saves under the project's configured ``artifacts.summaries`` directory, so counts and
file rows are never re-typed. Artifact classification goes through
``branch_commits.path_bucket`` (the project's configured commit buckets). Git and gh are not run here.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Tuple

from harness_lib.branch_commits import Bucket, path_bucket
from harness_lib.commit_txt import vendor_names

MONOSPACE_WIDTH = 120
TABLE_CELL_WIDTH = 40
ARTIFACT_TAG = "(machine-generated artifact)"
CHANGE_CODES = "Change codes: A = added, M = modified, D = deleted, R = renamed"
_FENCE = "```"
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL = re.compile(r":?-+:?")
_FLOW_HEADING = "Behavior:"
_NEW_FLOW_HEADING = "New Behavior:"
_FLOW_TAGS = ("[changed]", "[new]")
_SHAPE_HEADINGS = ("Module Relocations", "Symbol Relocations", "Call-Site Migration", "Rule Illustration")
_LEVEL3_SHAPE_HEADINGS = (*_SHAPE_HEADINGS, "Sequence Diagram", "Data Flow")
_SYMBOLS_HEADING = "Changed Symbols"
_KIND_ORDER = ("flow", "shape", "symbols")
_MAX_FLOWS = {2: 3, 3: 5}
LEVELS = (1, 2, 3)
DEFAULT_LEVEL = 2


@dataclass(frozen=True)
class PrFile:
    """One changed path: status letter (A/M/D/R), path, pre-rename path, changed-line counts, binary flag,
    and whether the path is untracked (a working-tree capture only).

    Git reports no line counts for a binary file, so ``added`` and ``deleted`` read zero there.
    """

    status: str
    path: str
    old_path: Optional[str]
    added: int
    deleted: int
    binary: bool = False
    untracked: bool = False

    @property
    def artifact(self) -> bool:
        """True for a machine-generated artifact path: one ``path_bucket`` places in the Artifact bucket."""
        return path_bucket(self.path) is Bucket.ARTIFACT

    @property
    def relocated(self) -> bool:
        """True for a pure move: a text rename with no changed lines (binary zero counts prove nothing)."""
        return self.status == "R" and not self.binary and self.added == 0 and self.deleted == 0


@dataclass(frozen=True)
class PrFacts:
    """Script-owned facts: PR identity, refs, commit lines (``<sha> <subject>``, oldest first), files.

    ``head_source`` is ``remote`` when ``head_sha`` is the PR head ``gh`` reports and ``local`` when it is
    the checked-out PR branch's HEAD; ``working_tree`` adds that checkout's uncommitted and untracked changes.
    ``local_branch`` names the branch a local capture read (empty on a detached HEAD); None for a remote
    capture and for payloads written before the field existed, which read as the PR branch.
    """

    number: int
    pr_title: str
    head: str
    base: str
    head_sha: str
    merge_base: str
    date: str
    commits: Tuple[str, ...]
    files: Tuple[PrFile, ...]
    head_source: str = "remote"
    working_tree: bool = False
    local_branch: Optional[str] = None

    @property
    def additions(self) -> int:
        """Added lines across every file."""
        return sum(f.added for f in self.files)

    @property
    def deletions(self) -> int:
        """Deleted lines across every file."""
        return sum(f.deleted for f in self.files)

    @property
    def listed(self) -> Tuple[PrFile, ...]:
        """Files Changed table rows: every file except pure moves."""
        return tuple(f for f in self.files if not f.relocated)

    @property
    def relocated(self) -> Tuple[PrFile, ...]:
        """Pure moves, shown in the Relocated section."""
        return tuple(f for f in self.files if f.relocated)

    @property
    def described(self) -> Tuple[str, ...]:
        """Paths whose row needs a drafted description: listed, non-artifact files."""
        return tuple(f.path for f in self.listed if not f.artifact)


@dataclass(frozen=True)
class PrSection:
    """One drafted markdown section (levels 2 and 3): a heading and its body."""

    heading: str
    body: str


@dataclass(frozen=True)
class PrDraft:
    """Agent-owned prose: derived title, Summary, per-path descriptions, visual sections."""

    title: str = ""
    summary: str = ""
    descriptions: Dict[str, str] = field(default_factory=dict)
    sections: Tuple[PrSection, ...] = ()


def new_draft(facts: PrFacts) -> PrDraft:
    """Empty draft with one description slot per path that needs one."""
    return PrDraft(descriptions={path: "" for path in facts.described})


def skeleton(facts: PrFacts, draft: PrDraft) -> Dict[str, object]:
    """JSON skeleton: ``facts`` (script-owned) and ``draft`` (agent-owned)."""
    return {"facts": asdict(facts), "draft": asdict(draft)}


def facts_from_payload(raw: Mapping[str, object]) -> PrFacts:
    """Inverse of ``asdict(PrFacts)``; malformed input raises ``KeyError``, ``TypeError`` or ``ValueError``.

    Payloads written before ``PrFile.binary`` existed read with ``binary`` False; payloads without the
    source fields read as a committed capture of the remote PR head.
    """
    files = tuple(PrFile(**entry) for entry in raw["files"])
    return PrFacts(**{**raw, "commits": tuple(raw["commits"]), "files": files})


def _text(value: object) -> str:
    """A drafted string, or a list of lines joined with newlines; None reads as empty."""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(line) for line in value)
    return str(value or "")


def draft_from_payload(raw: Mapping[str, object]) -> PrDraft:
    """Inverse of ``asdict(PrDraft)``; missing keys and None read as empty; any string may be a line list.

    ``descriptions`` must be an object and each ``sections`` entry an object; callers check the shapes.
    """
    sections = tuple(
        PrSection(_text(s.get("heading")), _text(s.get("body"))) for s in raw.get("sections") or ()
    )
    descriptions = {str(k): _text(v) for k, v in (raw.get("descriptions") or {}).items()}
    return PrDraft(_text(raw.get("title")), _text(raw.get("summary")), descriptions, sections)


def summary_filename(number: int, title: str) -> str:
    """``<NNNN>_<Title>.md``: zero-padded PR number; runs other than letters, digits, hyphens become ``_``."""
    return f"{number:04d}_{re.sub(r'[^A-Za-z0-9-]+', '_', title).strip('_')}.md"


def _description_problems(facts: PrFacts, draft: PrDraft) -> List[str]:
    """Missing descriptions for described paths, and descriptions for paths not in the PR."""
    known = {f.path for f in facts.files}
    problems = [
        f"no description for `{p}`" for p in facts.described if not draft.descriptions.get(p, "").strip()
    ]
    problems += [
        f"description for `{p}`, which is not a changed path" for p in draft.descriptions if p not in known
    ]
    return problems


def _split_fences(body: str) -> Tuple[List[str], List[str]]:
    """``(fenced, open)``: lines inside fenced code blocks, and lines outside them (fence markers dropped)."""
    fenced: List[str] = []
    open_lines: List[str] = []
    inside = False
    for line in body.splitlines():
        if line.strip().startswith(_FENCE):
            inside = not inside
        else:
            (fenced if inside else open_lines).append(line)
    return fenced, open_lines


def _fenced_lines(body: str) -> List[str]:
    """Lines inside fenced code blocks."""
    return _split_fences(body)[0]


def _fence_blocks(body: str) -> List[List[str]]:
    """Each fenced code block's lines, in order; an unclosed trailing fence counts as a block."""
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in body.splitlines():
        if not line.strip().startswith(_FENCE):
            if current is not None:
                current.append(line)
        elif current is None:
            current = []
        else:
            blocks.append(current)
            current = None
    return blocks + ([current] if current is not None else [])


def _flow_problems(section: PrSection) -> List[str]:
    """Flow labels and tag placement of a ``Behavior:`` section.

    Two forms pass the label check: stacked fences, one whose first line starts with BEFORE and one whose
    first line holds AFTER; or one side-by-side fence whose first line holds both. Change tags are checked
    only in a stacked BEFORE fence; tags in a side-by-side fence are not checked.
    """
    if not section.heading.strip().startswith(_FLOW_HEADING):
        return []
    blocks = [(block[0].strip() if block else "", block) for block in _fence_blocks(section.body)]
    before = any(first.startswith("BEFORE") for first, _ in blocks)
    labelled = before and any("AFTER" in first for first, _ in blocks)
    before_only = [block for first, block in blocks if first.startswith("BEFORE") and "AFTER" not in first]
    tagged = any(tag in line for block in before_only for line in block for tag in _FLOW_TAGS)
    problems = [] if labelled else [
        f"section '{section.heading}': needs a fence whose first line is BEFORE and one whose first line is "
        "AFTER, or one side-by-side fence whose first line holds both",
    ]
    misplaced = f"section '{section.heading}': [changed] / [new] tags belong in the AFTER flow only"
    return problems + ([misplaced] if tagged else [])


def _section_kind(heading: str, level: int = 2) -> Optional[str]:
    """``flow``, ``shape`` or ``symbols`` for a heading known at ``level``; None otherwise."""
    heading = heading.strip()
    if heading.startswith((_FLOW_HEADING, _NEW_FLOW_HEADING)):
        return "flow"
    if heading in (_LEVEL3_SHAPE_HEADINGS if level >= 3 else _SHAPE_HEADINGS):
        return "shape"
    return "symbols" if heading == _SYMBOLS_HEADING else None


def _shape_count_problems(draft: PrDraft, kinds: List[Optional[str]], level: int) -> List[str]:
    """Shape diagram limit: one at level 2; at level 3 each shape heading at most once."""
    headings = [s.heading.strip() for s, kind in zip(draft.sections, kinds) if kind == "shape"]
    if level < 3:
        return [] if len(headings) <= 1 else [f"at most one shape diagram (found {len(headings)})"]
    return [f"shape diagram '{h}' appears {headings.count(h)} times; use each at most once"
            for h in dict.fromkeys(headings) if headings.count(h) > 1]


def _layout_problems(draft: PrDraft, level: int = 2) -> List[str]:
    """Layout checks of the visual sections.

    Known headings (a blank heading is left to the no-heading check); a flow or shape diagram; exactly one
    Changed Symbols; the shape limit and the flow limit of ``level``; flows, shape, symbols order.
    """
    kinds = [_section_kind(s.heading, level) for s in draft.sections]
    problems = [
        f"section '{s.heading}': unknown heading; use 'Behavior: <trigger>', 'New Behavior: <trigger>', "
        f"a shape diagram name or '{_SYMBOLS_HEADING}'"
        for s, kind in zip(draft.sections, kinds) if kind is None and s.heading.strip()
    ]
    flows, shapes, symbols = (kinds.count(kind) for kind in _KIND_ORDER)
    problems += [] if flows or shapes else ["a visual summary needs a behavior flow or a shape diagram"]
    problems += [] if symbols == 1 else [
        f"a visual summary needs exactly one '{_SYMBOLS_HEADING}' section (found {symbols})",
    ]
    problems += _shape_count_problems(draft, kinds, level)
    limit = _MAX_FLOWS[level]
    problems += [] if flows <= limit else [f"at most {limit} behavior flows (found {flows})"]
    ranks = [_KIND_ORDER.index(kind) for kind in kinds if kind is not None]
    return problems + ([] if ranks == sorted(ranks) else [
        "sections out of order: behavior flows, then the shape diagram, then Changed Symbols",
    ])


def _table_cells(body: str) -> List[str]:
    """Cells of the markdown table rows outside fences; separator rows skipped, ``\\|`` kept inside a cell."""
    rows = [line.strip() for line in _split_fences(body)[1] if line.strip().startswith("|")]
    cells = [cell.strip() for row in rows for cell in _CELL_SPLIT.split(row.strip("|"))]
    return [cell for cell in cells if not _SEPARATOR_CELL.fullmatch(cell)]


def _section_problems(draft: PrDraft, level: int) -> List[str]:
    """Section checks.

    Sections required (levels 2 and 3) or forbidden (level 1); the layout checks; every heading set; fenced
    lines within ``MONOSPACE_WIDTH``; table cells outside fences within ``TABLE_CELL_WIDTH``; and the
    ``Behavior:`` flow labels and tag placement.
    """
    if level == 1:
        misplaced = ["sections are for levels 2 and 3; remove them or build with --level 2"]
        return misplaced if draft.sections else []
    if not draft.sections:
        return ["a visual summary needs its sections (behavior flows or a shape diagram, Changed Symbols)"]
    problems = _layout_problems(draft, level)
    for section in draft.sections:
        problems += [] if section.heading.strip() else ["a section has no heading"]
        problems += [
            f"section '{section.heading}': monospace line of {len(line)} chars (limit {MONOSPACE_WIDTH})"
            for line in _fenced_lines(section.body) if len(line) > MONOSPACE_WIDTH
        ]
        problems += [
            f"section '{section.heading}': table cell of {len(cell)} chars (limit {TABLE_CELL_WIDTH}); "
            "move the text above or below the table"
            for cell in _table_cells(section.body) if len(cell) > TABLE_CELL_WIDTH
        ]
        problems += _flow_problems(section)
    return problems


def _prose(draft: PrDraft) -> str:
    """Every drafted string, for the vendor-name check."""
    sections = [f"{s.heading}\n{s.body}" for s in draft.sections]
    return "\n".join([draft.title, draft.summary, *draft.descriptions.values(), *sections])


def draft_problems(facts: PrFacts, draft: PrDraft, level: int = DEFAULT_LEVEL) -> List[str]:
    """Every defect in ``draft``, one line each; empty when the summary can be built.

    ``level`` 1 is plain, 2 the visual layout, 3 the visual layout with more diagram types.
    """
    problems = [] if draft.title.strip() else ["draft title is empty"]
    problems += ["draft title spans more than one line"] if "\n" in draft.title.strip() else []
    problems += [] if draft.summary.strip() else ["draft summary is empty"]
    problems += _description_problems(facts, draft)
    problems += _section_problems(draft, level)
    problems += [f"vendor name {name!r} in the draft" for name in vendor_names(_prose(draft))]
    return problems


def artifact_note(facts: PrFacts) -> Optional[str]:
    """The artifact-noise Note line when artifact files account for more than half of the changed lines."""
    artifacts = [f for f in facts.files if f.artifact]
    added, deleted = sum(f.added for f in artifacts), sum(f.deleted for f in artifacts)
    if 2 * (added + deleted) <= facts.additions + facts.deletions:
        return None
    return (
        f"***Note:*** {len(artifacts)} machine-generated artifact file(s) account for "
        f"+{added}/-{deleted} of the +{facts.additions}/-{facts.deletions} headline; the source delta is "
        f"+{facts.additions - added}/-{facts.deletions - deleted}."
    )


def _cell(text: str) -> str:
    """Single-line table cell with pipes escaped."""
    return " ".join(text.split()).replace("|", "\\|")


def _details(summary: str, body: List[str]) -> List[str]:
    """Collapsed ``<details>`` block."""
    return [f"<details><summary>{summary}</summary>", "<p>", "", *body, "", "</p>", "</details>"]


def _file_row(file: PrFile, description: str) -> str:
    """Files Changed row; a rename shows ``old → new``, an artifact carries the artifact tag."""
    shown = f"`{file.old_path}` → `{file.path}`" if file.old_path else f"`{file.path}`"
    text = " ".join(part for part in (description.strip(), ARTIFACT_TAG if file.artifact else "") if part)
    return f"| {shown} | {file.status} | {_cell(text)} |"


def _files_block(facts: PrFacts, draft: PrDraft) -> List[str]:
    """Collapsed Files Changed table."""
    rows = [_file_row(f, draft.descriptions.get(f.path, "")) for f in facts.listed]
    table = ["| File | Change | Description |", "|------|--------|-------------|", *rows, "", CHANGE_CODES]
    return _details(f"Files Changed ({len(facts.listed)})", table)


def _relocated_block(facts: PrFacts) -> List[str]:
    """Collapsed Relocated table (file name, old directory, new directory); empty without pure moves."""
    if not facts.relocated:
        return []
    rows = [
        f"| `{PurePosixPath(f.path).name}` | `{PurePosixPath(f.old_path or '').parent}/` "
        f"| `{PurePosixPath(f.path).parent}/` |"
        for f in facts.relocated
    ]
    table = ["| File | From | To |", "|------|------|----|", *rows]
    return ["", *_details(f"Relocated {len(facts.relocated)} files", table)]


def _source_line(facts: PrFacts) -> List[str]:
    """``**Source:**`` line for a local capture (the PR branch, or the checkout ``--local`` read); none for
    the remote PR head."""
    if facts.head_source != "local":
        return []
    extra = ", plus uncommitted changes" if facts.working_tree else ""
    return [f"**Source:** {_checkout_label(facts)} at `{facts.head_sha[:7]}`{extra}"]


def _checkout_label(facts: PrFacts) -> str:
    """``local branch`` for the PR branch; otherwise the other branch named, or a detached checkout."""
    if facts.local_branch is None or facts.local_branch == facts.head:
        return "local branch"
    return f"local checkout `{facts.local_branch}`" if facts.local_branch else "local detached checkout"


def _header(facts: PrFacts, title: str) -> List[str]:
    """Title line and the Branch / Base / Date / Source / Files Changed envelope; pure moves counted when
    present."""
    moved = f", {len(facts.relocated)} relocated" if facts.relocated else ""
    return [
        f"# PR #{facts.number}: {title.strip()}", "", f"**Branch:** {facts.head}", f"**Base:** {facts.base}",
        f"**Date:** {facts.date}", *_source_line(facts),
        f"**Files Changed:** {len(facts.files)} (+{facts.additions} / -{facts.deletions} lines{moved})",
    ]


def render_summary(facts: PrFacts, draft: PrDraft) -> str:
    """Summary markdown: header, Summary, Note, drafted sections, Files Changed, Relocated."""
    note = artifact_note(facts)
    lines = [*_header(facts, draft.title), "", "## Summary", "", draft.summary.strip()]
    lines += ["", note] if note else []
    for section in draft.sections:
        lines += ["", f"## {section.heading.strip()}", "", section.body.strip()]
    lines += ["", *_files_block(facts, draft), *_relocated_block(facts)]
    return "\n".join(lines) + "\n"
