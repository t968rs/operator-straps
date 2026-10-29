"""Bubble memo format: anchors, scaffold, completeness check, investigator facts and the reviewer model.

The memo is the developer's decision sheet for issues a pr-review bubbled up. Anchors (index header,
status words, Decision line, entry heading, stub marker) are the contract that the stamping mod mirrors;
prose between the anchors is free. Everything here is pure: text in, text or problem lines out. The
project root is always an argument, and nothing is read from configuration.

Format rules that other implementations (the stamping mod) mirror:

- Entry boundary: an entry runs from its `### <ID>.` heading to the next line that starts with `### ` or
  `## `, or that is exactly `---` with no indentation (trailing blanks allowed). An indented `---`, such as
  one inside a flow diagram, never ends an entry. An entry heading id has the review-id shape
  (`[A-Z]+[0-9]+`); any other `### ` line is prose that still ends the previous entry.
- Line endings: `\\r\\n` is read as `\\n` by `check_memo`, `add_missing`, `apply_facts`, `entry_blocks` and
  `parse_index`; text returned by `add_missing` and `apply_facts` uses `\\n` when it changed.
- Reference tokens: only a backticked `path:line` or `path:start-end` span counts as a reference; other code
  spans are prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from harness_lib.review_merge import CLOSED_STATUSES, TIERS

MEMO_SUFFIX = "_Bubbles.md"
INDEX_HEADER = "| ID | Class | Status | Decision | Tracked in |"
INDEX_RULE = "|----|-------|--------|----------|------------|"
STATUS_OPEN = "Open"
STATUS_DECIDED = "Decided"
DECISION_OPEN = "- **Decision:** open"
DECISION_PREFIX = "- **Decision:** "
ENTRY_PREFIX = "### "
STUB = "TODO(fill)"
UNCLASSIFIED = "unclassified"

_FIELD_PREFIX = "- **"
_CLASS, _DESCRIPTION, _REFERENCES = "Class", "Description", "References"
_CURRENT, _WHEN, _CHAIN = "Current behavior", "When", "Chain"
_EXPECTED, _RECOMMENDATION, _DECISION = "Expected behavior per fix", "Recommendation", "Decision"
_FENCE = "  ```"

_HEADING_RE = re.compile(r"^" + re.escape(ENTRY_PREFIX) + r"([A-Z]+[0-9]+)\.(?:\s|$)")
_REF_RE = re.compile(r"(.+?):(\d+)(?:-(\d+))?")
_LINES_RE = re.compile(r"\d+(?:-\d+)?")
_TOKEN_RE = re.compile(r"`([^`]*)`")
_OPTION_RE = re.compile(r"^\s*- \(\w+\) ")
_STEP_NUMBER_RE = re.compile(r"^\d+[.)]\s+")


@dataclass(frozen=True)
class Bubbled:
    """One currently bubbled issue: its id, classification and the reason it was bubbled."""

    id: str
    cls: str
    reason: str


@dataclass(frozen=True)
class IndexRow:
    """One row of the memo's index table."""

    id: str
    cls: str
    status: str
    decision: str
    tracked: str


def memo_name(pr: Union[int, str]) -> str:
    """File name of the memo for a PR number (unpadded)."""
    return f"PR_{pr}{MEMO_SUFFIX}"


def _one_line(value: Any) -> str:
    return " ".join(str(value).split())


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _label(index: int) -> str:
    return chr(ord("a") + index) if index < 26 else str(index + 1)


# ---------------------------------------------------------------- review JSON readers

def find_issue(doc: Mapping[str, Any], issue_id: str) -> Optional[Mapping[str, Any]]:
    """The review JSON issue with this id, or None."""
    issues = doc.get("issues") or {}
    for tier in TIERS:
        for issue in issues.get(tier) or []:
            if issue.get("id") == issue_id:
                return issue
    return None


