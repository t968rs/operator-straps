"""pr-review findings and fix reports: pydantic models, the run directory and the one-call recording API.

Reviewers call ``record`` and fixers call ``record_fixes`` exactly once, from the heredoc their brief carries.
Each call validates every item before writing anything, replaces the agent's report under the run directory
(``<project>/<artifacts.scratch>/<NNNN>/<RUN_ID>/``, named by the ``run_id`` argument, else by ``current``),
and prints the agent's return-contract block (the pr-team skill's ``return_contract.md``), UTF-8 safe on any
console encoding. Agents never choose issue ids; ids are assigned when ``harness_lib.review_merge`` merges
the reports. An explicit ``repo`` names the project (its own ``.claude/harness.json`` governs the scratch
path); without one, the project is ``harness_lib.config.active()``'s root.
"""
from __future__ import annotations

import functools
import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple, Type, TypeVar, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

AGENT_ID = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
RUN_ID = re.compile(r"^pr\d{1,7}_\d{8}T\d{6}Z$")
ISSUE_ID = r"^[CIM]\d+$"
LINES = r"^\d+(-\d+)?(,\s*\d+(-\d+)?)*$"
_DRIVE = re.compile(r"^[A-Za-z]:")
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
_M = TypeVar("_M", bound=BaseModel)


class Severity(str, Enum):
    """Issue severity tier; coerced from ``C`` / ``I`` / ``M`` or the full name, any case."""

    critical = "critical"
    important = "important"
    minor = "minor"


class FixKind(str, Enum):
    """Whether a fix is mechanical (haiku-sized) or needs design judgment."""

    mechanical = "mechanical"
    judgment = "judgment"


class BubbleClass(str, Enum):
    """``bubble_up`` classification values of ``PR_REVIEW.schema.json``."""

    architectural_ambiguity = "architectural_ambiguity"
    out_of_scope = "out_of_scope"
    needs_follow_up = "needs_follow_up"
    fixer_failed = "fixer_failed"


_SEVERITY_LETTERS = {"c": Severity.critical, "i": Severity.important, "m": Severity.minor}


@functools.lru_cache(maxsize=8)
def _loaded(root: str, _stamp: int) -> HarnessConfig:
    """``load_config(root)``; ``_stamp`` (the config file's mtime) only keys the cache."""
    from harness_lib.config import load_config
    return load_config(Path(root))


def config_for(repo: Optional[Union[str, Path]] = None) -> HarnessConfig:
    """The configuration of project ``repo``, else the active one.

    An explicit ``repo`` governs even when the process activated another project: a brief's ``record``
    heredoc runs from any working directory and names its project through ``repo``.
    """
    if repo is None:
        from harness_lib.config import active
        return active()
    from harness_lib.config import CONFIG_REL
    root = Path(repo).resolve()
    source = root / CONFIG_REL
    return _loaded(str(root), source.stat().st_mtime_ns if source.is_file() else 0)


def run_root(repo: Optional[Union[str, Path]] = None) -> Path:
    """Project-relative directory holding every PR's review runs (``artifacts.scratch`` of ``repo``, else
    of the active project)."""
    return Path(config_for(repo).artifacts.scratch)


def _project_root() -> Path:
    """Root of the active project."""
    from harness_lib.config import active
    return active().project_root


def _root_prefix_matches(text: str, prefix: str) -> bool:
    """True when ``text`` starts with ``prefix``; drive-rooted prefixes ignore case, POSIX prefixes do not."""
    if _DRIVE.match(prefix):
        return text.lower().startswith(prefix.lower())
    return text.startswith(prefix)


def repo_path(value: str, root: Optional[Union[str, Path]] = None) -> str:
    """Repo-relative posix form of ``value``; a leading ``root`` is stripped; ``..``, drives, empty raise."""
    text = str(value).strip().replace("\\", "/")
    prefix = Path(root if root is not None else _project_root()).as_posix().rstrip("/") + "/"
    if _root_prefix_matches(text, prefix):
        text = text[len(prefix):]
    while text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or _DRIVE.match(text):
        raise ValueError(f"path {value!r} is not a repo-relative path")
    if ".." in text.split("/"):
        raise ValueError(f"path {value!r} leaves the repo ('..')")
    return text


def _one_line(value: object) -> object:
    """Whitespace runs collapsed to single spaces for string input; other input unchanged."""
    return " ".join(value.split()) if isinstance(value, str) else value


def _context_root(info: ValidationInfo) -> Optional[str]:
    """Repo root passed as validation context (``{"root": ...}``), else None."""
    return (info.context or {}).get("root") if isinstance(info.context, dict) else None


