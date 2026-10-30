"""Draw the README usage charts from the pr-review JSONL ledgers under ``docs/_harness/``.

Usage: harness_usage_charts.py [--data-dir DIR] [--out-dir DIR]

Two chart sets are written as standalone SVG files (stdlib only, no plotting library):

* ``model_share_<role>.svg``: one pie per ``role`` in ``pr_review_agent_usage.jsonl``, slices by model
  family (the model id collapsed to haiku / sonnet / opus, version ignored). The invocation test matrix
  (``pr_review_invocation_test_matrix.jsonl``) carries no ``role`` field; its rows are grouped by the role
  named in their ``notes`` text (``"...; reviewer DONE"``) and drawn as ``model_share_matrix_<role>.svg``.
* ``avg_tokens_by_role.svg``: mean ``tokens`` per dispatch for each ``role`` in the usage ledger, where one
  dispatch is one ledger row (one subagent run logged by pr-review-watch, re-dispatches included).

Each SVG paints its own opaque card and switches palette under ``prefers-color-scheme: dark``, so it reads
on both README themes. A per-role summary is printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
USAGE_FILE = "pr_review_agent_usage.jsonl"
MATRIX_FILE = "pr_review_invocation_test_matrix.jsonl"
FAMILIES = ("opus", "sonnet", "haiku")
FAMILY_RE = re.compile(r"(haiku|sonnet|opus)", re.IGNORECASE)
NOTES_ROLE_RE = re.compile(r";\s*(\w+)\s+(?:DONE|NO_BLOCK|FAIL)\b")
FONT = "system-ui,-apple-system,'Segoe UI',sans-serif"

LIGHT = {"bg": "#fcfcfb", "border": "#e1e0d9", "t1": "#0b0b0b", "t2": "#52514e", "mu": "#6f6d68",
         "grid": "#e1e0d9", "axis": "#c3c2b7", "opus": "#2a78d6", "sonnet": "#eb6834", "haiku": "#1baf7a"}
DARK = {"bg": "#1a1a19", "border": "#383835", "t1": "#f0efec", "t2": "#c3c2b7", "mu": "#a3a29b",
        "grid": "#2c2c2a", "axis": "#383835", "opus": "#3987e5", "sonnet": "#d95926", "haiku": "#199e70"}


def read_jsonl(path: Path, skipped: Counter) -> Iterator[dict]:
    """Yield each parsable object row; count non-blank unparsable lines under ``skipped``."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped[f"{path.name}: malformed JSON"] += 1
            continue
        if isinstance(row, dict):
            yield row
        else:
            skipped[f"{path.name}: not an object"] += 1


def model_family(row: dict) -> Optional[str]:
    """Collapse ``model`` (preferred) or ``model_family`` to haiku / sonnet / opus, version ignored."""
    for key in ("model", "model_family"):
        match = FAMILY_RE.search(str(row.get(key) or ""))
        if match:
            return match.group(1).lower()
    return None


def matrix_role(row: dict) -> Optional[str]:
    """Return the role named in a matrix row's ``notes`` (the matrix has no ``role`` field)."""
    match = NOTES_ROLE_RE.search(str(row.get("notes") or ""))
    return match.group(1) if match else None


def tally_families(rows: List[dict], role_of, label: str, skipped: Counter) -> Dict[str, Counter]:
    """Count model families per role; rows lacking a role or a family are counted as skipped."""
    out: Dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        role, family = role_of(row), model_family(row)
        if not role:
            skipped[f"{label}: no role"] += 1
        elif not family:
            skipped[f"{label}: no model family"] += 1
        else:
            out[role][family] += 1
    return dict(out)


def mean_tokens(rows: List[dict], skipped: Counter) -> Dict[str, Tuple[int, float]]:
    """Map each usage role to (dispatch count, mean tokens per dispatch)."""
    acc: Dict[str, List[int]] = defaultdict(list)
    for row in rows:
        tokens = row.get("tokens")
        if not row.get("role"):
            skipped[f"{USAGE_FILE}: no role (bar)"] += 1
        elif not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            skipped[f"{USAGE_FILE}: tokens missing or not a non-negative int"] += 1
        else:
            acc[row["role"]].append(tokens)
    return {role: (len(v), sum(v) / len(v)) for role, v in acc.items()}


def style_block() -> str:
    """CSS for both themes; the dark block overrides the light classes under the OS/browser setting."""
    def rules(p: Dict[str, str]) -> str:
        fams = "".join(f".f-{f}{{fill:{p[f]}}}" for f in FAMILIES)
        return (f".bg{{fill:{p['bg']};stroke:{p['border']}}}.gap{{stroke:{p['bg']}}}"
                f".t1{{fill:{p['t1']}}}.t2{{fill:{p['t2']}}}.mu{{fill:{p['mu']}}}"
                f".grid{{stroke:{p['grid']}}}.axis{{stroke:{p['axis']}}}{fams}")
    return (f"<style>text{{font-family:{FONT}}}.num{{font-variant-numeric:tabular-nums}}{rules(LIGHT)}"
            f"@media (prefers-color-scheme: dark){{{rules(DARK)}}}</style>")


