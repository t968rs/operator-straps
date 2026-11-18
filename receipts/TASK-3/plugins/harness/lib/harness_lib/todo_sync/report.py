"""Findings, the check report (``TodoSyncReport.schema.json``), its atomic JSON writer and text formats.

Also writes the TODO snapshot header line rule T2 reads back; ``snapshot_html`` draws the page under it.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
SEVERITIES = ("error", "warn")
REPLACE_ATTEMPTS = 5
REPLACE_DELAY_SECONDS = 0.05


@dataclass(frozen=True)
class Finding:
    """One rule violation; ``file`` is a repo-relative POSIX path or None."""

    rule: str
    severity: str
    file: Optional[str]
    message: str
    line: Optional[int] = None
    subject: Optional[str] = None
    fix: Optional[str] = None


@dataclass(frozen=True)
class Report:
    """Result of one check run."""

    generated_at: str
    elapsed_ms: float
    rules_run: Tuple[str, ...]
    rules_skipped: Tuple[Tuple[str, str], ...]
    findings: Tuple[Finding, ...]
    warn_counts: bool = False
    gh_fetched_at: Optional[str] = None
    order: Tuple[str, ...] = field(default=())

    def counted(self, finding: Finding) -> bool:
        """Whether ``finding`` is part of the drift number."""
        return finding.severity == "error" or (self.warn_counts and finding.severity == "warn")

    @property
    def drift(self) -> int:
        """Number of counted findings."""
        return sum(1 for f in self.findings if self.counted(f))

    def by_severity(self, severity: str) -> int:
        """All findings of ``severity``, counted or not."""
        return sum(1 for f in self.findings if f.severity == severity)

    def by_rule(self) -> Dict[str, int]:
        """Counted findings per rule id, rules with none left out."""
        out: Dict[str, int] = {}
        for f in self.findings:
            if self.counted(f):
                out[f.rule] = out.get(f.rule, 0) + 1
        return out

    def sorted_findings(self) -> List[Finding]:
        """Errors first, then by rule (catalog order) and file."""
        rank = {rule: n for n, rule in enumerate(self.order)}
        return sorted(self.findings, key=lambda f: (f.severity != "error", rank.get(f.rule, len(rank)),
                                                     f.file or "", f.line or 0))

    def to_dict(self) -> Dict[str, Any]:
        """The JSON document ``TodoSyncReport.schema.json`` describes."""
        return {
            "schema_version": SCHEMA_VERSION, "generated_at": self.generated_at,
            "elapsed_ms": round(self.elapsed_ms, 1), "rules_run": list(self.rules_run),
            "rules_skipped": [{"rule": r, "reason": why} for r, why in self.rules_skipped],
            "drift": self.drift, "by_rule": self.by_rule(),
            "counts": {s: self.by_severity(s) for s in SEVERITIES},
            "gh_fetched_at": self.gh_fetched_at,
            "findings": [self._finding_dict(f) for f in self.sorted_findings()],
        }

    def _finding_dict(self, f: Finding) -> Dict[str, Any]:
        return {"rule": f.rule, "severity": f.severity, "counted": self.counted(f), "file": f.file,
                "line": f.line, "subject": f.subject, "message": f.message, "fix": f.fix}


def _replace_with_retry(src: str, dst: Path) -> None:
    """``os.replace(src, dst)``, retrying ``PermissionError`` up to ``REPLACE_ATTEMPTS`` times.

    The last failure propagates; other ``OSError`` values raise at once.
    """
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_DELAY_SECONDS)


def write_atomic(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` through a temp file in the same directory and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        _replace_with_retry(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_report(report: Report, path: Path) -> Path:
    """Write ``report`` as JSON to ``path`` atomically."""
    return write_atomic(path, json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n")


def format_summary(report: Report) -> str:
    """One line: drift, per-severity counts, rules run, elapsed time."""
    return (f"todo-sync drift={report.drift} error={report.by_severity('error')} "
            f"warn={report.by_severity('warn')} rules={len(report.rules_run)} "
            f"elapsed_ms={round(report.elapsed_ms)}")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _where(f: Finding) -> str:
    if f.file is None:
        return ""
    return f"{f.file}:{f.line}" if f.line else f.file


def format_markdown(report: Report) -> str:
    """Heading, counts and a findings table (rule, severity, file:line, subject, message, fix)."""
    lines = ["# TODO sync report", "",
             f"Drift **{report.drift}**: {report.by_severity('error')} error, {report.by_severity('warn')} "
             f"warn; {len(report.rules_run)} rules run, {len(report.rules_skipped)} skipped "
             f"({round(report.elapsed_ms)} ms).", ""]
    findings = report.sorted_findings()
    if not findings:
        return "\n".join(lines + ["No findings."]) + "\n"
    lines += ["| Rule | Severity | File:line | Subject | Message | Fix |", "|---|---|---|---|---|---|"]
    lines += [f"| {f.rule} | {f.severity} | {_cell(_where(f))} | {_cell(f.subject)} | {_cell(f.message)} | "
              f"{_cell(f.fix)} |" for f in findings]
    return "\n".join(lines) + "\n"


def snapshot_header(source: str, top: int, rows_sha256: str, rendered: str) -> str:
    """The first line of a rendered snapshot; rule T2 parses it back."""
    return f"<!-- todo-snapshot source={source} top={top} rows_sha256={rows_sha256} rendered={rendered} -->"