def _non_empty(values: Tuple[str, ...], label: str) -> Tuple[str, ...]:
    """``values`` stripped; raise when any is empty."""
    stripped = tuple(v.strip() for v in values)
    if any(not v for v in stripped):
        raise ValueError(f"every {label} entry must be non-empty")
    return stripped


def _agent_id(value: str) -> str:
    """``value`` when it is a snake_case agent id; raise otherwise."""
    if not AGENT_ID.match(value):
        raise ValueError(f"agent id {value!r} must be snake_case ([a-z0-9]+ joined by '_')")
    return value


class Finding(BaseModel):
    """One reviewer finding: a primary ``file`` with optional ``lines``, plus optional ``also`` files."""

    model_config = _MODEL_CONFIG

    severity: Severity
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    fix: Tuple[str, ...] = Field(min_length=1)
    file: str
    lines: Optional[str] = Field(default=None, pattern=LINES)
    also: Tuple[str, ...] = ()
    fix_kind: FixKind

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: object) -> object:
        """``C`` / ``I`` / ``M`` and any-case names coerced to ``Severity`` values."""
        if not isinstance(value, str):
            return value
        text = value.strip().lower()
        return _SEVERITY_LETTERS.get(text, text)

    @field_validator("fix_kind", mode="before")
    @classmethod
    def _fix_kind(cls, value: object) -> object:
        """Any-case fix kind names lowered."""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> object:
        """Name collapsed to one line."""
        return _one_line(value)

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        """Summary stripped; blank rejected."""
        return _non_empty((value,), "summary")[0]

    @field_validator("fix")
    @classmethod
    def _fix(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Fix options stripped; a blank option rejected."""
        return _non_empty(value, "fix")

    @field_validator("file")
    @classmethod
    def _file(cls, value: str, info: ValidationInfo) -> str:
        """Primary file normalized by ``repo_path``."""
        return repo_path(value, _context_root(info))

    @field_validator("lines")
    @classmethod
    def _lines_ordered(cls, value: Optional[str]) -> Optional[str]:
        """Each ``start-end`` range has ``end`` at or after ``start``."""
        for start, end in re.findall(r"(\d+)-(\d+)", value or ""):
            if int(end) < int(start):
                raise ValueError(f"lines range {start}-{end} ends before it starts")
        return value

    @field_validator("also")
    @classmethod
    def _also(cls, value: Tuple[str, ...], info: ValidationInfo) -> Tuple[str, ...]:
        """Other files normalized by ``repo_path`` and de-duplicated in order."""
        paths = [repo_path(v, _context_root(info)) for v in value]
        return tuple(dict.fromkeys(paths))

    @model_validator(mode="after")
    def _also_not_primary(self) -> Finding:
        """``also`` never repeats the primary file."""
        if self.file in self.also:
            raise ValueError(f"also repeats the primary file {self.file!r}")
        return self


class ReviewerReport(BaseModel):
    """Everything one reviewer recorded: its findings and strengths."""

    model_config = _MODEL_CONFIG

    reviewer: str
    findings: Tuple[Finding, ...] = ()
    strengths: Tuple[str, ...] = ()

    @field_validator("reviewer")
    @classmethod
    def _reviewer(cls, value: str) -> str:
        """Reviewer id is a snake_case agent id."""
        return _agent_id(value)

    @field_validator("strengths")
    @classmethod
    def _strengths(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Strengths stripped; blank rejected."""
        return _non_empty(value, "strengths")

    def counts(self) -> Dict[Severity, int]:
        """Findings per severity, every tier present."""
        return {s: sum(1 for f in self.findings if f.severity is s) for s in Severity}


class FixEntry(BaseModel):
    """One issue a fixer claims fixed, with the files it edited.

    ``no_change`` names files of the fixer's part that the fix needed no edit in (a split issue citing a
    file only as context); ``what`` then also carries why. At least one of ``files`` / ``no_change`` is
    non-empty, and no file is in both.
    """

    model_config = _MODEL_CONFIG

    id: str = Field(pattern=ISSUE_ID)
    what: str = Field(min_length=1)
    files: Tuple[str, ...] = ()
    no_change: Tuple[str, ...] = ()

    @field_validator("what", mode="before")
    @classmethod
    def _what(cls, value: object) -> object:
        """Evidence text collapsed to one line."""
        return _one_line(value)

    @field_validator("files", "no_change")
    @classmethod
    def _files(cls, value: Tuple[str, ...], info: ValidationInfo) -> Tuple[str, ...]:
        """Files normalized by ``repo_path`` and de-duplicated in order."""
        return tuple(dict.fromkeys(repo_path(v, _context_root(info)) for v in value))

    @model_validator(mode="after")
    def _some_file(self) -> FixEntry:
        """At least one file named; no file both edited and marked no-change."""
        if not self.files and not self.no_change:
            raise ValueError("files or no_change must name at least one file")
        both = [f for f in self.files if f in self.no_change]
        if both:
            raise ValueError(f"files both edited and marked no_change: {', '.join(both)}")
        return self


class FixBubble(BaseModel):
    """One issue a fixer hands back to the developer instead of fixing."""

    model_config = _MODEL_CONFIG

    id: str = Field(pattern=ISSUE_ID)
    classification: BubbleClass
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, value: object) -> object:
        """Reason collapsed to one line."""
        return _one_line(value)