def svg_open(width: int, height: int, title: str, desc: str) -> List[str]:
    """Open an SVG document with an accessible title/desc, the theme CSS and an opaque card."""
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
        f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>',
        style_block(),
        f'<rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" '
        f'fill="{LIGHT["bg"]}" stroke="{LIGHT["border"]}"/>',
    ]


def heading(title: str, subtitle: str) -> List[str]:
    """Title and subtitle lines in primary and secondary ink."""
    return [
        f'<text class="t1" x="24" y="36" font-size="17" font-weight="600" fill="{LIGHT["t1"]}">'
        f'{escape(title)}</text>',
        f'<text class="t2" x="24" y="58" font-size="12.5" fill="{LIGHT["t2"]}">{escape(subtitle)}</text>',
    ]


def slice_path(cx: float, cy: float, r: float, a0: float, a1: float) -> str:
    """SVG path for a pie wedge between angles a0 and a1 (radians, clockwise from 12 o'clock)."""
    x0, y0 = cx + r * math.sin(a0), cy - r * math.cos(a0)
    x1, y1 = cx + r * math.sin(a1), cy - r * math.cos(a1)
    large = 1 if a1 - a0 > math.pi else 0
    return f"M{cx},{cy} L{x0:.2f},{y0:.2f} A{r},{r} 0 {large} 1 {x1:.2f},{y1:.2f} Z"


def pie_marks(counts: Counter, cx: float, cy: float, r: float) -> List[str]:
    """Wedges in fixed family order, separated by a 2px surface-coloured gap."""
    total = sum(counts.values())
    present = [f for f in FAMILIES if counts.get(f)]
    marks, angle = [], 0.0
    for fam in present:
        share = counts[fam] / total
        tip = f"<title>{fam}: {counts[fam]} of {total} ({share:.1%})</title>"
        common = f'class="f-{fam} gap" fill="{LIGHT[fam]}" stroke="{LIGHT["bg"]}" stroke-width="2"'
        if len(present) == 1:
            marks.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {common}>{tip}</circle>')
            continue
        end = angle + share * 2 * math.pi
        marks.append(f'<path d="{slice_path(cx, cy, r, angle, end)}" {common} '
                     f'stroke-linejoin="round">{tip}</path>')
        angle = end
    return marks


def pie_legend(counts: Counter, x: float, y_mid: float) -> List[str]:
    """Legend rows (swatch, family, count, share) that double as the direct labels."""
    total = sum(counts.values())
    present = [f for f in FAMILIES if counts.get(f)]
    y = y_mid - (len(present) - 1) * 15
    out = []
    for fam in present:
        out.append(f'<rect class="f-{fam}" x="{x}" y="{y - 10}" width="12" height="12" rx="3" '
                   f'fill="{LIGHT[fam]}"/>')
        out.append(f'<text class="t1" x="{x + 20}" y="{y}" font-size="14" fill="{LIGHT["t1"]}">{fam}</text>')
        out.append(f'<text class="t1 num" x="{x + 200}" y="{y}" font-size="14" text-anchor="end" '
                   f'fill="{LIGHT["t1"]}">{counts[fam]}  ({counts[fam] / total:.1%})</text>')
        y += 30
    return out


def pie_svg(label: str, counts: Counter, source: str, unit: str) -> str:
    """One self-contained pie chart card for a single role."""
    total = sum(counts.values())
    title = f"{label[0].upper()}{label[1:]}: model family share"
    subtitle = f"n = {total} {unit} · {source}"
    desc = ", ".join(f"{f} {counts[f]}" for f in FAMILIES if counts.get(f))
    parts = svg_open(560, 250, title, f"{subtitle}. {desc}.")
    parts += heading(title, subtitle)
    parts += pie_marks(counts, 140, 152, 72)
    parts += pie_legend(counts, 280, 152)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def nice_axis(peak: float) -> Tuple[float, float]:
    """Return (axis maximum, tick step) giving four to six round ticks."""
    raw = peak / 4 if peak > 0 else 1.0
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return math.ceil(peak / step) * step, step


def short_num(v: float) -> str:
    """Compact tick label: 250k, 1.5M."""
    if v >= 1e6:
        return f"{v / 1e6:g}M"
    return f"{v / 1e3:g}k" if v >= 1e3 else f"{v:g}"


