"""QA pass for pr-team.

Validates the consolidated PR review JSON against its schema AND cross-checks
its contents against aggregated agent return-contract signals captured in the
runtime terminals.jsonl file.

Exits 0 on PASS; 1 on any check failure; 2 on argv shape error or input load
failure.

Usage (Bash tool):
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/pr-team/commands/qa_review_json.py" \
        --json <path-to-consolidated-PR-review-JSON> \
        --schema <path-to-PR_REVIEW.schema.json> \
        --terminals-file <path-to-runtime-terminals.jsonl> \
        --dispatch-plan <path-to-dispatch_plan_review.json> \
        --fix-plan <path-to-dispatch_plan_fix.json> \
        [--bubble-ups <path-to-bubble_ups.json>]

Check inventory:
    A1  JSON schema validation against PR_REVIEW.schema.json
    A2  pre_fix_time sentinel present in verification_log
    A3  verdict regex match
    A4  terminals rows validate against terminals.schema.json
    B1-B3  reviewer counts cross-checks
    C1-C5 (C2a, C2b subsets)  closer / fixer cross-checks
    D  post_review_resolutions status enum
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    # noinspection PyUnusedImports
    import jsonschema
    # noinspection PyUnusedImports
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012  # noqa: F401  (availability probe)
except ImportError:
    print("FATAL: jsonschema + referencing packages required (pip install jsonschema)", file=sys.stderr)
    sys.exit(2)

CheckResult = Tuple[bool, str]
_TERMINALS_SCHEMA_DIR = Path(__file__).resolve().parent.parent


def _build_terminals_validator() -> jsonschema.Draft202012Validator:
    """Construct a Draft202012Validator over the union terminals schema.

    Every schema self-declares its dialect via `$schema`, so each can be
    registered via `Resource.from_contents` without an explicit specification.
    Registry keys are full filenames (terminals.reviewer.schema.json,
    terminals.fixer.schema.json, terminals.common.schema.json) to match the
    relative `$ref` slugs used by the role-specific schemas + the union.
    """
    common = _load_json(_TERMINALS_SCHEMA_DIR / "terminals.common.schema.json")
    reviewer = _load_json(_TERMINALS_SCHEMA_DIR / "terminals.reviewer.schema.json")
    fixer = _load_json(_TERMINALS_SCHEMA_DIR / "terminals.fixer.schema.json")
    union = _load_json(_TERMINALS_SCHEMA_DIR / "terminals.schema.json")
    registry = Registry().with_resources([
        ("terminals.common.schema.json", Resource.from_contents(common)),
        ("terminals.reviewer.schema.json", Resource.from_contents(reviewer)),
        ("terminals.fixer.schema.json", Resource.from_contents(fixer)),
    ])
    return jsonschema.Draft202012Validator(union, registry=registry)


def check_a4_terminals_rows_validate(terminals: List[Dict[str, Any]]) -> CheckResult:
    """A4. Every terminals.jsonl row validates against terminals.schema.json (union)."""
    try:
        v = _build_terminals_validator()
    except FileNotFoundError as exc:
        return False, f"A4 FAIL: cannot load terminals schemas: {exc}"
    bad: List[str] = []
    for i, row in enumerate(terminals, 1):
        try:
            errs = list(v.iter_errors(row))
        except Exception as exc:
            return False, f"A4 FAIL: unexpected error during schema validation: {exc}"
        if errs:
            agent_id = row.get("agent_id", "<no-id>")
            bad.append(f"line {i} (agent_id={agent_id}): {errs[0].message[:80]}")
        if len(bad) >= 3:
            break
    if bad:
        return False, f"A4 FAIL: terminals row(s) reject schema: {bad}"
    return True, f"A4 PASS: all {len(terminals)} terminals rows validate against union schema"


def _is_skip(msg: str) -> bool:
    """Check if a result is a SKIP signal."""
    return msg.startswith("SKIP:") or msg.split(":", 1)[0].endswith(" SKIP")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for ln, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"terminals.jsonl line {ln} not valid JSON: {exc}") from exc
    return rows


# A-checks: schema correctness

def check_a1_json_schema(json_doc: Dict[str, Any], schema_doc: Dict[str, Any]) -> CheckResult:
    """A1. JSON validates against PR_REVIEW.schema.json (draft-07)."""
    try:
        jsonschema.Draft7Validator(schema_doc).validate(json_doc)
        return True, "A1 PASS: consolidated JSON validates against PR_REVIEW.schema.json"
    except jsonschema.ValidationError as exc:
        loc = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        return False, f"A1 FAIL: schema validation error at {loc}: {exc.message}"
    except jsonschema.SchemaError as exc:
        return False, f"A1 FAIL: schema is malformed: {exc}"


def check_a2_pre_fix_time(json_doc: Dict[str, Any]) -> CheckResult:
    """A2. verification_log.pre_fix_time is the full struct, not the pending sentinel."""
    pre = json_doc.get("verification_log", {}).get("pre_fix_time")
    if isinstance(pre, str):
        return False, f"A2 FAIL: pre_fix_time is still the pending sentinel string: {pre!r}"
    if not isinstance(pre, dict):
        return False, f"A2 FAIL: pre_fix_time has unexpected type {type(pre).__name__}, expected object"
    return True, "A2 PASS: pre_fix_time is the full branch-safety struct"


def check_a3_verdict_regex(json_doc: Dict[str, Any]) -> CheckResult:
    """A3. verdict matches ^(READY TO MERGE|NOT READY TO MERGE)(.*)$."""
    verdict = json_doc.get("verdict", "")
    if re.match(r"^(READY TO MERGE|NOT READY TO MERGE)(.*)$", verdict):
        snippet = verdict[:60] + ("..." if len(verdict) > 60 else "")
        return True, f"A3 PASS: verdict prefix matches contract ({snippet!r})"
    return False, f"A3 FAIL: verdict does not match regex: {verdict!r}"


# B-checks: reviewer consistency

def check_b1_reviewer_coverage(
    plan: Dict[str, Any],
    terminals: List[Dict[str, Any]],
) -> CheckResult:
    """B1. Every planned reviewer has a terminals entry (DONE or FAIL)."""
    planned_ids = {a["id"] for a in plan.get("agents", [])}
    if not planned_ids:
        return True, "B1 PASS: no reviewers planned (orchestrator returned empty plan)"
    term_ids = {
        t["agent_id"] for t in terminals
        if t.get("agent_role") == "reviewer" and t.get("signal") in ("DONE", "FAIL")
    }
    missing = planned_ids - term_ids
    if missing:
        return False, f"B1 FAIL: planned reviewers with no terminal entry: {sorted(missing)}"
    return True, f"B1 PASS: all {len(planned_ids)} planned reviewers have terminals"


def _reviewer_done_rows(plan: Dict[str, Any], terminals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """DONE reviewer rows with ``counts`` from planned reviewers."""
    planned_ids = {a["id"] for a in plan.get("agents", [])}
    return [
        t for t in terminals
        if t.get("agent_role") == "reviewer"
        and t.get("agent_id") in planned_ids
        and t.get("signal") == "DONE"
        and "counts" in t
    ]


def _miscounted_reviewers(rows: List[Dict[str, Any]]) -> List[str]:
    """Agent ids whose ``counts.findings`` differs from ``critical + important + minor``."""
    return [
        str(t.get("agent_id")) for t in rows
        if t["counts"].get("findings", 0)
        != sum(t["counts"].get(sev, 0) for sev in ("critical", "important", "minor"))
    ]


def check_b2_findings_count(
    json_doc: Dict[str, Any],
    plan: Dict[str, Any],
    terminals: List[Dict[str, Any]],
) -> CheckResult:
    """B2. Each reviewer's findings equal its severity sum; their total >= JSON issue count (de-dup ok)."""
    reviewer_done = _reviewer_done_rows(plan, terminals)
    miscounted = _miscounted_reviewers(reviewer_done)
    if miscounted:
        return False, (
            f"B2 FAIL: counts.findings != critical + important + minor for reviewers {miscounted}"
        )
    reviewer_sum = sum(t["counts"].get("findings", 0) for t in reviewer_done)
    issues = json_doc.get("issues", {})
    json_count = (
        len(issues.get("critical", []))
        + len(issues.get("important", []))
        + len(issues.get("minor", []))
    )
    if reviewer_sum >= json_count:
        dedup = reviewer_sum - json_count
        msg = (
            f"B2 PASS: reviewer-sum {reviewer_sum} >= JSON-count {json_count} "
            f"(de-dup factor {dedup})"
        )
        return True, msg
    msg = (
        f"B2 FAIL: reviewer-sum {reviewer_sum} < JSON-count {json_count} "
        f"(consolidator invented findings)"
    )
    return False, msg