class FixReport(BaseModel):
    """Everything one fixer recorded: fixed and bubbled issues, each id at most once."""

    model_config = _MODEL_CONFIG

    fixer: str
    fixed: Tuple[FixEntry, ...] = ()
    bubbled: Tuple[FixBubble, ...] = ()

    @field_validator("fixer")
    @classmethod
    def _fixer(cls, value: str) -> str:
        """Fixer id is a snake_case agent id."""
        return _agent_id(value)

    @model_validator(mode="after")
    def _unique_ids(self) -> FixReport:
        """An issue id appears once across ``fixed`` and ``bubbled``."""
        ids = [e.id for e in self.fixed] + [b.id for b in self.bubbled]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"issue ids recorded more than once: {', '.join(repeated)}")
        return self

    def edited(self) -> Tuple[str, ...]:
        """Distinct files across the fixed entries, in first-seen order."""
        return tuple(dict.fromkeys(f for e in self.fixed for f in e.files))


def _repo(repo: Optional[Path]) -> Path:
    """Resolved project root: ``repo`` when given, else the active project's root."""
    return Path(repo or _project_root()).resolve()


def _pr_dir(pr: int, repo: Optional[Path]) -> Path:
    """``<repo>/<artifacts.scratch>/<NNNN>``."""
    return _repo(repo) / run_root(repo) / f"{int(pr):04d}"


