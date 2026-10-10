"""Reconcile what each wording states against the treaty book.

The book is the record the engine prices from (see `catsight_agent.store`).
Gemini reads each wording; this module compares the two field by field and
says, for every term, one of:

  * **match**        book and wording agree, and the wording's value has a
                     verified (or transcribed) citation.
  * **differs**      they disagree, and the wording's value is verified - a
                     real discrepancy an analyst must look at, with the page
                     and quote to check it against.
  * **unverified**   the wording's value has no checkable citation, so no
                     claim is made either way. A discrepancy that cannot be
                     shown on the page is not reported as one.
  * **book_only** / **wording_only**  one side states the term, the other
                     does not.

Nothing here changes the book. A discrepancy is surfaced, never applied: a
misread number must not flow into the money, and a genuine one is a decision
for the underwriter, not for the extractor.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from ingest.ingest_treaty import flatten_payload
from ingest.provenance import SHOWABLE

__all__ = ["normalise_value", "reconcile_treaty", "reconcile_all", "main"]

#: Bookkeeping, not a term.
_SKIP = frozenset({"endorsement.overrides"})


def normalise_value(value: Any) -> Any:
    """A comparable form: numbers as Decimal, lists as sorted casefolded
    tuples, strings casefolded. `20`, `20.0` and `"20.00"` are one value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).normalize()
    if isinstance(value, str):
        try:
            return Decimal(value.strip()).normalize()
        except InvalidOperation:
            return value.strip().casefold()
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(normalise_value(v)) for v in value))
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def reconcile_treaty(
    treaty_id: str,
    booked: Mapping[str, Any],
    wording: Mapping[str, Any],
    provenance: Mapping[str, Mapping[str, Any]] | None,
    *,
    wording_id: str | None = None,
) -> dict[str, Any]:
    """Compare one treaty. `booked` is the book record (serialised Treaty),
    `wording` the flattened extraction, `provenance` its per-field checks."""
    book_fields = flatten_payload(dict(booked))
    provenance = provenance or {}
    names = sorted((set(book_fields) | set(wording)) - _SKIP)

    rows = []
    for name in names:
        in_book, in_wording = name in book_fields, name in wording
        cited = provenance.get(name) or {}
        citation = (
            {k: cited.get(k) for k in ("status", "page", "clause_no", "quote")}
            if cited
            else None
        )
        verified = cited.get("status") in SHOWABLE

        if not in_wording:
            result = "book_only"
        elif not in_book:
            result = "wording_only" if verified else "unverified"
        elif not verified:
            result = "unverified"
        elif normalise_value(book_fields[name]) == normalise_value(wording[name]):
            result = "match"
        else:
            result = "differs"

        rows.append({
            "field": name,
            "booked": _jsonable(book_fields.get(name)),
            "wording": _jsonable(wording.get(name)),
            "result": result,
            "citation": citation,
        })

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    status = (
        "discrepancies" if counts.get("differs")
        else "incomplete" if counts.get("unverified")
        else "reconciled"
    )
    return {
        "treaty_id": treaty_id,
        "wording_id": wording_id,
        "status": status,
        "counts": dict(sorted(counts.items())),
        "fields": rows,
    }


def reconcile_all(
    treaties: Sequence[Mapping[str, Any]],
    extracted: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Reconcile every booked treaty that has an extracted wording."""
    by_id = {t["treaty_id"]: t for t in treaties}
    values = extracted.get("extracted") or {}
    provenance = extracted.get("provenance") or {}
    return {
        treaty_id: reconcile_treaty(
            treaty_id,
            by_id[treaty_id],
            fields,
            provenance.get(treaty_id),
            wording_id=by_id[treaty_id].get("wording_id"),
        )
        for treaty_id, fields in sorted(values.items())
        if treaty_id in by_id
    }


def main(argv: Sequence[str] | None = None) -> int:
    """python -m ingest.reconcile [--book data/book] [--extracted ...] [--out ...]"""
    import argparse

    parser = argparse.ArgumentParser(description="Reconcile wordings against the book.")
    parser.add_argument("--book", default="data/book")
    parser.add_argument("--extracted", default="data/extracted/extracted.json")
    parser.add_argument("--out", default="data/extracted/reconciliation.json")
    args = parser.parse_args(argv)

    treaties = json.loads((Path(args.book) / "treaties.json").read_text(encoding="utf-8"))
    extracted = json.loads(Path(args.extracted).read_text(encoding="utf-8"))
    result = reconcile_all(treaties, extracted)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for treaty_id, row in result.items():
        counts = ", ".join(f"{k} {v}" for k, v in row["counts"].items())
        print(f"  {treaty_id}  {row['status']:<13}  {counts}")
        for field in row["fields"]:
            if field["result"] == "differs":
                cite = field["citation"] or {}
                print(
                    f"      differs  {field['field']}: book {field['booked']!r} vs "
                    f"wording {field['wording']!r} (p.{cite.get('page')}, "
                    f"clause {cite.get('clause_no')})"
                )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