def check_b3_per_severity(
    json_doc: Dict[str, Any],
    plan: Dict[str, Any],
    terminals: List[Dict[str, Any]],
) -> CheckResult:
    """B3. JSON per-severity <= reviewer summed per-severity."""
    reviewer_done = _reviewer_done_rows(plan, terminals)
    for sev in ("critical", "important", "minor"):
        json_n = len(json_doc.get("issues", {}).get(sev, []))
        rev_n = sum(t["counts"].get(sev, 0) for t in reviewer_done)
        if json_n > rev_n:
            return False, f"B3 FAIL: JSON {sev}={json_n} exceeds reviewer-sum {rev_n}"
    return True, "B3 PASS: all per-severity counts within reviewer sums"


# C-checks: fixer consistency

def check_c1_fixer_coverage(
    plan: Dict[str, Any],
    terminals: List[Dict[str, Any]],
) -> CheckResult:
    """C1. Every planned fixer has a terminals entry."""
    planned_ids = {a["id"] for a in plan.get("agents", [])}
    if not planned_ids:
        return True, "C1 PASS: no fixers planned (all bubbled)"
    valid_signals = ("DONE", "FAIL", "FORK_AMBIGUITY", "FORK_BLOCKER", "STOP")
    term_ids = {
        t["agent_id"] for t in terminals
        if t.get("agent_role") == "fixer" and t.get("signal") in valid_signals
    }
    missing = planned_ids - term_ids
    if missing:
        return False, f"C1 FAIL: planned fixers with no terminal entry: {sorted(missing)}"
    return True, f"C1 PASS: all {len(planned_ids)} planned fixers have terminals"