def run_dir(pr: int, repo: Optional[Path] = None, run_id: Optional[str] = None) -> Path:
    """Run directory for ``run_id``, else the one ``current`` names; ``FileNotFoundError`` without one."""
    if run_id is None:
        current = _pr_dir(pr, repo) / "current"
        if not current.is_file():
            raise FileNotFoundError(f"no current pr-review run for PR {pr} ({current}); run capture first")
        run_id = current.read_text(encoding="utf-8").strip()
    if not RUN_ID.match(run_id):
        raise ValueError(f"run id {run_id!r} must look like pr<N>_<yyyymmddTHHMMSSZ>")
    return _pr_dir(pr, repo) / run_id


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a sibling temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def start_run(pr: int, run_id: str, repo: Optional[Path] = None) -> Path:
    """Create the run directory for ``run_id`` and point ``current`` at it; return the directory.

    An existing run directory raises ``ValueError`` (``current`` untouched): two captures within one second
    share a run id, and reusing the directory would mix the earlier run's findings and drafts into the new
    one.
    """
    if not RUN_ID.match(run_id):
        raise ValueError(f"run id {run_id!r} must look like pr<N>_<yyyymmddTHHMMSSZ>")
    path = run_dir(pr, repo, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError as exc:
        raise ValueError(f"run directory {path} already exists; rerun capture for a fresh run id") from exc
    _atomic_write(_pr_dir(pr, repo) / "current", run_id + "\n")
    return path


def reviewer_block(report: ReviewerReport, output: str) -> str:
    """Reviewer-style DONE block with the strict ``COUNTS`` form."""
    counts = report.counts()
    return "\n".join([
        "---", "SIGNAL: DONE", "AGENT_ROLE: reviewer",
        f"COUNTS: findings={len(report.findings)} critical={counts[Severity.critical]} "
        f"important={counts[Severity.important]} minor={counts[Severity.minor]}",
        f"OUTPUT: {output}", "---",
    ])


def _fail_reason(report: FixReport) -> str:
    """One-line FAIL reason (at most 200 characters) naming any bubbled ids."""
    bubbled = ",".join(b.id for b in report.bubbled)
    reason = f"no issues fixed; bubbled: {bubbled}" if bubbled else "no issues fixed and none bubbled"
    return reason[:200]


def fixer_block(report: FixReport, output: str) -> str:
    """Fixer DONE block when anything was fixed, else a FAIL block with a ``REASON``."""
    if not report.fixed:
        return "\n".join(["---", "SIGNAL: FAIL", "AGENT_ROLE: fixer", f"REASON: {_fail_reason(report)}",
                          f"PARTIAL_OUTPUT: {output}", "---"])
    return "\n".join([
        "---", "SIGNAL: DONE", "AGENT_ROLE: fixer",
        f"FIXED: {','.join(e.id for e in report.fixed)}",
        f"BUBBLED: {','.join(b.id for b in report.bubbled)}",
        f"EDITED: {len(report.edited())}", f"OUTPUT: {output}", "EVIDENCE:",
        *(f"  {e.id}: {e.what}" for e in report.fixed), "---",
    ])


def _error_text(exc: ValidationError) -> str:
    """Pydantic errors as ``loc: message`` pairs joined by ``; ``."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '<item>'}: {e['msg']}" for e in exc.errors())


def _validate_items(
        model: Type[_M], items: Sequence[Mapping[str, object]], label: str, root: Path,
) -> Tuple[_M, ...]:
    """Every item validated as ``model``; one ``ValueError`` names each failing ``label[index]``."""
    built: List[_M] = []
    errors: List[str] = []
    for index, item in enumerate(items):
        try:
            built.append(model.model_validate(dict(item), context={"root": root.as_posix()}))
        except (ValidationError, TypeError, ValueError) as exc:
            detail = _error_text(exc) if isinstance(exc, ValidationError) else str(exc)
            errors.append(f"{label}[{index}]: {detail}")
    if errors:
        raise ValueError("; ".join(errors))
    return tuple(built)


def _report_path(pr: int, folder: str, agent: str, repo: Optional[Path],
                 run_id: Optional[str] = None) -> Tuple[Path, str]:
    """Absolute report path under ``run_id`` (else the current run) and its repo-relative posix form."""
    path = run_dir(pr, repo, run_id) / folder / f"{agent}.json"
    return path, path.relative_to(_repo(repo)).as_posix()


def _emit(text: str) -> None:
    """Print ``text`` to stdout; a stream that cannot encode it is reconfigured to UTF-8 when it supports
    ``reconfigure``, else ``text`` goes to its ``buffer`` as UTF-8 bytes."""
    stream = sys.stdout
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
            stream.write(text + "\n")
        else:
            stream.buffer.write((text + "\n").encode("utf-8"))
    stream.flush()


def _load(model: Type[_M], path: Path) -> _M:
    """``model`` read from the JSON file at ``path``."""
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def record(pr: int, reviewer: str, findings: Sequence[Mapping[str, object]] = (),
           strengths: Sequence[str] = (), *, repo: Optional[Path] = None,
           run_id: Optional[str] = None) -> str:
    """Validate, write ``findings/<reviewer>.json`` (replacing), re-read it, print and return the block.

    ``run_id`` names the run directory; without it the run ``current`` names receives the report.
    """
    root = _repo(repo)
    built = _validate_items(Finding, findings, "finding", root)
    try:
        report = ReviewerReport(reviewer=reviewer, findings=built, strengths=tuple(strengths))
    except ValidationError as exc:
        raise ValueError(_error_text(exc)) from exc
    path, output = _report_path(pr, "findings", report.reviewer, root, run_id)
    _atomic_write(path, report.model_dump_json(indent=2) + "\n")
    block = reviewer_block(load_report(path), output)
    _emit(block)
    return block


def record_fixes(pr: int, fixer: str, fixed: Sequence[Mapping[str, object]] = (),
                 bubbled: Sequence[Mapping[str, object]] = (), *, repo: Optional[Path] = None,
                 run_id: Optional[str] = None) -> str:
    """Validate, write ``fixes/<fixer>.json`` (replacing), re-read it, print and return the block.

    ``run_id`` names the run directory; without it the run ``current`` names receives the report.
    """
    root = _repo(repo)
    entries = _validate_items(FixEntry, fixed, "fixed", root)
    bubbles = _validate_items(FixBubble, bubbled, "bubbled", root)
    try:
        report = FixReport(fixer=fixer, fixed=entries, bubbled=bubbles)
    except ValidationError as exc:
        raise ValueError(_error_text(exc)) from exc
    path, output = _report_path(pr, "fixes", report.fixer, root, run_id)
    _atomic_write(path, report.model_dump_json(indent=2) + "\n")
    block = fixer_block(_load(FixReport, path), output)
    _emit(block)
    return block


def load_report(path: Path) -> ReviewerReport:
    """The ``ReviewerReport`` stored at ``path``."""
    return _load(ReviewerReport, path)


def load_fix_reports(directory: Path) -> Tuple[FixReport, ...]:
    """Every ``FixReport`` in ``directory`` by file name; empty when the directory is missing."""
    if not directory.is_dir():
        return ()
    return tuple(_load(FixReport, p) for p in sorted(directory.glob("*.json")))
