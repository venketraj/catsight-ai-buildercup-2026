"""Where the runtime reads its data from - the treaty book, events, the
method, and wording reconciliations.

The synthetic generators (`ingest.seed_portfolio`, `ingest.build_events`) run
**once**, as a seed step. The API never calls them: it reads what the seed
wrote, through a `DataStore`. Two implementations share one interface:

  * `LocalStore`      JSON files under `data/`, for development and tests.
  * `FirestoreStore`  Firestore collections, for Cloud Run.

So the cloud deployment reads from GCP services, a local run reads the same
records from disk, and nothing that prices a treaty lives in code. Which one
is used is decided by configuration (`DATA_BACKEND`), never by the code path.

## The book is the record; wordings are reconciled against it

Treaty terms come from the **book** - the structured record a reinsurer's
treaty system holds. The wordings are read by Gemini and *reconciled* against
the book (`ingest.reconcile`): a value the wording states differently is
flagged with a verified citation rather than silently replacing the booked
figure. That keeps a misread number out of the money while still surfacing a
real discrepancy, which is the point of reading the wording at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from ingest.seed_portfolio import Cedent, Exposure, Layer, Portfolio, Treaty

__all__ = [
    "BookNotSeeded",
    "EventNotFound",
    "DataStore",
    "LocalStore",
    "FirestoreStore",
    "portfolio_from_records",
    "event_summary",
    "current_methodology",
]


class EventNotFound(LookupError):
    """No replay record for that event id."""


class BookNotSeeded(RuntimeError):
    """The treaty book has not been written yet. Run the seed step."""


# --------------------------------------------------------------------------- #
# Record conversion - the inverse of seed_portfolio._serialise
# --------------------------------------------------------------------------- #


def _treaty_from_record(raw: Mapping[str, Any]) -> Treaty:
    territory = raw.get("territory") or {}
    return Treaty(
        treaty_id=raw["treaty_id"],
        cedent_id=raw["cedent_id"],
        type=raw["type"],
        perils=tuple(raw.get("perils") or ()),
        territory={
            "include": tuple(territory.get("include") or ()),
            "exclude": tuple(territory.get("exclude") or ()),
        },
        inception=raw["inception"],
        expiry=raw["expiry"],
        currency=raw["currency"],
        hours_clause=dict(raw.get("hours_clause") or {}),
        exclusions=tuple(raw.get("exclusions") or ()),
        layers=tuple(
            Layer(
                layer_no=int(la["layer_no"]),
                retention=float(la["retention"]),
                limit=float(la["limit"]),
                premium=float(la["premium"]),
                our_share=float(la["our_share"]),
                reinstatements=dict(la.get("reinstatements") or {}),
            )
            for la in raw.get("layers") or ()
        ),
        qs=dict(raw["qs"]) if raw.get("qs") else None,
        source_pdf=raw.get("source_pdf"),
        wording_id=raw.get("wording_id"),
        extraction=raw.get("extraction"),
        endorsement=raw.get("endorsement"),
    )


def portfolio_from_records(
    cedents: Iterable[Mapping[str, Any]],
    treaties: Iterable[Mapping[str, Any]],
    exposures: Iterable[Mapping[str, Any]],
) -> Portfolio:
    """Rebuild a `Portfolio` from stored records, in a stable order."""
    return Portfolio(
        cedents=tuple(
            Cedent(c["cedent_id"], c["name"], c["country"], tuple(c.get("lines") or ()))
            for c in sorted(cedents, key=lambda c: c["cedent_id"])
        ),
        treaties=tuple(
            _treaty_from_record(t) for t in sorted(treaties, key=lambda t: t["treaty_id"])
        ),
        exposures=tuple(
            Exposure(
                exposure_id=e["exposure_id"],
                cedent_id=e["cedent_id"],
                region_code=e["region_code"],
                peril=e["peril"],
                tsi_usd=float(e["tsi_usd"]),
                policy_count=int(e["policy_count"]),
                lob=e["lob"],
            )
            for e in sorted(exposures, key=lambda e: e["exposure_id"])
        ),
    )


def event_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """API-2's catalogue row for one event record."""
    regions = payload.get("regions") or []
    return {
        "event_id": payload["event_id"],
        "name": payload["name"],
        "peril": payload["peril"],
        "date": payload["start"][:10],
        "countries": sorted({r.get("country") for r in regions if r.get("country")}),
        "duration_h": payload.get("duration_h"),
        "regions": len(regions),
    }


def current_methodology(versions: Iterable[Mapping[str, Any]], today: str) -> dict[str, Any]:
    """The approved method in force on `today` (ISO date): the approved
    version with the latest `effective_from` not after today."""
    eligible = [
        v for v in versions
        if v.get("status") == "approved" and str(v.get("effective_from", "")) <= today
    ]
    if not eligible:
        raise BookNotSeeded(f"no approved methodology in force on {today}")
    return dict(max(eligible, key=lambda v: (v["effective_from"], v["version"])))


# --------------------------------------------------------------------------- #
# The interface
# --------------------------------------------------------------------------- #


