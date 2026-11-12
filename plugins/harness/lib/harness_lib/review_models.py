"""pr-review findings and fix reports: pydantic models, the run directory and the recording API.

Reviewers record through ``record_draft`` (or ``record``) and fixers through ``record_fixes_draft`` (or
``record_fixes``), normally once, from the heredoc their brief carries. ``record_add`` is the exception: it
appends to a reviewer's report across several calls. Under ``--adversarial``, code refuters (``adv_code*``)
record through ``record_attacks(_draft)`` and findings refuters through ``record_refutations(_draft)``,
which writes ``refutations/<target>.json``; their ``attack`` and ``evidence`` text loses the repo root
prefix (``strip_root``), so a cited ``path:line`` stays repo-relative. Each replacing call validates every
item before writing anything, replaces the agent's report under the run directory
(``<project>/<artifacts.scratch>/<NNNN or local-<label>>/<RUN_ID>/``, named by the ``run_id`` argument,
else by ``current``), and prints the agent's return-contract block (the pr-team skill's
``return_contract.md``), UTF-8 safe on any console encoding. Agents never choose issue ids; ids are assigned when ``harness_lib.review_merge`` merges
the reports. An explicit ``repo`` names the project (its own ``.claude/harness.json`` governs the scratch
path); without one, the project is ``harness_lib.config.active()``'s root.
"""
from __future__ import annotations

import collections
import functools
import hashlib
import json
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

from harness_lib.review_local_models import LABEL_MAX, LABEL_PATTERN, LOCAL_PREFIX, RunKey, parse_key

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

AGENT_ID = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
ADVERSARIAL_WORKFLOW = "workflows/adversarial-review.js"
ADVERSARIAL_AGENT = "harness:adversarial-reviewer"
REFUTER_MODEL = "opus"
CODE_REFUTER_PREFIX = "adv_code"
FINDINGS_REFUTER_PREFIX = "adv_refute_"
_KEY_LENGTH = 12
KEY_PATTERN = rf"^[0-9a-f]{{{_KEY_LENGTH}}}$"
_LOCAL_RUN = (rf"{re.escape(LOCAL_PREFIX)}(?=[^_]{{1,{LABEL_MAX}}}_)"
              rf"{LABEL_PATTERN.strip('^$')}")
RUN_ID = re.compile(rf"^(pr\d{{1,7}}|{_LOCAL_RUN})_\d{{8}}T\d{{6}}Z$")
_RUN_ID_SHAPE = "pr<N>_<yyyymmddTHHMMSSZ> or local-<label>_<yyyymmddTHHMMSSZ>"
ISSUE_ID = r"^[CIM]\d+$"
LINES = r"^\d+(-\d+)?(,\s*\d+(-\d+)?)*$"
_DRIVE = re.compile(r"^[A-Za-z]:")
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
_M = TypeVar("_M", bound=BaseModel)


class Severity(str, Enum):
    """Issue severity tier; coerced from its one-letter tier code or the full name, any case."""

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


def strip_root(text: str, root: Union[str, Path]) -> str:
    """``text`` with every occurrence of the repo ``root`` prefix (``<root>/`` or ``<root>\\``) removed, so
    a cited ``path:line`` reads repo-relative; case-insensitive on Windows or for a drive-rooted root."""
    base = Path(root).as_posix().rstrip("/")
    forms = (base + "/", base.replace("/", "\\") + "\\")
    flags = re.IGNORECASE if os.name == "nt" or _DRIVE.match(base) else 0
    pattern = "|".join(re.escape(form) for form in dict.fromkeys(forms))
    return re.sub(pattern, "", text, flags=flags)


def _relative_text(value: str, info: ValidationInfo) -> str:
    """``value`` with the validation context's repo root stripped (``strip_root``); unchanged without a
    root (a report loaded from disk)."""
    root = _context_root(info)
    return strip_root(value, root) if root else value


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
        """One-letter tier codes and any-case names coerced to ``Severity`` values."""
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


class AttackFinding(Finding):
    """A code refuter's finding: a ``Finding`` plus the ``attack`` that breaks the code (the failing
    input, the broken call path, or the test that would fail)."""

    attack: str = Field(min_length=1)

    @field_validator("attack")
    @classmethod
    def _attack(cls, value: str, info: ValidationInfo) -> str:
        """Attack stripped, the repo root prefix removed (``record_attacks`` passes the root); blank
        rejected."""
        return _non_empty((_relative_text(value, info),), "attack")[0]