def check_c2_resolved_equality(
    json_doc: Dict[str, Any],
    plan: Dict[str, Any],
    terminals: List[Dict[str, Any]],
) -> CheckResult:
    """C2. RESOLVED-status ids in post_review_resolutions == aggregate fixer-DONE `fixed` ids."""
    planned_fixer_ids = {a["id"] for a in plan.get("agents", [])}
    fixer_done_fixed = set()
    for t in terminals:
        if (
            t.get("agent_role") == "fixer"
            and t.get("agent_id") in planned_fixer_ids
            and t.get("signal") == "DONE"
            and isinstance(t.get("fixed"), list)
        ):
            fixer_done_fixed.update(t["fixed"])
    json_resolved = {
        r["id"] for r in json_doc.get("post_review_resolutions", [])
        if r.get("status") == "RESOLVED"
    }
    extra = json_resolved - fixer_done_fixed
    missing = fixer_done_fixed - json_resolved
    if extra or missing:
        diag = []
        if extra:
            diag.append(f"in JSON but not in any fixer DONE.fixed: {sorted(extra)}")
        if missing:
            diag.append(f"in fixer DONE.fixed but not in JSON: {sorted(missing)}")
        return False, f"C2 FAIL: RESOLVED-id mismatch ({'; '.join(diag)})"
    return True, f"C2 PASS: {len(json_resolved)} RESOLVED ids match aggregate fixer DONE.fixed exactly"


# Narrow on purpose — augmented by C4 bubble enumeration. Add patterns as new auto-CNA shapes are observed.
_AUTO_CNA_PATTERNS = (
    re.compile(r"\bfixer\s+(bubbled|failed|fail)\b", re.IGNORECASE),
    re.compile(r"^\s*bubbled\b", re.IGNORECASE),
    re.compile(r"^\s*classification\s*:", re.IGNORECASE),
)


