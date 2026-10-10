"""QA-3 / B3 — field-level extraction accuracy against the answer key.

Scores extracted treaty terms against `ground_truth.json` and produces the
number that goes on the results slide. Pass bar: **>= 95% field accuracy**.

The harness is deliberately independent of *how* the extraction happened. It
takes `{treaty_id: {field: value}}` and knows nothing about Gemini, so it is
fully testable now and will produce a real number the moment a live extractor
exists. Nothing here changes when GCP access lands.

## Comparison is typed, not textual

`"72"`, `72` and `72.0` are the same hours clause; `["WS", "EQ"]` and
`["EQ", "WS"]` are the same peril list; `0.25` and `0.250000` are the same
share. A string compare would fail all three and report an accuracy far below
the truth, which is the sort of error that makes a team loosen a threshold
when the extractor was right all along.

Equally, `72` and `96` are not the same, and neither are `"JPN"` and
`["JPN"]` where a scalar was expected - so coercion is narrow and explicit
rather than best-effort.

## Citation pages are scored separately

QA-4 scores citation page accuracy at >= 95%, and it is reported on its own
line. A field extracted correctly but cited to the wrong page is a different
failure from a misread value: the number is right and the audit trail is
wrong, which in a regulated setting is arguably worse. Averaging the two
would hide both.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "PASS_BAR",
    "FieldOutcome",
    "AccuracyReport",
    "values_match",
    "load_ground_truth",
    "score_extraction",
    "format_report",
    "main",
]

#: QA-3's pass bar.
PASS_BAR = 0.95

#: Tolerance for a money or rate comparison. Tighter than a cent on figures
#: expressed in millions.
_NUMERIC_TOLERANCE = Decimal("0.000001")


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def _as_decimal(value: Any) -> Decimal | None:
    """Coerce to Decimal, or None when the value is not a number.

    `Decimal(str(x))` rather than `Decimal(x)`, for the reason in the loss
    engine: `Decimal(0.1)` carries the float's binary error and `Decimal("0.1")`
    does not.
    """
    # Booleans are handled by both callers before they reach here - `True == 1`
    # is never what a field comparison means - so there is no bool branch.
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def values_match(expected: Any, actual: Any) -> bool:
    """Whether an extracted value matches the answer key.

    Typed, not textual. Numbers compare numerically, lists compare as sets
    (clause order carries no meaning), strings compare case- and
    whitespace-insensitively. A type mismatch between a scalar and a list is
    a mismatch, not something to flatten.
    """
    if expected is None or actual is None:
        return expected is None and actual is None

    expected_is_list = isinstance(expected, (list, tuple, set))
    actual_is_list = isinstance(actual, (list, tuple, set))
    if expected_is_list != actual_is_list:
        return False

    if expected_is_list:
        left = {_normalise_scalar(item) for item in expected}
        right = {_normalise_scalar(item) for item in actual}
        return left == right

    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) is bool(actual) and type(expected) is type(actual)

    expected_number = _as_decimal(expected)
    actual_number = _as_decimal(actual)
    if expected_number is not None and actual_number is not None:
        return abs(expected_number - actual_number) <= _NUMERIC_TOLERANCE

    return _normalise_scalar(expected) == _normalise_scalar(actual)


def _normalise_scalar(value: Any) -> Any:
    # Booleans are tagged rather than normalised, so a list member behaves the
    # same way a scalar does. Untagged, `{True} == {Decimal(1)}` is true -
    # Python hashes them identically - and [True] would match [1].
    if isinstance(value, bool):
        return ("bool", value)
    number = _as_decimal(value)
    if number is not None:
        return number.normalize()
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldOutcome:
    treaty_id: str
    field: str
    expected: Any
    actual: Any
    matched: bool
    expected_page: int | None
    actual_page: int | None
    source: str = "text"
    missing: bool = False

    @property
    def page_matched(self) -> bool | None:
        """None when the extractor offered no page - unscored rather than
        counted as wrong, and surfaced separately so it cannot hide."""
        if self.actual_page is None or self.expected_page is None:
            return None
        return self.actual_page == self.expected_page


@dataclass
class AccuracyReport:
    outcomes: list[FieldOutcome] = field(default_factory=list)

    # -- field accuracy (QA-3) ------------------------------------------- #

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def correct(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.matched)

    @property
    def missing(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.missing)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.accuracy >= PASS_BAR

    # -- citation pages (QA-4's page component) -------------------------- #

    @property
    def pages_scored(self) -> int:
        return sum(1 for o in self.outcomes if o.page_matched is not None)

    @property
    def pages_correct(self) -> int:
        return sum(1 for o in self.outcomes if o.page_matched is True)

    @property
    def page_accuracy(self) -> float | None:
        return self.pages_correct / self.pages_scored if self.pages_scored else None

    # -- breakdowns ------------------------------------------------------- #

    def by_treaty(self) -> dict[str, tuple[int, int]]:
        rows: dict[str, tuple[int, int]] = {}
        for outcome in self.outcomes:
            correct, total = rows.get(outcome.treaty_id, (0, 0))
            rows[outcome.treaty_id] = (correct + int(outcome.matched), total + 1)
        return dict(sorted(rows.items()))

    def by_source(self) -> dict[str, tuple[int, int]]:
        """Split text-layer from transcription reads.

        FR-ENDORSE-3 badges them differently in the UI, so they are reported
        differently here too: a model that reads clean text well and scanned
        pages poorly has a very different weakness from one that is uniformly
        mediocre.
        """
        rows: dict[str, tuple[int, int]] = {}
        for outcome in self.outcomes:
            correct, total = rows.get(outcome.source, (0, 0))
            rows[outcome.source] = (correct + int(outcome.matched), total + 1)
        return dict(sorted(rows.items()))

    def failures(self) -> list[FieldOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.matched]


def load_ground_truth(path: Path | str) -> list[dict[str, Any]]:
    """Load the answer key written by `build_wordings.build_all`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("fields", []))
    return list(payload)