class CodeRefuterReport(ReviewerReport):
    """Everything one code refuter (an ``adv_code*`` slot) recorded: attack findings and strengths."""

    findings: Tuple[AttackFinding, ...] = ()


class RefutationVerdict(str, Enum):
    """A findings refuter's verdict on one finding."""

    refuted = "refuted"
    upheld = "upheld"


class Refutation(BaseModel):
    """One findings-refuter verdict on the finding whose ``finding_key`` is ``key``.

    A refuted entry carries ``evidence``: the ``path:line`` opened and what it showed.
    """

    model_config = _MODEL_CONFIG

    key: str = Field(pattern=KEY_PATTERN)
    verdict: RefutationVerdict
    evidence: str = ""

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, value: object) -> object:
        """Key stripped of whitespace and one pair of surrounding square brackets, then lowercased."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return text.lower()

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> object:
        """Evidence collapsed to one line."""
        return _one_line(value)

    @field_validator("evidence")
    @classmethod
    def _evidence_relative(cls, value: str, info: ValidationInfo) -> str:
        """Evidence with the repo root prefix removed (``record_refutations`` passes the root)."""
        return _relative_text(value, info)

    @model_validator(mode="after")
    def _refuted_has_evidence(self) -> Refutation:
        """A refuted verdict needs non-blank evidence."""
        if self.verdict is RefutationVerdict.refuted and not self.evidence:
            raise ValueError(f"refutation {self.key}: a refuted verdict needs evidence")
        return self


def _repeated(keys: Sequence[str]) -> List[str]:
    """Values occurring more than once in ``keys``, sorted."""
    return sorted(k for k, n in collections.Counter(keys).items() if n > 1)


def _check_refuter_pair(refuter: str, target: str) -> None:
    """Raise unless ``refuter`` is ``adv_refute_<target>``."""
    if refuter != f"{FINDINGS_REFUTER_PREFIX}{target}":
        raise ValueError(f"refuter id {refuter!r} does not match target {target!r}: "
                         f"expected {FINDINGS_REFUTER_PREFIX}{target}")


class RefutationReport(BaseModel):
    """A findings refuter's verdicts on each distinct finding key of ``target``, exactly once, keyed to
    the target report's ``report_digest`` at record time; ``refuter`` is ``adv_refute_<target>``."""

    model_config = _MODEL_CONFIG

    refuter: str
    target: str
    report_digest: str = Field(pattern=KEY_PATTERN)
    refutations: Tuple[Refutation, ...] = ()

    @field_validator("refuter", "target")
    @classmethod
    def _ids(cls, value: str) -> str:
        """Refuter and target ids are snake_case agent ids."""
        return _agent_id(value)

    @model_validator(mode="after")
    def _refuter_matches_target(self) -> RefutationReport:
        """The refuter id is ``adv_refute_<target>``."""
        _check_refuter_pair(self.refuter, self.target)
        return self

    @model_validator(mode="after")
    def _unique_keys(self) -> RefutationReport:
        """A finding key appears once across the refutations."""
        repeated = _repeated([r.key for r in self.refutations])
        if repeated:
            raise ValueError(f"finding keys refuted more than once: {', '.join(repeated)}")
        return self

    def counts(self) -> Dict[RefutationVerdict, int]:
        """Refutations per verdict, every verdict present."""
        return {v: sum(1 for r in self.refutations if r.verdict is v) for v in RefutationVerdict}


def is_code_refuter(agent: str) -> bool:
    """True when ``agent`` is the code-refuter id ``adv_code`` or starts with ``adv_code_``."""
    return agent == CODE_REFUTER_PREFIX or agent.startswith(CODE_REFUTER_PREFIX + "_")


def _finding_model(agent: str) -> Type[Finding]:
    """``AttackFinding`` for a code-refuter id, else ``Finding``."""
    return AttackFinding if is_code_refuter(agent) else Finding


def _report_model(agent: str) -> Type[ReviewerReport]:
    """``CodeRefuterReport`` for a code-refuter id, else ``ReviewerReport``."""
    return CodeRefuterReport if is_code_refuter(agent) else ReviewerReport