def check_c2a_no_auto_closed_no_action(json_doc: Dict[str, Any]) -> CheckResult:
    """C2a. Every CLOSED_NO_ACTION entry must have user-decision evidence."""
    bad: List[Tuple[str, str]] = []
    for r in json_doc.get("post_review_resolutions", []):
        if r.get("status") != "CLOSED_NO_ACTION":
            continue
        evidence = r.get("evidence", "")
        if any(pat.search(evidence) for pat in _AUTO_CNA_PATTERNS):
            bad.append((r.get("id", "<no-id>"), evidence[:80]))
    if bad:
        return False, f"C2a FAIL: auto-generated CLOSED_NO_ACTION entries: {bad}"
    return True, "C2a PASS: no auto-generated CLOSED_NO_ACTION entries"


def check_c2b_closer_aggregates_fixer_fixed(rows: List[Dict[str, Any]],
                                            planned_fixer_ids: Set[str]) -> CheckResult:
    """C2b: closer DONE row's `fixed` array MUST equal the union of all
    fixer-role DONE rows' `fixed` arrays (per terminals.fixer.schema.json:41)."""
    fixer_done_fixed = set()
    closer_row = None
    for row in rows:
        if row.get("agent_role") != "fixer":
            continue
        if row.get("signal") != "DONE":
            continue
        agent_id = row.get("agent_id")
        if agent_id == "closer":
            closer_row = row
        elif agent_id in planned_fixer_ids:
            fixer_done_fixed.update(row.get("fixed", []))
    if closer_row is None:
        return True, "C2b PASS: no closer DONE row to cross-check"
    closer_fixed = set(closer_row.get("fixed", []))
    if closer_fixed != fixer_done_fixed:
        missing = fixer_done_fixed - closer_fixed
        extra = closer_fixed - fixer_done_fixed
        return False, (f"C2b FAIL: closer aggregate mismatch — missing={sorted(missing)}, "
                       f"extra={sorted(extra)}")
    return True, f"C2b PASS: closer aggregate matches {len(closer_fixed)} ids"


def check_c3_orphan_resolution(json_doc: Dict[str, Any]) -> CheckResult:
    """C3. Every post_review_resolutions[].id is a member of issues.*[].id."""
    issue_ids = set()
    for sev in ("critical", "important", "minor"):
        for i in json_doc.get("issues", {}).get(sev, []):
            issue_ids.add(i.get("id"))
    res_ids = {r.get("id") for r in json_doc.get("post_review_resolutions", [])}
    orphans = res_ids - issue_ids
    if orphans:
        return False, f"C3 FAIL: post_review_resolutions ids with no matching issue: {sorted(orphans)}"
    return True, f"C3 PASS: all {len(res_ids)} resolution ids map to issues"


def check_c4_bubble_enumeration(
    terminals: List[Dict[str, Any]],
    bubble_ups: Optional[Dict[str, Any]],
) -> CheckResult:
    """C4. Closer's DONE row `bubbled` array == bubble_ups sidecar items[].id set.

    The bubble_ups sidecar matches bubble_ups.schema.json:
    `{run_id: ..., items: [{id, classification, reason}, ...]}`. The closer's
    terminals.jsonl row (agent_id=='closer', agent_role=='fixer', signal=='DONE')
    carries a `bubbled` array directly per terminals.fixer.schema.json. C4
    verifies the two sets are equal (no regex on TERMINAL NOTES — read the
    structured field).
    """
    if bubble_ups is None:
        return True, "C4 SKIP: no bubble_ups sidecar provided"
    if not isinstance(bubble_ups, dict):
        return False, "C4 FAIL: bubble_ups sidecar is not a JSON object"
    items = bubble_ups.get("items", [])
    expected = {b.get("id") for b in items if b.get("id")}
    if not expected:
        return True, "C4 PASS: bubble_ups sidecar has no items"
    closer_dones = [
        t for t in terminals
        if t.get("agent_id") == "closer"
        and t.get("agent_role") == "fixer"
        and t.get("signal") == "DONE"
        and isinstance(t.get("bubbled"), list)
    ]
    if len(closer_dones) > 1:
        return False, f"C4 FAIL: {len(closer_dones)} closer DONE rows found, expected exactly 1"
    if not closer_dones:
        msg = (
            "C4 FAIL: no closer DONE row in terminals.jsonl "
            "(looking for agent_id=='closer' + agent_role=='fixer' + signal=='DONE' "
            "+ bubbled present)"
        )
        return False, msg
    listed = set(closer_dones[-1]["bubbled"])
    missing = expected - listed
    extra = listed - expected
    if missing or extra:
        return False, f"C4 FAIL: mismatch — missing={sorted(missing)}, extra={sorted(extra)}"
    return True, f"C4 PASS: closer enumerated all {len(expected)} bubble-up ids in TERMINAL"