def bar_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Horizontal bar anchored square at the baseline, rounded at the data end."""
    r = min(r, w, h / 2)
    return (f"M{x},{y} H{x + w - r:.2f} Q{x + w:.2f},{y} {x + w:.2f},{y + r} V{y + h - r} "
            f"Q{x + w:.2f},{y + h} {x + w - r:.2f},{y + h} H{x} Z")


def bar_axis(x0: float, x1: float, top: float, bottom: float, axis_max: float, step: float) -> List[str]:
    """Solid hairline gridlines with tick labels below the plot, plus the baseline."""
    out, v = [], 0.0
    while v <= axis_max + 1e-9:
        x = x0 + (x1 - x0) * v / axis_max
        out.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{bottom}" '
                   f'stroke="{LIGHT["grid"]}" stroke-width="1"/>')
        out.append(f'<text class="mu num" x="{x:.2f}" y="{bottom + 18}" font-size="11.5" '
                   f'text-anchor="middle" fill="{LIGHT["mu"]}">{short_num(v)}</text>')
        v += step
    out.append(f'<line class="axis" x1="{x0}" y1="{top}" x2="{x0}" y2="{bottom}" '
               f'stroke="{LIGHT["axis"]}" stroke-width="1"/>')
    return out


def bar_row(role: str, n: int, avg: float, y: float, x0: float, scale: float) -> List[str]:
    """Category label with its dispatch count, the bar, and the value at the bar end."""
    w = max(avg * scale, 1.0)
    tip = f"<title>{role}: mean {avg:,.0f} tokens over {n} dispatches</title>"
    return [
        f'<text class="t1" x="{x0 - 12}" y="{y + 9}" font-size="13.5" text-anchor="end" '
        f'fill="{LIGHT["t1"]}">{escape(role)}</text>',
        f'<text class="mu num" x="{x0 - 12}" y="{y + 24}" font-size="11" text-anchor="end" '
        f'fill="{LIGHT["mu"]}">n = {n}</text>',
        f'<path class="f-opus" d="{bar_path(x0, y, w, 18)}" fill="{LIGHT["opus"]}">{tip}</path>',
        f'<text class="t1 num" x="{x0 + w + 8:.2f}" y="{y + 13.5}" font-size="12.5" '
        f'fill="{LIGHT["t1"]}">{avg:,.0f}</text>',
    ]


def bar_svg(stats: Dict[str, Tuple[int, float]], source: str) -> str:
    """Horizontal bar chart of mean tokens per dispatch, one bar per role, sorted descending."""
    order = sorted(stats, key=lambda k: stats[k][1], reverse=True)
    total = sum(n for n, _ in stats.values())
    x0, x1, top, pitch = 140.0, 540.0, 84.0, 42.0
    bottom = top + pitch * len(order)
    axis_max, step = nice_axis(max(avg for _, avg in stats.values()))
    title = "Mean tokens per subagent dispatch, by role"
    subtitle = f"n = {total} dispatches (1 ledger row = 1 dispatch) · {source}"
    parts = svg_open(640, int(bottom + 44), title, subtitle)
    parts += heading(title, subtitle)
    parts += bar_axis(x0, x1, top - 8, bottom - 6, axis_max, step)
    for i, role in enumerate(order):
        n, avg = stats[role]
        parts += bar_row(role, n, avg, top + i * pitch, x0, (x1 - x0) / axis_max)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def print_summary(usage: Dict[str, Counter], matrix: Dict[str, Counter],
                  stats: Dict[str, Tuple[int, float]], skipped: Counter) -> None:
    """Per-role counts, family splits and token means, plus any skipped rows."""
    for label, tallies in ((USAGE_FILE, usage), (MATRIX_FILE, matrix)):
        print(f"== {label}")
        for role, c in sorted(tallies.items(), key=lambda kv: -sum(kv[1].values())):
            fams = ", ".join(f"{f}={c[f]}" for f in FAMILIES if c.get(f))
            print(f"  {role:<13} n={sum(c.values()):<4} {fams}")
    print("== mean tokens per dispatch")
    for role, (n, avg) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
        print(f"  {role:<13} n={n:<4} mean={avg:,.1f}")
    print("== skipped:", dict(skipped) or "none")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="harness_usage_charts.py", description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "docs" / "_harness")
    parser.add_argument("--out-dir", type=Path, default=None, help="Default: <data-dir>/charts")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or args.data_dir / "charts"
    skipped: Counter = Counter()
    usage_rows = list(read_jsonl(args.data_dir / USAGE_FILE, skipped))
    matrix_rows = list(read_jsonl(args.data_dir / MATRIX_FILE, skipped))
    usage = tally_families(usage_rows, lambda r: r.get("role"), USAGE_FILE, skipped)
    matrix = tally_families(matrix_rows, matrix_role, MATRIX_FILE, skipped)
    stats = mean_tokens(usage_rows, skipped)
    for role, counts in usage.items():
        unit = "dispatch" if sum(counts.values()) == 1 else "dispatches"
        write(out_dir / f"model_share_{role}.svg", pie_svg(role, counts, USAGE_FILE, unit))
    for role, counts in matrix.items():
        label = f"{role} (test matrix)"
        write(out_dir / f"model_share_matrix_{role}.svg", pie_svg(label, counts, MATRIX_FILE, "rows"))
    write(out_dir / "avg_tokens_by_role.svg", bar_svg(stats, USAGE_FILE))
    print_summary(usage, matrix, stats, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