def _digest(payload: object) -> str:
    """First ``_KEY_LENGTH`` hex characters of sha256 over ``payload`` as sorted-key JSON."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def finding_key(finding: Finding) -> str:
    """Content key of ``finding``: 12 hex characters of sha256 over its canonical JSON.

    The hash covers every dumped field, defaults included, so a new defaulted field on ``Finding``
    changes every key.
    """
    return _digest(finding.model_dump(mode="json"))


def report_digest(report: ReviewerReport) -> str:
    """Content digest of ``report``'s findings list (strengths do not move it).

    The hash covers every dumped field of each finding, defaults included, so a new defaulted field on
    ``Finding`` changes every digest.
    """
    return _digest([f.model_dump(mode="json") for f in report.findings])


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


def _pr_dir(pr: RunKey, repo: Optional[Path]) -> Path:
    """``<repo>/<artifacts.scratch>/<NNNN>`` for a PR number, ``.../<key>`` for a local key."""
    key = parse_key(pr)
    return _repo(repo) / run_root(repo) / (key if isinstance(key, str) else f"{key:04d}")


def run_id_for(pr: RunKey, stamp: str) -> str:
    """``pr<N>_<stamp>`` for a PR number, ``<key>_<stamp>`` for a local key."""
    key = parse_key(pr)
    return f"{key}_{stamp}" if isinstance(key, str) else f"pr{key}_{stamp}"


def run_dir(pr: RunKey, repo: Optional[Path] = None, run_id: Optional[str] = None) -> Path:
    """Run directory for ``run_id``, else the one ``current`` names; ``FileNotFoundError`` without one."""
    if run_id is None:
        current = _pr_dir(pr, repo) / "current"
        if not current.is_file():
            who = f"PR {pr}" if isinstance(parse_key(pr), int) else f"local run {pr}"
            raise FileNotFoundError(f"no current pr-review run for {who} ({current}); run capture first")
        run_id = current.read_text(encoding="utf-8").strip()
    if not RUN_ID.match(run_id):
        raise ValueError(f"run id {run_id!r} must look like {_RUN_ID_SHAPE}")
    return _pr_dir(pr, repo) / run_id


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a sibling temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def start_run(pr: RunKey, run_id: str, repo: Optional[Path] = None) -> Path:
    """Create the run directory for ``run_id`` and point ``current`` at it; return the directory.

    An existing run directory raises ``ValueError`` (``current`` untouched): two captures within one second
    share a run id, and reusing the directory would mix the earlier run's findings and drafts into the new
    one.
    """
    if not RUN_ID.match(run_id):
        raise ValueError(f"run id {run_id!r} must look like {_RUN_ID_SHAPE}")
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


def refutation_block(report: RefutationReport, output: str) -> str:
    """Findings-refuter DONE block in the ``reviewer_block`` shape, counting verdicts."""
    counts = report.counts()
    return "\n".join([
        "---", "SIGNAL: DONE", "AGENT_ROLE: refuter",
        f"COUNTS: refutations={len(report.refutations)} refuted={counts[RefutationVerdict.refuted]} "
        f"upheld={counts[RefutationVerdict.upheld]}",
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


def _report_path(pr: RunKey, folder: str, agent: str, repo: Optional[Path],
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


def _reviewer_id(agent: str) -> str:
    """``agent`` when it is a snake_case id outside ``adv_refute_*``; raise otherwise."""
    _agent_id(agent)
    if agent.startswith(FINDINGS_REFUTER_PREFIX):
        raise ValueError(f"agent id {agent!r} is a findings refuter id; findings refuters record through "
                         f"record_refutations or record_refutations_draft")
    return agent


def record(pr: RunKey, reviewer: str, findings: Sequence[Mapping[str, object]] = (),
           strengths: Sequence[str] = (), *, repo: Optional[Path] = None,
           run_id: Optional[str] = None) -> str:
    """Validate, write ``findings/<reviewer>.json`` (replacing), re-read it, print and return the block.

    ``run_id`` names the run directory; without it the run ``current`` names receives the report. A
    ``reviewer`` id of ``adv_code`` or ``adv_code_*`` is validated as a ``CodeRefuterReport`` (every
    finding needs an ``attack``); an ``adv_refute_*`` id is refused.
    """
    _reviewer_id(reviewer)
    root = _repo(repo)
    built = _validate_items(_finding_model(reviewer), findings, "finding", root)
    try:
        report = _report_model(reviewer)(reviewer=reviewer, findings=built, strengths=tuple(strengths))
    except ValidationError as exc:
        raise ValueError(_error_text(exc)) from exc
    path, output = _report_path(pr, "findings", report.reviewer, root, run_id)
    _atomic_write(path, report.model_dump_json(indent=2) + "\n")
    block = reviewer_block(load_report(path), output)
    _emit(block)
    return block


def record_fixes(pr: RunKey, fixer: str, fixed: Sequence[Mapping[str, object]] = (),
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


def draft_path(pr: RunKey, agent: str, repo: Optional[Path] = None, run_id: Optional[str] = None) -> Path:
    """``drafts/<agent>.json`` in the run directory: the file an agent writes before ``record_draft``."""
    return run_dir(pr, repo, run_id) / "drafts" / f"{agent}.json"


def _read_draft(path: Path, keys: Tuple[str, ...]) -> Dict[str, list]:
    """The draft at ``path`` as ``{key: list}`` for each of ``keys`` (missing keys read as empty lists)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"no draft at {path}: write it first") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"draft {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) - set(keys):
        raise ValueError(f"draft {path} must be one JSON object with only the keys {', '.join(keys)}")
    if any(not isinstance(data.get(k, []), list) for k in keys):
        raise ValueError(f"draft {path}: {' and '.join(keys)} must be lists")
    return {k: list(data.get(k, [])) for k in keys}