def check_c5_evidence_coverage(rows: List[Dict[str, Any]]) -> CheckResult:
    """C5: for each fixer DONE row with non-empty fixed, evidence keys MUST
    correspond EXACTLY to fixed IDs (bidirectional — no missing keys AND no
    extras). See terminals.fixer.schema.json:55-66."""
    for row in rows:
        if row.get("agent_role") != "fixer":
            continue
        if row.get("signal") != "DONE":
            continue
        fixed = row.get("fixed", []) or []
        if not fixed:
            continue
        evidence = row.get("evidence", {}) or {}
        evidence_keys = set(evidence.keys())
        fixed_set = set(fixed)
        missing = fixed_set - evidence_keys
        extra = evidence_keys - fixed_set
        if missing or extra:
            agent_id = row.get("agent_id", "<unknown>")
            parts = []
            if missing:
                parts.append(f"missing keys for fixed ids: {sorted(missing)}")
            if extra:
                parts.append(f"extra keys not in fixed[]: {sorted(extra)}")
            return False, f"C5 FAIL: {agent_id} evidence {' — '.join(parts)}"
    return True, "C5 PASS: evidence corresponds exactly to fixed for all fixer DONE rows"


# D-check: verdict re-evaluation


def check_d_verdict(json_doc: Dict[str, Any]) -> CheckResult:
    """D1-D5. Recompute verdict from issues + post_review_resolutions; compare."""
    issues_by_sev = json_doc.get("issues", {})
    res = json_doc.get("post_review_resolutions", [])
    closed_statuses = {"RESOLVED", "CLOSED_NO_ACTION"}
    closed_ids = {r["id"] for r in res if r.get("status") in closed_statuses}
    unresolved_c = [
        i["id"] for i in issues_by_sev.get("critical", [])
        if i.get("id") not in closed_ids
    ]
    unresolved_i = [
        i["id"] for i in issues_by_sev.get("important", [])
        if i.get("id") not in closed_ids
    ]
    if unresolved_c or unresolved_i:
        expected = "NOT READY TO MERGE"
    else:
        expected = "READY TO MERGE"
    verdict = json_doc.get("verdict", "")
    if verdict.startswith(expected):
        msg = (
            f"D PASS: verdict prefix '{expected}' matches re-eval "
            f"(uC={len(unresolved_c)}, uI={len(unresolved_i)})"
        )
        return True, msg
    msg = (
        f"D FAIL: expected verdict prefix '{expected}' "
        f"(uC={unresolved_c}, uI={unresolved_i}) but got: {verdict[:60]!r}"
    )
    return False, msg


# Main


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QA pass for pr-team.")
    parser.add_argument("--json", required=True, type=Path, help="Path to consolidated PR review JSON")
    parser.add_argument("--schema", required=True, type=Path, help="Path to PR_REVIEW.schema.json")
    parser.add_argument("--terminals-file", required=True, type=Path, help="Path to runtime terminals.jsonl")
    parser.add_argument("--dispatch-plan", required=True, type=Path, help="Path to dispatch_plan_review.json")
    parser.add_argument("--fix-plan", required=True, type=Path, help="Path to dispatch_plan_fix.json")
    parser.add_argument("--bubble-ups", required=False, type=Path, help="Optional bubble_ups.json sidecar")
    return parser


def _load_inputs(args: argparse.Namespace) -> Tuple[
    Dict[str, Any], Dict[str, Any], List[Dict[str, Any]],
    Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]
]:
    """Load all input files; raise on failure."""
    json_doc = _load_json(args.json)
    schema_doc = _load_json(args.schema)
    terminals = _load_jsonl(args.terminals_file)
    review_plan = _load_json(args.dispatch_plan)
    fix_plan = _load_json(args.fix_plan)
    bubble_ups = (
        _load_json(args.bubble_ups)
        if args.bubble_ups is not None and args.bubble_ups.exists()
        else None
    )
    return json_doc, schema_doc, terminals, review_plan, fix_plan, bubble_ups