def score_extraction(
    ground_truth: Iterable[Mapping[str, Any]],
    extracted: Mapping[str, Mapping[str, Any]],
    *,
    pages: Mapping[str, Mapping[str, int]] | None = None,
    only_treaties: Sequence[str] | None = None,
) -> AccuracyReport:
    """Score `extracted` against the answer key.

    `extracted` is `{treaty_id: {field: value}}`; `pages` is the optional
    `{treaty_id: {field: page}}` the extractor cited. A field present in the
    key but absent from the extraction counts as **wrong, not skipped** -
    silently omitting the hard fields would otherwise be the easiest way to a
    high score.
    """
    wanted = set(only_treaties) if only_treaties else None
    report = AccuracyReport()

    for row in ground_truth:
        treaty_id = row["treaty_id"]
        if wanted is not None and treaty_id not in wanted:
            continue
        name = row["field"]
        treaty_fields = extracted.get(treaty_id, {})
        present = name in treaty_fields
        actual = treaty_fields.get(name)
        actual_page = (pages or {}).get(treaty_id, {}).get(name)

        report.outcomes.append(
            FieldOutcome(
                treaty_id=treaty_id,
                field=name,
                expected=row.get("expected_value"),
                actual=actual,
                matched=present and values_match(row.get("expected_value"), actual),
                expected_page=row.get("page"),
                actual_page=actual_page,
                source=row.get("source", "text"),
                missing=not present,
            )
        )
    return report


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def format_report(report: AccuracyReport, *, max_failures: int = 15) -> str:
    """A plain-text summary for RESULTS.md and the console.

    Failures are listed, not just counted. QA-4 requires known misses to be
    reported, and a bare percentage invites nobody to look at them.
    """
    lines = [
        "QA-3 / B3 - extraction accuracy",
        "=" * 46,
        f"fields scored      {report.total}",
        f"correct            {report.correct}",
        f"missing            {report.missing}",
        f"accuracy           {report.accuracy:.1%}  (bar {PASS_BAR:.0%})",
        f"result             {'PASS' if report.passed else 'FAIL'}",
    ]
    if report.page_accuracy is not None:
        lines.append(
            f"citation pages     {report.pages_correct}/{report.pages_scored} "
            f"= {report.page_accuracy:.1%}"
        )
        # Accuracy over offered citations flatters an extractor that cites
        # only the easy fields, so coverage is reported beside it. C-7 wants
        # every claim cited, and these are different failures.
        coverage = report.pages_scored / report.total if report.total else 0.0
        lines.append(
            f"citation coverage  {report.pages_scored}/{report.total} "
            f"= {coverage:.1%}  (fields carrying any citation)"
        )
    else:
        lines.append("citation pages     not reported by the extractor")

    lines.append("")
    lines.append("by treaty")
    for treaty_id, (correct, total) in report.by_treaty().items():
        share = correct / total if total else 0.0
        lines.append(f"  {treaty_id:<10} {correct:>3}/{total:<3} {share:>6.1%}")

    by_source = report.by_source()
    if len(by_source) > 1:
        lines.append("")
        lines.append("by source")
        for source, (correct, total) in by_source.items():
            share = correct / total if total else 0.0
            lines.append(f"  {source:<14} {correct:>3}/{total:<3} {share:>6.1%}")

    failures = report.failures()
    if failures:
        lines.append("")
        lines.append(f"failures ({len(failures)})")
        for outcome in failures[:max_failures]:
            reason = "absent" if outcome.missing else f"got {outcome.actual!r}"
            lines.append(
                f"  {outcome.treaty_id} {outcome.field:<28} "
                f"expected {outcome.expected!r}, {reason}"
            )
        if len(failures) > max_failures:
            lines.append(f"  ... and {len(failures) - max_failures} more")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: python -m qa.extraction_accuracy --truth ... --extracted ...

    Exits 1 when accuracy is below the bar, so it can gate a checkpoint.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Score extraction accuracy (QA-3).")
    parser.add_argument(
        "--truth",
        default="data/synthetic/wordings/ground_truth.json",
        help="answer key written by build_wordings",
    )
    parser.add_argument(
        "--extracted",
        required=True,
        help='JSON: {"treaty_id": {"field": value}}, optionally with a "pages" sibling',
    )
    parser.add_argument("--only", action="append", help="treaty_id; repeatable")
    args = parser.parse_args(argv)

    truth = load_ground_truth(args.truth)
    payload = json.loads(Path(args.extracted).read_text(encoding="utf-8"))
    extracted = payload.get("extracted", payload)
    pages = payload.get("pages")

    report = score_extraction(truth, extracted, pages=pages, only_treaties=args.only)
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