def record_draft(pr: RunKey, reviewer: str, *, repo: Optional[Path] = None,
                 run_id: Optional[str] = None) -> str:
    """``record`` with the findings and strengths read from ``draft_path`` (``{findings, strengths}``).

    The payload travels through a file instead of the command line, so its size never reaches the shell.
    """
    _reviewer_id(reviewer)
    draft = _read_draft(draft_path(pr, reviewer, repo, run_id), ("findings", "strengths"))
    return record(pr, reviewer, draft["findings"], draft["strengths"], repo=repo, run_id=run_id)


def record_fixes_draft(pr: RunKey, fixer: str, *, repo: Optional[Path] = None,
                       run_id: Optional[str] = None) -> str:
    """``record_fixes`` with the entries read from ``draft_path`` (a ``{fixed, bubbled}`` object)."""
    draft = _read_draft(draft_path(pr, fixer, repo, run_id), ("fixed", "bubbled"))
    return record_fixes(pr, fixer, draft["fixed"], draft["bubbled"], repo=repo, run_id=run_id)


def record_add(pr: RunKey, reviewer: str, findings: Sequence[Mapping[str, object]] = (),
               strengths: Sequence[str] = (), *, repo: Optional[Path] = None,
               run_id: Optional[str] = None) -> str:
    """Append to ``findings/<reviewer>.json`` (created when absent), print and return the block.

    Builds a report in several small calls; an item identical to one already recorded is skipped, so a
    retried call adds nothing twice. ``record`` and ``record_draft`` still replace the whole report.
    """
    _reviewer_id(reviewer)
    root = _repo(repo)
    added = _validate_items(_finding_model(reviewer), findings, "finding", root)
    path, _ = _report_path(pr, "findings", reviewer, root, run_id)
    old = load_report(path) if path.is_file() else _report_model(reviewer)(reviewer=reviewer)
    merged = list(dict.fromkeys([*old.findings, *added]))
    kept = list(dict.fromkeys([*old.strengths, *(s.strip() if isinstance(s, str) else s for s in strengths)]))
    return record(pr, reviewer, [f.model_dump(mode="json") for f in merged], kept, repo=repo, run_id=run_id)