@dataclass(frozen=True, kw_only=True)
class SummaryResult:
    count: int
    skip: int
    name: str
    total: int

    @classmethod
    def from_checks(cls, checks: List[CheckResult], prefix: str) -> SummaryResult:
        count = sum(1 for r in checks if r[1].startswith(prefix) and not _is_skip(r[1]))
        skip = sum(1 for r in checks if r[1].startswith(prefix) and _is_skip(r[1]))
        return cls(count=count, skip=skip, name=prefix, total=count + skip)

    def __str__(self):
        return f"A={self.count}/{self.total} (skipped: {self.skip})"

def _summarize(checks: List[CheckResult], run_id: str) -> int:
    """Count check results and print summary; return exit code."""
    fails = [(ok, msg) for ok, msg in checks if not ok]
    if fails:
        for _, msg in fails:
            if _is_skip(msg):
                print(f"QA_SKIP: {msg}", file=sys.stderr)
            else:
                print(f"QA_FAIL: {msg}", file=sys.stderr)
        print(
            "RECOVERY: inspect the consolidated PR review JSON and the listed inputs; "
            "re-invoke the skill from scratch only if a fresh run is wanted.",
            file=sys.stderr,
        )
        return 1

    print(
        f"QA_PASS: {run_id} | ")

    for prefix in ("A", "B", "C", "D"):
        result = SummaryResult.from_checks(checks, prefix)
        print(f"{prefix}: {result}, ")

    print(
        f"all {len(checks)} checks complete."
    )
    return 0


def _run_all_checks(
    json_doc: Dict[str, Any],
    schema_doc: Dict[str, Any],
    terminals: List[Dict[str, Any]],
    review_plan: Dict[str, Any],
    fix_plan: Dict[str, Any],
    bubble_ups: Optional[Dict[str, Any]],
) -> List[CheckResult]:
    """Run A, B, C, D checks; skip B/C/D if A1 fails."""
    a_results: List[CheckResult] = [
        check_a1_json_schema(json_doc, schema_doc),
        check_a2_pre_fix_time(json_doc),
        check_a3_verdict_regex(json_doc),
        check_a4_terminals_rows_validate(terminals),
    ]
    a1_ok = a_results[0][0]

    if a1_ok:
        other_results: List[CheckResult] = [
            check_b1_reviewer_coverage(review_plan, terminals),
            check_b2_findings_count(json_doc, review_plan, terminals),
            check_b3_per_severity(json_doc, review_plan, terminals),
            check_c1_fixer_coverage(fix_plan, terminals),
            check_c2_resolved_equality(json_doc, fix_plan, terminals),
            check_c2a_no_auto_closed_no_action(json_doc),
            check_c2b_closer_aggregates_fixer_fixed(terminals, {a["id"] for a in fix_plan.get("agents", [])}),
            check_c3_orphan_resolution(json_doc),
            check_c4_bubble_enumeration(terminals, bubble_ups),
            check_c5_evidence_coverage(terminals),
            check_d_verdict(json_doc),
        ]
    else:
        skipped_checks = ["B1", "B2", "B3", "C1", "C2", "C2a", "C2b", "C3", "C4", "C5", "D"]
        other_results = [
            (True, f"{check_id} SKIP: A1 schema validation failed")
            for check_id in skipped_checks
        ]

    return a_results + other_results


def main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()

    try:
        json_doc, schema_doc, terminals, review_plan, fix_plan, bubble_ups = (
            _load_inputs(args)
        )
    except FileNotFoundError as exc:
        print(f"FATAL: input file not found: {exc.filename}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"FATAL: input file malformed: {exc}", file=sys.stderr)
        return 2

    run_id = review_plan.get("run_id", "<unknown>")
    checks = _run_all_checks(
        json_doc, schema_doc, terminals, review_plan, fix_plan, bubble_ups
    )
    return _summarize(checks, run_id)


if __name__ == "__main__":
    sys.exit(main())