@runtime_checkable
class DataStore(Protocol):
    """What the API and the agents read. Nothing here writes."""

    def portfolio(self) -> Portfolio: ...

    def events(self) -> list[dict[str, Any]]: ...

    def event(self, event_id: str) -> dict[str, Any]: ...

    def methodology(self) -> dict[str, Any]: ...

    def reconciliation(self, treaty_id: str) -> dict[str, Any] | None: ...

    def ingestions(self) -> list[dict[str, Any]]: ...

    def benchmark(self) -> dict[str, Any]: ...


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Local JSON
# --------------------------------------------------------------------------- #


class LocalStore:
    """Reads the seed's JSON output under `data_dir`.

    Layout:
      book/{cedents,treaties,exposures}.json   written by ingest.seed_portfolio
      events/*.json                            written by ingest.build_events
      methodology.json + vulnerability.json    versioned method
      extracted/reconciliation.json            written by ingest.reconcile
    """

    def __init__(self, data_dir: Path | str = "data", *, today: str | None = None) -> None:
        self.data_dir = Path(data_dir)
        self._today = today
        self._portfolio: Portfolio | None = None

    def _read(self, *parts: str) -> Any:
        return json.loads(self.data_dir.joinpath(*parts).read_text(encoding="utf-8"))

    def portfolio(self) -> Portfolio:
        if self._portfolio is None:
            book = self.data_dir / "book"
            if not (book / "treaties.json").exists():
                raise BookNotSeeded(
                    f"no treaty book at {book}. Run: python -m ingest.seed_portfolio --out {book}"
                )
            self._portfolio = portfolio_from_records(
                self._read("book", "cedents.json"),
                self._read("book", "treaties.json"),
                self._read("book", "exposures.json"),
            )
        return self._portfolio

    def events(self) -> list[dict[str, Any]]:
        rows = [
            event_summary(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted((self.data_dir / "events").glob("*.json"))
        ]
        return sorted(rows, key=lambda row: row["date"])

    def event(self, event_id: str) -> dict[str, Any]:
        path = self.data_dir / "events" / f"{event_id}.json"
        # The id arrives from a request: refuse anything that is not a plain
        # file name, so it cannot walk out of the events directory.
        if path.parent != self.data_dir / "events" or not path.exists():
            raise EventNotFound(event_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def methodology(self) -> dict[str, Any]:
        method = current_methodology([self._read("methodology.json")], self._today or _today())
        method["vulnerability"] = self._read(method["vulnerability_file"])
        return method

    def reconciliation(self, treaty_id: str) -> dict[str, Any] | None:
        path = self.data_dir / "extracted" / "reconciliation.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get(treaty_id)

    def ingestions(self) -> list[dict[str, Any]]:
        path = self.data_dir / "extracted" / "ingestions.json"
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [rows[key] for key in sorted(rows)]

    def benchmark(self) -> dict[str, Any]:
        path = self.data_dir / "benchmark.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("_comment", None)
        return data


# --------------------------------------------------------------------------- #
# Firestore
# --------------------------------------------------------------------------- #


class FirestoreStore:
    """Reads the seed's Firestore collections.

    `client` is anything exposing `collection(name).stream()` and
    `collection(name).document(id).get()`, so it is testable with a fake.
    Collections: cedents, treaties, exposures, events, methodology,
    reconciliations. The book is cached per instance - it changes only when
    the seed is re-run, and a new revision picks it up on start.
    """

    def __init__(self, client: Any, *, today: str | None = None) -> None:
        self.client = client
        self._today = today
        self._portfolio: Portfolio | None = None

    def _all(self, name: str) -> list[dict[str, Any]]:
        return [doc.to_dict() for doc in self.client.collection(name).stream()]

    def _one(self, name: str, key: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(name).document(key).get()
        return snapshot.to_dict() if snapshot.exists else None

    def portfolio(self) -> Portfolio:
        if self._portfolio is None:
            treaties = self._all("treaties")
            if not treaties:
                raise BookNotSeeded("Firestore has no treaties. Run: python -m ingest.seed_cloud")
            self._portfolio = portfolio_from_records(
                self._all("cedents"), treaties, self._all("exposures")
            )
        return self._portfolio

    def events(self) -> list[dict[str, Any]]:
        return sorted((event_summary(e) for e in self._all("events")), key=lambda r: r["date"])

    def event(self, event_id: str) -> dict[str, Any]:
        found = self._one("events", event_id) if "/" not in event_id else None
        if found is None:
            raise EventNotFound(event_id)
        return found

    def methodology(self) -> dict[str, Any]:
        # The seed embeds the vulnerability parameters in each version, so a
        # version is self-contained and cannot drift from its curve.
        return current_methodology(self._all("methodology"), self._today or _today())

    def reconciliation(self, treaty_id: str) -> dict[str, Any] | None:
        return self._one("reconciliations", treaty_id)

    def ingestions(self) -> list[dict[str, Any]]:
        return sorted(self._all("ingestions"), key=lambda row: row.get("treaty_id", ""))

    def benchmark(self) -> dict[str, Any]:
        return self._one("benchmark", "current") or {}