def _stored_reviewer(text: str) -> str:
    """The ``reviewer`` id in report JSON ``text``; empty when the text does not parse to one."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    reviewer = data.get("reviewer") if isinstance(data, dict) else None
    return reviewer if isinstance(reviewer, str) else ""


def load_report(path: Path) -> ReviewerReport:
    """The report stored at ``path``: a ``CodeRefuterReport`` when its reviewer id starts with
    ``adv_code``, else a ``ReviewerReport``."""
    text = path.read_text(encoding="utf-8")
    return _report_model(_stored_reviewer(text)).model_validate_json(text)


def _code_refuter_id(agent: str) -> str:
    """``agent`` when it starts with ``adv_code``; raise otherwise."""
    if not is_code_refuter(agent):
        raise ValueError(f"agent id {agent!r} is not a code refuter id (must start with "
                         f"{CODE_REFUTER_PREFIX!r}); reviewers record through record or record_draft")
    return agent


def record_attacks(pr: RunKey, refuter: str, findings: Sequence[Mapping[str, object]] = (),
                   strengths: Sequence[str] = (), *, repo: Optional[Path] = None,
                   run_id: Optional[str] = None) -> str:
    """The code refuter's ``record``: refuse an id outside ``adv_code*``, then write
    ``findings/<refuter>.json`` as a ``CodeRefuterReport``, print and return the block."""
    _code_refuter_id(refuter)
    return record(pr, refuter, findings, strengths, repo=repo, run_id=run_id)


def record_attacks_draft(pr: RunKey, refuter: str, *, repo: Optional[Path] = None,
                         run_id: Optional[str] = None) -> str:
    """``record_attacks`` with the findings and strengths read from ``draft_path``."""
    _code_refuter_id(refuter)
    draft = _read_draft(draft_path(pr, refuter, repo, run_id), ("findings", "strengths"))
    return record_attacks(pr, refuter, draft["findings"], draft["strengths"], repo=repo, run_id=run_id)


def _target_report(pr: RunKey, target: str, root: Path, run_id: Optional[str]) -> ReviewerReport:
    """The recorded report of slot ``target``; ``ValueError`` when the slot has not recorded."""
    path, _ = _report_path(pr, "findings", target, root, run_id)
    if not path.is_file():
        raise ValueError(f"reviewer {target} has not recorded")
    return load_report(path)


def _refutation_ids(refuter: str, target: str) -> None:
    """Raise unless both ids are snake_case agent ids and ``refuter`` is ``adv_refute_<target>``."""
    _agent_id(refuter)
    _agent_id(target)
    _check_refuter_pair(refuter, target)


def _coverage_problems(target: ReviewerReport, keys: Sequence[str]) -> List[str]:
    """Missing keys (with finding names), keys not in ``target``, and repeated keys, one text each."""
    names: Dict[str, str] = {}
    for finding in target.findings:
        names.setdefault(finding_key(finding), finding.name)
    missing = [f"{k} ({names[k]})" for k in sorted(set(names) - set(keys))]
    extra = sorted(set(keys) - set(names))
    repeated = _repeated(keys)
    problems = [f"missing: {', '.join(missing)}"] if missing else []
    if extra:
        problems.append(f"not in the target: {', '.join(extra)}")
    if repeated:
        problems.append(f"repeated: {', '.join(repeated)} (identical findings share one key; give one "
                        f"entry per key)")
    return problems


def _check_coverage(target: ReviewerReport, entries: Sequence[Refutation]) -> None:
    """Raise unless the entry keys name each distinct finding key of ``target``, exactly once, and
    nothing else."""
    problems = _coverage_problems(target, [e.key for e in entries])
    if problems:
        raise ValueError(f"refutations must cover each distinct finding key of {target.reviewer}, "
                         f"exactly once; " + "; ".join(problems))


def record_refutations(pr: RunKey, refuter: str, target: str, entries: Sequence[Mapping[str, object]] = (),
                       *, repo: Optional[Path] = None, run_id: Optional[str] = None) -> str:
    """Validate, write ``refutations/<target>.json`` (replacing), re-read it, print and return the block.

    ``refuter`` is ``adv_refute_<target>``. ``entries`` are ``{key, verdict, evidence}`` mappings that
    must name each distinct finding key of the target's recorded report, exactly once; the target's
    ``report_digest`` is stored alongside them. A target that has not recorded is refused.
    """
    _refutation_ids(refuter, target)
    root = _repo(repo)
    report_of_target = _target_report(pr, target, root, run_id)
    built = _validate_items(Refutation, entries, "refutation", root)
    _check_coverage(report_of_target, built)
    try:
        report = RefutationReport(refuter=refuter, target=target,
                                  report_digest=report_digest(report_of_target), refutations=built)
    except ValidationError as exc:
        raise ValueError(_error_text(exc)) from exc
    path, output = _report_path(pr, "refutations", report.target, root, run_id)
    _atomic_write(path, report.model_dump_json(indent=2) + "\n")
    block = refutation_block(load_refutations(path), output)
    _emit(block)
    return block


def record_refutations_draft(pr: RunKey, refuter: str, target: str, *, repo: Optional[Path] = None,
                             run_id: Optional[str] = None) -> str:
    """``record_refutations`` with the entries read from ``draft_path`` (a ``{refutations}`` object)."""
    _refutation_ids(refuter, target)
    draft = _read_draft(draft_path(pr, refuter, repo, run_id), ("refutations",))
    return record_refutations(pr, refuter, target, draft["refutations"], repo=repo, run_id=run_id)


def load_refutations(path: Path) -> RefutationReport:
    """The ``RefutationReport`` stored at ``path``."""
    return _load(RefutationReport, path)


def load_fix_reports(directory: Path) -> Tuple[FixReport, ...]:
    """Every ``FixReport`` in ``directory`` by file name; empty when the directory is missing."""
    if not directory.is_dir():
        return ()
    return tuple(_load(FixReport, p) for p in sorted(directory.glob("*.json")))