def issue_files(issue: Mapping[str, Any]) -> List[str]:
    """Distinct paths an issue names through `file` and `files`, in order."""
    names = [issue.get("file"), *(issue.get("files") or [])]
    seen: List[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(str(name))
    return seen


def needs_chain(issue_id: str, issue: Optional[Mapping[str, Any]]) -> bool:
    """True for a critical id or an issue that names more than one code file."""
    return issue_id.startswith("C") or (issue is not None and len(issue_files(issue)) > 1)


def flagged_ids(doc: Mapping[str, Any], ids: Sequence[str]) -> List[str]:
    """The ids, in order, whose entries must carry a Chain and a flow block."""
    return [i for i in ids if needs_chain(i, find_issue(doc, i))]


def reviewer_model(flagged: Sequence[str]) -> str:
    """Model for the memo reviewer: opus when any entry is flagged, else sonnet."""
    return "opus" if flagged else "sonnet"


def decided_ids(doc: Mapping[str, Any]) -> List[str]:
    """Ids whose latest post-review resolution closes them."""
    # Integration switches this to review_bubbles.closed_ids.
    latest: Dict[str, str] = {}
    for entry in doc.get("post_review_resolutions") or []:
        latest[str(entry.get("id"))] = str(entry.get("status"))
    return [i for i, status in latest.items() if status in CLOSED_STATUSES]


def currently_bubbled(doc: Mapping[str, Any], pending: Sequence[Tuple[str, str, str]]) -> List[Bubbled]:
    """`bubbles` in order, then pending fixer bubbles not already listed.

    Class and reason come from `bubble_up`, else from the pending triple, else the class reads `unclassified`.
    """
    listed = {str(e.get("id")): e for e in doc.get("bubble_up") or []}
    waiting = {pid: (pcls, preason) for pid, pcls, preason in reversed(list(pending))}
    ids: List[str] = []
    for bubble_id in [*(doc.get("bubbles") or []), *(p[0] for p in pending)]:
        if bubble_id not in ids:
            ids.append(bubble_id)
    out = []
    for bubble_id in ids:
        known = listed.get(bubble_id, {})
        pcls, preason = waiting.get(bubble_id, ("", ""))
        out.append(Bubbled(bubble_id, known.get("classification") or pcls or UNCLASSIFIED,
                           known.get("reason") or preason or ""))
    return out


# ---------------------------------------------------------------- scaffold

def _row(bubbled: Bubbled) -> str:
    return f"| {bubbled.id} | {bubbled.cls} | {STATUS_OPEN} | - | - |"


def _reference_line(issue: Optional[Mapping[str, Any]]) -> str:
    files = issue_files(issue) if issue else []
    if not files:
        return STUB
    lines = issue.get("lines") if issue else None
    usable = len(files) == 1 and lines is not None and _LINES_RE.fullmatch(str(lines).strip())
    line = str(lines).strip() if usable else STUB
    return ", ".join(f"`{name}:{line}`" for name in files)


def _chain_stub_lines() -> List[str]:
    return [f"{_FIELD_PREFIX}{_CHAIN}:** {STUB}", _FENCE, f"  {STUB}", _FENCE]


def _expected_stub_lines(issue: Optional[Mapping[str, Any]]) -> List[str]:
    fixes = (issue or {}).get("fix") or []
    return [f"    - ({_label(i)}) {_one_line(fix)} -> {STUB}" for i, fix in enumerate(fixes)]


def render_entry(doc: Mapping[str, Any], bubbled: Bubbled) -> str:
    """One memo entry with the sources' facts filled in and the rest stubbed."""
    issue = find_issue(doc, bubbled.id)
    name = _one_line((issue or {}).get("name") or STUB)
    lines = [f"{ENTRY_PREFIX}{bubbled.id}. {name}", "",
             f"{_FIELD_PREFIX}{_CLASS}:** {bubbled.cls}",
             f"{_FIELD_PREFIX}{_DESCRIPTION}:** {STUB}",
             f"{_FIELD_PREFIX}{_REFERENCES}:** {_reference_line(issue)}",
             f"{_FIELD_PREFIX}{_CURRENT}:** {STUB}",
             f"{_FIELD_PREFIX}{_WHEN}:** {STUB}"]
    if needs_chain(bubbled.id, issue):
        lines += _chain_stub_lines()
    lines += [f"{_FIELD_PREFIX}{_EXPECTED}:**", *_expected_stub_lines(issue),
              f"{_FIELD_PREFIX}{_RECOMMENDATION}:** {STUB}", DECISION_OPEN]
    return "\n".join(lines)


def scaffold_memo(doc: Mapping[str, Any], bubbled: Sequence[Bubbled], *,
                  review_file: Optional[str] = None) -> str:
    """A new memo: header stubs, the index and one entry per bubbled issue.

    The Scope line names the PR, the review JSON file when given, and the head SHA.
    """
    sha = str(doc.get("head_sha") or "")[:7]
    scope = f"Issues bubbled for decision in the review of PR #{doc.get('pr')}"
    scope += f", review file {review_file}" if review_file else ""
    scope += (f", head {sha}" if sha else "") + "."
    lines = [f"# PR #{doc.get('pr')} Bubbles: {_one_line(doc.get('pr_title') or '')}", "",
             f"- **Scope:** {scope}", f"- **Verified against:** {STUB}",
             f"- **Sources:** {STUB}", f"- **Not bubbled:** {STUB}", "",
             "## Index", "", INDEX_HEADER, INDEX_RULE, *(_row(b) for b in bubbled), "",
             "## Entries", ""]
    for item in bubbled:
        lines += [render_entry(doc, item), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- parsing

def _split_row(line: str) -> List[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def _table_span(lines: Sequence[str]) -> Optional[Tuple[int, int]]:
    """Line range of the index data rows (after the rule row), or None without the header."""
    for i, line in enumerate(lines):
        if line.strip() == INDEX_HEADER:
            end = i + 1
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            return i + 1, end
    return None


def _data_rows(lines: Sequence[str]) -> List[List[str]]:
    """Cells of every index data row (the rule row skipped), whatever the cell count."""
    span = _table_span(lines)
    rows = [_split_row(line) for line in lines[span[0]:span[1]]] if span else []
    return [cells for cells in rows if not set("".join(cells)) <= set("-: ")]


def parse_index(text: str) -> List[IndexRow]:
    """Rows of the index table, in order; the rule row and malformed rows are skipped."""
    return [IndexRow(*cells) for cells in _data_rows(_lf(text).split("\n")) if len(cells) == 5]


def _malformed_ids(lines: Sequence[str]) -> List[str]:
    """First cell (or `?`) of each index row that lacks exactly five cells."""
    return [(cells[0] if cells and cells[0] else "?") for cells in _data_rows(lines) if len(cells) != 5]


def _is_boundary(line: str) -> bool:
    return line.startswith(ENTRY_PREFIX) or line.startswith("## ") or line.rstrip() == "---"


def entry_spans(lines: Sequence[str]) -> Dict[str, Tuple[int, int]]:
    """Line range of each entry: its heading up to the next `### `, `## ` or unindented `---` line."""
    spans: Dict[str, Tuple[int, int]] = {}
    current: Optional[Tuple[str, int]] = None
    for i, line in enumerate(list(lines) + ["---"]):
        if current is not None and _is_boundary(line):
            end = i
            while end > current[1] + 1 and not lines[end - 1].strip():
                end -= 1
            spans.setdefault(current[0], (current[1], end))
            current = None
        match = _HEADING_RE.match(line)
        if match:
            current = (match.group(1), i)
    return spans


def entry_blocks(text: str) -> Dict[str, str]:
    """Entry id -> entry text, trailing blank lines removed."""
    lines = _lf(text).split("\n")
    return {i: "\n".join(lines[s:e]) for i, (s, e) in entry_spans(lines).items()}


def _field_range(block: Sequence[str], name: str) -> Optional[Tuple[int, int]]:
    """Line range of a top-level field: its line plus indented continuation lines."""
    prefix = f"{_FIELD_PREFIX}{name}:**"
    for i, line in enumerate(block):
        if line.startswith(prefix):
            end = i + 1
            while end < len(block) and not block[end].startswith(_FIELD_PREFIX):
                end += 1
            while end > i + 1 and not block[end - 1].strip():
                end -= 1
            return i, end
    return None


def _field_text(block: Sequence[str], name: str) -> Optional[str]:
    span = _field_range(block, name)
    return None if span is None else "\n".join(block[span[0]:span[1]])


# ---------------------------------------------------------------- add_missing

def add_missing(text: str, doc: Mapping[str, Any], bubbled: Sequence[Bubbled]) -> Tuple[str, List[str]]:
    """Append the entries and index rows the memo lacks; existing text is never edited.

    An id whose index row is malformed counts as having a row. ValueError when a row is needed and the memo
    has no index table. Text that changes comes back with `\\n` line endings.
    """
    source = _lf(text)
    all_lines = source.split("\n")
    have_rows = {r.id for r in parse_index(source)} | set(_malformed_ids(all_lines))
    have_entries = set(entry_blocks(source))
    added: List[str] = []
    rows: List[str] = []
    entries: List[str] = []
    for item in bubbled:
        if item.id in have_rows and item.id in have_entries:
            continue
        added.append(item.id)
        rows += [] if item.id in have_rows else [_row(item)]
        entries += [] if item.id in have_entries else [render_entry(doc, item)]
    if not added:
        return text, []
    span = _table_span(all_lines)
    if rows and span is None:
        raise ValueError(f"the memo has no index table ({INDEX_HEADER}); "
                         f"cannot add rows for {', '.join(added)}")
    if rows and span:
        all_lines[span[1]:span[1]] = rows
    out = "\n".join(all_lines)
    out = out if out.endswith("\n") else out + "\n"
    return out + "".join(f"\n{entry}\n" for entry in entries), added


# ---------------------------------------------------------------- references

def reference_problem(at: str, root: Path) -> Optional[str]:
    """Why a `path:line` or `path:start-end` reference is wrong, or None when it checks out."""
    match = _REF_RE.fullmatch(at.strip())
    if match is None:
        return f"reference `{at}` is not path:line or path:start-end"
    path, first = match.group(1), int(match.group(2))
    last = int(match.group(3) or first)
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).anchor:
        return f"reference file {path} is an absolute path; use a path relative to the project"
    try:
        return _file_reference_problem(at, path, first, last, root)
    except (OSError, ValueError) as exc:
        return f"reference file {path} cannot be read ({exc.__class__.__name__})"


def _file_reference_problem(at: str, path: str, first: int, last: int, root: Path) -> Optional[str]:
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        return f"reference file {path} lies outside the project"
    if not target.is_file():
        return f"reference file {path} does not exist"
    if first < 1 or last < first:
        return f"reference {at} is not a valid line range"
    parts = target.read_text(encoding="utf-8", errors="replace").split("\n")
    count = len(parts) - 1 if parts and parts[-1] == "" else len(parts)
    if last > count:
        return f"reference {at} runs past the end of {path} ({count} lines)"
    return None


def _reference_tokens(field: str) -> List[str]:
    """Backticked `path:line` or `path:start-end` spans; other code spans are prose."""
    return [t.strip() for t in _TOKEN_RE.findall(field) if _REF_RE.fullmatch(t.strip())]


def _reference_files(tokens: Sequence[str]) -> List[str]:
    """Distinct normalised paths of the reference tokens, in order."""
    files: List[str] = []
    for token in tokens:
        match = _REF_RE.fullmatch(token)
        path = str(PurePosixPath(match.group(1).replace("\\", "/"))) if match else token
        if path not in files:
            files.append(path)
    return files


# ---------------------------------------------------------------- check

def _stub_problems(item_id: str, block: str) -> List[str]:
    count = block.count(STUB)
    return [f"{item_id}: {count} unfilled {STUB} stub(s)"] if count else []


def _reference_problems(item_id: str, tokens: Sequence[str], root: Path) -> List[str]:
    return [f"{item_id}: {p}" for p in (reference_problem(t, root) for t in tokens) if p]


def _chain_problems(item_id: str, lines: Sequence[str], why: str) -> List[str]:
    field = _field_text(lines, _CHAIN)
    if field is None:
        return [f"{item_id}: Chain and flow block are required ({why})"]
    body = field.split("\n")
    fences = [i for i, line in enumerate(body) if line.strip().startswith("```")]
    steps = [body[0].split(":**", 1)[1].strip(), *(ln.strip() for i, ln in enumerate(body[1:], 1)
                                                   if not (fences and fences[0] <= i <= fences[-1]))]
    problems = [] if any(steps) else [f"{item_id}: Chain has no steps"]
    if len(fences) < 2:
        return problems + [f"{item_id}: Chain has no flow block"]
    flow = body[fences[0] + 1:fences[1]]
    return problems + ([] if any(ln.strip() for ln in flow) else [f"{item_id}: Chain flow block is empty"])


def _expected_problems(item_id: str, lines: Sequence[str], issue: Optional[Mapping[str, Any]]) -> List[str]:
    fixes = (issue or {}).get("fix") or []
    if not fixes:
        return []
    field = _field_text(lines, _EXPECTED) or ""
    found = sum(1 for ln in field.split("\n")[1:] if _OPTION_RE.match(ln))
    if found == len(fixes):
        return []
    return [f"{item_id}: expected {len(fixes)} expected-behavior lines (one per fix option), found {found}"]


def _entry_problems(item_id: str, block: Optional[str], has_row: bool,
                    doc: Mapping[str, Any], root: Path) -> List[str]:
    """Problems of one currently bubbled id: missing entry or row, stubs, references, chain, fix count."""
    problems = [] if block is not None else [f"{item_id}: no entry in the memo"]
    problems += [] if has_row else [f"{item_id}: no index row"]
    if block is None:
        return problems
    lines = block.split("\n")
    issue = find_issue(doc, item_id)
    tokens = _reference_tokens(_field_text(lines, _REFERENCES) or "")
    files = _reference_files(tokens)
    problems += _stub_problems(item_id, block) + _reference_problems(item_id, tokens, root)
    if not any(ln.startswith(DECISION_PREFIX) for ln in lines):
        problems.append(f"{item_id}: no Decision line")
    if needs_chain(item_id, issue) or len(files) > 1:
        why = "critical id" if item_id.startswith("C") else "several code files"
        problems += [] if tokens else [f"{item_id}: a flagged entry needs at least one `path:line` reference"]
        problems += _chain_problems(item_id, lines, why)
    return problems + _expected_problems(item_id, lines, issue)


def _anchor_problems(text: str, rows: Sequence[IndexRow]) -> List[str]:
    problems = [] if INDEX_HEADER in text else [f"memo: index header is missing ({INDEX_HEADER})"]
    problems += [f"{i}: malformed index row" for i in _malformed_ids(text.split("\n"))]
    for row in rows:
        if row.status not in (STATUS_OPEN, STATUS_DECIDED):
            problems.append(f"{row.id}: index Status `{row.status}` is not {STATUS_OPEN} or {STATUS_DECIDED}")
    lines = text.split("\n")
    inside = {i for s, e in entry_spans(lines).values() for i in range(s, e)}
    outside = sum(ln.count(STUB) for i, ln in enumerate(lines) if i not in inside)
    return problems + ([f"memo: {outside} unfilled {STUB} stub(s) outside the entries"] if outside else [])


def _stale_notes(text: str, rows: Sequence[IndexRow], current: Sequence[str],
                 decided: Sequence[str]) -> List[str]:
    ids = [r.id for r in rows] + list(entry_blocks(text))
    stale: List[str] = []
    for item_id in ids:
        if item_id not in current and item_id not in decided and item_id not in stale:
            stale.append(item_id)
    return [f"{i}: neither currently bubbled nor decided in the review JSON (renamed or merged id; "
            "settle by hand)" for i in stale]


def check_memo(text: str, bubbled: Sequence[Bubbled], doc: Mapping[str, Any],
               root: Path) -> Tuple[List[str], List[str]]:
    """Problems (each `<ID>: <what>`) that fail the memo, and notes that do not.

    A bubbled id whose index row is malformed gets the malformed-row problem, not a missing-row one.
    """
    text = _lf(text)
    blocks = entry_blocks(text)
    rows = parse_index(text)
    row_ids = {r.id for r in rows} | set(_malformed_ids(text.split("\n")))
    problems = _anchor_problems(text, rows)
    for item in bubbled:
        problems += _entry_problems(item.id, blocks.get(item.id), item.id in row_ids, doc, root)
    notes = _stale_notes(text, rows, [b.id for b in bubbled], decided_ids(doc))
    return problems, notes


# ---------------------------------------------------------------- facts

class FactRef(BaseModel):
    """One verified code reference: `at` is path:line or path:start-end."""

    model_config = ConfigDict(extra="forbid")

    at: str
    note: str


class FixEffect(BaseModel):
    """What the code does after one fix option."""

    model_config = ConfigDict(extra="forbid")

    option: str
    effect: str


class Facts(BaseModel):
    """The investigator's report for one flagged issue."""

    model_config = ConfigDict(extra="forbid")

    id: str
    current_behavior: str
    when: str
    chain: List[str]
    flow: str
    references: List[FactRef]
    fix_effects: List[FixEffect]
    confidence: str

    @model_validator(mode="after")
    def _no_empty_field(self) -> "Facts":
        names = ("id", "current_behavior", "when", "flow", "confidence")
        empty = [n for n in names if not getattr(self, n).strip()]
        empty += ["chain"] if not self.chain or not all(s.strip() for s in self.chain) else []
        empty += ["references"] if not self.references or not all(
            r.at.strip() and r.note.strip() for r in self.references) else []
        empty += ["fix_effects"] if not all(
            f.option.strip() and f.effect.strip() for f in self.fix_effects) else []
        if empty:
            raise ValueError("empty field: " + ", ".join(empty))
        return self


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"])
        parts.append(f"{where + ': ' if where else ''}{err['msg'].removeprefix('Value error, ')}")
    return "; ".join(parts)


def _facts_problems(facts: Facts, issue: Mapping[str, Any], root: Path) -> List[str]:
    problems = []
    if issue.get("id") and facts.id != issue["id"]:
        problems.append(f"id {facts.id} does not match the issue {issue['id']}")
    fixes = issue.get("fix") or []
    if len(facts.fix_effects) != len(fixes):
        problems.append(f"fix_effects has {len(facts.fix_effects)} items, "
                        f"the issue has {len(fixes)} fix options")
    else:
        problems += [f"fix_effects[{i}].option does not match fix option {i + 1} of the issue"
                     for i, (eff, fix) in enumerate(zip(facts.fix_effects, fixes))
                     if _one_line(eff.option) != _one_line(fix)]
    for ref in facts.references:
        why = reference_problem(ref.at, root)
        problems += [why] if why else []
    return problems


def validate_facts(raw: Any, issue: Mapping[str, Any], root: Path) -> Facts:
    """Parse a facts report; ValueError for an empty field, a wrong fix count or a reference off disk."""
    try:
        facts = Facts.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(_format_errors(exc)) from exc
    problems = _facts_problems(facts, issue, root)
    if problems:
        raise ValueError("; ".join(problems))
    return facts


# ---------------------------------------------------------------- apply_facts

def _replace_stubbed(block: List[str], name: str, new_lines: Sequence[str]) -> None:
    span = _field_range(block, name)
    if span and STUB in "\n".join(block[span[0]:span[1]]):
        block[span[0]:span[1]] = list(new_lines)


def _chain_lines(facts: Facts) -> List[str]:
    steps = [f"  {n}. {_STEP_NUMBER_RE.sub('', _one_line(s))}" for n, s in enumerate(facts.chain, 1)]
    raw_flow = facts.flow.replace("```", "'''").strip("\n").split("\n")
    flow = [f"  {ln}" if ln.strip() else "" for ln in raw_flow]
    return [f"{_FIELD_PREFIX}{_CHAIN}:**", *steps, _FENCE, *flow, _FENCE]


def _fill_effects(block: List[str], facts: Facts) -> None:
    span = _field_range(block, _EXPECTED)
    if span is None:
        return
    seen = 0
    for i in range(span[0] + 1, span[1]):
        if not _OPTION_RE.match(block[i]):
            continue
        if block[i].endswith(f"-> {STUB}") and seen < len(facts.fix_effects):
            block[i] = block[i][:-len(STUB)] + _one_line(facts.fix_effects[seen].effect)
        seen += 1


def _reference_text(facts: Facts) -> str:
    notes = [_one_line(r.note).replace("`", "'") for r in facts.references]
    return ", ".join(f"`{r.at.strip()}` ({n})" for r, n in zip(facts.references, notes))


def apply_facts(text: str, facts: Facts) -> str:
    """Fill the stubs of the facts' entry: References, Current behavior, When, Chain, flow, Expected behavior.

    Description, Recommendation and every other entry stay as they are.
    """
    lines = _lf(text).split("\n")
    span = entry_spans(lines).get(facts.id)
    if span is None:
        return text
    block = lines[span[0]:span[1]]
    _replace_stubbed(block, _REFERENCES, [f"{_FIELD_PREFIX}{_REFERENCES}:** {_reference_text(facts)}"])
    _replace_stubbed(block, _CURRENT, [f"{_FIELD_PREFIX}{_CURRENT}:** {_one_line(facts.current_behavior)}"])
    _replace_stubbed(block, _WHEN, [f"{_FIELD_PREFIX}{_WHEN}:** {_one_line(facts.when)}"])
    _replace_stubbed(block, _CHAIN, _chain_lines(facts))
    _fill_effects(block, facts)
    lines[span[0]:span[1]] = block
    return "\n".join(lines)
