"""API-1..5, FR-MATCH and FR-GUARD — the deployable spine.

No model calls anywhere in this file, because there are none in the code it
tests. That is the point of building this layer first: the figures a reinsurer
would be fired for getting wrong come from arithmetic, and they are
demonstrable before any agent exists.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.analysis import (
    EventNotFound,
    analyse,
    available_events,
    load_event,
    match_treaties,
    stream_analysis,
)
from app.config import LOCAL_ORIGIN, Settings, load_settings
from app.main import API_VERSION, create_app
from ingest.seed_portfolio import build_portfolio


@pytest.fixture(scope="module")
def portfolio():
    return build_portfolio()


@pytest.fixture(scope="module")
def client(portfolio):
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "test-project"}))
    api.state.portfolio = portfolio
    return TestClient(api)


def _frames(response_lines) -> list[dict]:
    out = []
    for line in response_lines:
        if line.strip().startswith("data: "):
            out.append(json.loads(line[len("data: ") :]))
    return out


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_the_location_defaults_to_global_not_the_data_region():
    """Gemini 3.x is not served from us-central1, where Cloud Run, Firestore
    and GCS live. Defaulting to the data region fails on the first call."""
    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p"})
    assert config.location == "global"
    assert config.configured


def test_an_unset_project_warns_but_still_boots():
    """`/healthz` has to answer so a bad deploy can be diagnosed. "Up but
    unconfigured" is more useful than a container that will not start."""
    config = load_settings({})
    assert not config.configured
    assert any("GOOGLE_CLOUD_PROJECT" in w for w in config.warnings)


def test_a_leftover_placeholder_is_rejected_rather_than_used():
    """`.env.example` ships `<GCP_PROJECT_ID>-docs`. Copied without editing,
    a literal "<...>" bucket name would fail at the first upload with an
    obscure error instead of at startup with a clear one."""
    config = load_settings(
        {
            "GOOGLE_CLOUD_PROJECT": "p",
            "GCS_BUCKET": "<GCP_PROJECT_ID>-docs",
            "ALLOWED_ORIGINS": "https://<GCP_PROJECT_ID>.web.app,https://real.example",
        }
    )
    assert config.gcs_bucket is None
    assert any("GCS_BUCKET" in w for w in config.warnings)
    assert "https://real.example" in config.allowed_origins
    assert not any("<" in origin for origin in config.allowed_origins)


def test_the_local_dev_origin_is_always_allowed():
    """So a developer can run the frontend without setting ALLOWED_ORIGINS,
    while a wildcard is never used - the API is not public."""
    assert LOCAL_ORIGIN in load_settings({}).allowed_origins
    config = load_settings({"ALLOWED_ORIGINS": "https://a.example"})
    assert config.allowed_origins == ("https://a.example", LOCAL_ORIGIN)


def test_origins_are_deduplicated_and_ordered():
    config = load_settings({"ALLOWED_ORIGINS": f"https://a.example, {LOCAL_ORIGIN} ,https://a.example"})
    assert config.allowed_origins == ("https://a.example", LOCAL_ORIGIN)


def test_model_dev_is_announced_loudly_rather_than_used_silently():
    """Project rule: MODEL_MAIN is always the production model and MODEL_DEV is
    explicit opt-in. A prompt tuned on a model production never uses drifts,
    so its presence must be visible in /healthz."""
    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "MODEL_DEV": "gemini-3.1-flash-lite"})
    assert config.model_main == "gemini-3.5-flash-lite"
    assert any("MODEL_DEV" in w for w in config.warnings)


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("false", False), ("", True), (None, True)],
)
def test_feature_flags_parse_the_forms_people_actually_write(raw, expected):
    env = {"GOOGLE_CLOUD_PROJECT": "p"}
    if raw is not None:
        env["COURTROOM_ENABLED"] = raw
    assert load_settings(env).courtroom_enabled is expected


def test_a_non_numeric_integer_falls_back_rather_than_crashing():
    """A typo in an env var must not stop the service booting."""
    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DAILY_ANALYSIS_CAP": "lots"})
    assert config.daily_analysis_cap == 300


def test_loading_settings_does_not_leak_into_the_real_environment():
    import os

    before = dict(os.environ)
    load_settings({"GOOGLE_CLOUD_PROJECT": "throwaway"})
    assert dict(os.environ) == before


# --------------------------------------------------------------------------- #
# FR-MATCH
# --------------------------------------------------------------------------- #


def test_as_if_is_the_default_and_skips_the_period_test(portfolio):
    """FR-MATCH: "only if as_if=false, inception <= event.start <= expiry",
    and replay defaults to as_if=true - a historical event on the current
    book, which is standard practice."""
    event = load_event("jebi-2018")
    as_if = match_treaties(portfolio, event, as_if=True)
    literal = match_treaties(portfolio, event, as_if=False)

    assert sum(1 for d in as_if if d.matched) == 13
    # The book runs 2025-2027 and Jebi is 2018, so a literal period test
    # excludes everything. This is why as-if has to be the default.
    assert sum(1 for d in literal if d.matched) == 0
    assert all("outside the period" in d.reason for d in literal if not d.matched and "peril" not in d.reason and "territory" not in d.reason)


def test_a_wrong_peril_is_excluded_with_a_reason(portfolio):
    """An analyst's first question about a programme that did not respond is
    "why not", and "it was not in the list" is not an answer."""
    quake = load_event("noto-2024")
    decisions = match_treaties(portfolio, quake)
    wind_only = [d for d in decisions if "not a covered peril" in d.reason]
    assert wind_only
    assert all("EQ is not a covered peril" in d.reason for d in wind_only)


def test_a_philippine_treaty_does_not_respond_to_a_japanese_event(portfolio):
    """The failure the unbounded ShakeMap grid would have caused: FR-MATCH
    keys off event.regions, so a Japanese quake must never reach a PHL book."""
    decisions = match_treaties(portfolio, load_event("noto-2024"))
    philippine = [
        d
        for d in decisions
        if portfolio.treaty(d.treaty_id).territory.get("include") == ("PHL",)
    ]
    assert philippine
    assert not any(d.matched for d in philippine)


def test_every_decision_carries_a_reason(portfolio):
    for decision in match_treaties(portfolio, load_event("jebi-2018")):
        assert decision.reason


def test_a_territorial_carve_out_reads_as_an_exclusion_not_as_no_exposure(portfolio):
    """W3 excludes Okinawa. If every affected region were carved out, the
    reason must say so - "no exposure" would send an analyst looking in the
    wrong place."""
    event = {
        "event_id": "synthetic",
        "name": "Okinawa-only storm",
        "peril": "WS",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-01T09:00:00Z",
        "regions": [
            {"code": "JP-47", "country": "JPN", "intensity": {"wind_ms": 50.0}, "band": 4}
        ],
    }
    decisions = match_treaties(portfolio, event)
    carved = [d for d in decisions if "territorially excluded" in d.reason]
    assert carved, "expected at least one treaty excluding JP-47"
    assert all("JP-47" in d.reason for d in carved)


def test_a_region_sampled_at_zero_intensity_is_not_affected(portfolio):
    """Event files list regions for completeness. A region with no wind is in
    the file but is not in the loss."""
    event = {
        "event_id": "synthetic",
        "name": "Nothing happened",
        "peril": "WS",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-01T09:00:00Z",
        "regions": [
            {"code": "JP-13", "country": "JPN", "intensity": {"wind_ms": 0.0}, "band": 0}
        ],
    }
    assert not any(d.matched for d in match_treaties(portfolio, event))


# --------------------------------------------------------------------------- #
# The money moment
# --------------------------------------------------------------------------- #


def test_the_live_jebi_analysis_reproduces_the_money_moment(portfolio):
    """The demo's hero number, through the same code path the API serves.

    Not a restatement of the engine test: this runs the committed event file,
    the committed portfolio and the real vulnerability curves, which is what
    a judge sees. The engine's own acceptance test feeds it a literal 54.4.
    """
    result = analyse("jebi-2018", portfolio=portfolio)
    sakura = next(o for o in result.outcomes if o.treaty_id == "T-001")

    assert float(sakura.gross) == pytest.approx(54.3, abs=0.2)

    layers = {lr.layer_no: lr for lr in sakura.cat_xl.layers}
    assert layers[1].ceded == Decimal("20.000000") and layers[1].exhausted
    assert Decimal("24") < layers[2].ceded < Decimal("25")
    assert not layers[2].exhausted
    assert layers[3].ceded == Decimal("0.000000")

    # The three-party view, against MONEY_MOMENT section 4.4.
    assert float(sakura.cat_xl.our_net) == pytest.approx(6.82, abs=0.02)
    assert float(sakura.cat_xl.cedent_retention) == pytest.approx(10.0, abs=0.01)
    assert float(sakura.cat_xl.cedent_net_cost) == pytest.approx(13.22, abs=0.02)
    assert float(sakura.cat_xl.market_net) == pytest.approx(41.18, abs=0.15)


def test_the_hero_programme_burns_partially_which_is_what_makes_the_split_matter(portfolio):
    """Guards the recalibration. At the previous TSI_PER_WEIGHT the modelled
    gross was 239.55, which exhausts all three layers - and once a programme
    is exhausted, splitting one occurrence into two changes nothing, so the
    money moment has nothing to show."""
    sakura = next(
        o for o in analyse("jebi-2018", portfolio=portfolio).outcomes
        if o.treaty_id == "T-001"
    )
    burns = [lr.burn for lr in sakura.cat_xl.layers]
    assert burns[0] == Decimal(1), "L1 should be exhausted"
    assert 0 < burns[1] < 1, "L2 must be PARTLY burnt for the split to matter"
    assert burns[2] == 0, "L3 should be untouched"


def test_outcomes_are_ordered_by_our_net_exposure(portfolio):
    """The first question is "where are we most on the hook", not "which
    treaty id sorts first"."""
    nets = [o.our_net for o in analyse("jebi-2018", portfolio=portfolio).outcomes]
    assert nets == sorted(nets, reverse=True)


def test_a_quota_share_is_priced_proportionally(portfolio):
    result = analyse("jebi-2018", portfolio=portfolio)
    shares = [o for o in result.outcomes if o.type == "QS"]
    for outcome in shares:
        assert outcome.quota_share is not None
        assert outcome.cat_xl is None
        assert outcome.our_net == outcome.quota_share.our_loss


def test_an_earthquake_uses_mmi_not_wind(portfolio):
    """The damage ratio is selected by peril. Reading wind_ms for a quake
    would silently produce zero loss everywhere."""
    result = analyse("noto-2024", portfolio=portfolio)
    assert result.matched > 0
    assert result.gross_total > 0


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


def test_the_catalogue_lists_every_replay_in_date_order():
    catalogue = available_events()
    assert [row["event_id"] for row in catalogue] == [
        "haiyan-2013",
        "jebi-2018",
        "hagibis-2019",
        "noto-2024",
    ]
    jebi = next(row for row in catalogue if row["event_id"] == "jebi-2018")
    assert jebi["peril"] == "WS"
    assert jebi["countries"] == ["JPN"]
    assert jebi["regions"] == 34


def test_an_unknown_event_raises_rather_than_returning_empty():
    with pytest.raises(EventNotFound):
        load_event("not-an-event")


# --------------------------------------------------------------------------- #
# SSE — API-4
# --------------------------------------------------------------------------- #


def test_the_stream_emits_the_documented_frame_sequence(portfolio):
    frames = _frames(stream_analysis("jebi-2018", portfolio=portfolio))
    kinds = [f["type"] for f in frames]
    assert kinds[0] == "stage"
    assert kinds[-1] == "done"
    assert "error" not in kinds
    assert [f["key"] for f in frames if f["type"] == "result"] == ["event", "impact"]
    tool = next(f for f in frames if f["type"] == "tool")
    assert tool["name"] == "match_treaties"
    assert "matched" in tool["summary"]


def test_every_frame_is_a_single_well_formed_sse_event(portfolio):
    for chunk in stream_analysis("jebi-2018", portfolio=portfolio):
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        assert chunk.count("\n\n") == 1
        json.loads(chunk[len("data: ") :])


def test_a_missing_event_streams_an_error_frame_not_a_broken_stream():
    """A half-finished SSE stream looks like a hung browser."""
    frames = _frames(stream_analysis("not-an-event"))
    assert frames[-1]["type"] == "error"
    assert frames[-1]["retryable"] is False


def test_an_unexpected_failure_is_reported_as_retryable(portfolio, monkeypatch):
    import app.analysis as module

    def explode(*args, **kwargs):
        raise RuntimeError("firestore fell over")

    monkeypatch.setattr(module, "analyse", explode)
    frames = _frames(module.stream_analysis("jebi-2018", portfolio=portfolio))
    assert frames[-1]["type"] == "error"
    assert frames[-1]["retryable"] is True
    assert "firestore fell over" in frames[-1]["message"]


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def test_healthz_reports_enough_to_diagnose_a_deploy(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["version"] == API_VERSION
    assert body["configured"] is True
    assert body["location"] == "global"
    assert body["models"]["embed_dim"] == 768
    assert "courtroom" in body["features"]


def test_the_events_endpoint(client):
    body = client.get("/api/events").json()
    assert len(body["events"]) == 4


def test_the_treaty_list_and_detail(client):
    listing = client.get("/api/treaties").json()["treaties"]
    assert len(listing) == 24
    assert any(row["wording_id"] == "W1" for row in listing)

    detail = client.get("/api/treaties/T-001").json()
    assert detail["cedent"] == "Sakura General Insurance"
    assert [la["layer_no"] for la in detail["layers"]] == [1, 2, 3]
    assert detail["layers"][0]["retention"] == 10.0
    assert detail["layers"][0]["limit"] == 20.0


def test_an_unknown_treaty_is_a_404(client):
    assert client.get("/api/treaties/T-999").status_code == 404


def test_posting_an_analysis_streams_the_impact(client):
    with client.stream(
        "POST", "/api/analyses", json={"mode": "replay", "event_id": "jebi-2018"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        # Cloud Run buffers without this, turning a stream into one late block.
        assert response.headers["x-accel-buffering"] == "no"
        frames = _frames(response.iter_lines())

    impact = next(f for f in frames if f.get("key") == "impact")
    assert impact["data"]["totals"]["treaties_matched"] == 13
    assert impact["data"]["as_if"] is True
    assert impact["data"]["excluded"]


def test_the_default_event_is_the_hero_demo(client):
    """UI-1's primary button is "Run demo: Typhoon Jebi 2018", so an empty
    body must produce exactly that."""
    with client.stream("POST", "/api/analyses", json={}) as response:
        frames = _frames(response.iter_lines())
    event = next(f for f in frames if f.get("key") == "event")
    assert event["data"]["event_id"] == "jebi-2018"


def test_live_mode_says_it_is_not_implemented_rather_than_failing_oddly(client):
    response = client.post("/api/analyses", json={"mode": "live", "event_query": "typhoon"})
    assert response.status_code == 501
    assert "replay" in response.json()["detail"]


def test_an_over_long_live_query_is_rejected_by_the_schema(client):
    """FR-GUARD: live query length <= 300 characters."""
    response = client.post("/api/analyses", json={"mode": "live", "event_query": "x" * 301})
    assert response.status_code == 422


def test_an_unknown_mode_is_rejected(client):
    assert client.post("/api/analyses", json={"mode": "wishful"}).status_code == 422


def test_api5_returns_the_full_document(client):
    body = client.get("/api/analyses/replay-jebi-2018").json()
    assert body["analysis_id"] == "replay-jebi-2018"
    assert body["event"]["name"] == "Typhoon Jebi"
    assert body["totals"]["treaties_matched"] == 13


def test_api5_rejects_an_id_it_cannot_recompute(client):
    assert client.get("/api/analyses/live-12345").status_code == 404
    assert client.get("/api/analyses/replay-nope").status_code == 404


# --------------------------------------------------------------------------- #
# FR-GUARD
# --------------------------------------------------------------------------- #


def test_the_hourly_limit_explains_itself_and_offers_a_cached_result(portfolio, tmp_path):
    """FR-GUARD-5: never a bare 429. Say what happened, when it resets, and
    whether a recorded replay can be offered instead - here there is none."""
    api = create_app(
        load_settings({"GOOGLE_CLOUD_PROJECT": "p", "RATE_LIMIT_PER_HOUR": "2",
                       "REPLAY_FIXTURE_DIR": str(tmp_path)})
    )
    api.state.portfolio = portfolio
    limited = TestClient(api)

    for _ in range(2):
        with limited.stream("POST", "/api/analyses", json={}) as response:
            assert response.status_code == 200
            list(response.iter_lines())

    blocked = limited.post("/api/analyses", json={})
    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert "2 analyses in the last hour" in detail["message"]
    assert detail["cached_available"] is False


def test_the_daily_cap_is_separate_from_the_per_ip_limit(portfolio):
    """A single visitor must not be able to exhaust the day's budget, and the
    cap must bite even when no IP has hit its hourly limit."""
    api = create_app(
        load_settings(
            {
                "GOOGLE_CLOUD_PROJECT": "p",
                "RATE_LIMIT_PER_HOUR": "100",
                "DAILY_ANALYSIS_CAP": "1",
            }
        )
    )
    api.state.portfolio = portfolio
    capped = TestClient(api)

    with capped.stream("POST", "/api/analyses", json={}) as response:
        list(response.iter_lines())
    blocked = capped.post("/api/analyses", json={})
    assert blocked.status_code == 429
    assert "daily analysis cap" in blocked.json()["detail"]["message"]


def test_the_limiter_forgets_requests_older_than_their_window(portfolio):
    from app.main import _RateLimiter

    limiter = _RateLimiter(per_hour=1, daily_cap=10)
    assert limiter.check("1.2.3.4", now=0.0)[0]
    assert not limiter.check("1.2.3.4", now=10.0)[0]
    # An hour and a second later the window has rolled.
    assert limiter.check("1.2.3.4", now=3_601.0)[0]


def test_the_limiter_is_per_ip():
    from app.main import _RateLimiter

    limiter = _RateLimiter(per_hour=1, daily_cap=10)
    assert limiter.check("1.1.1.1", now=0.0)[0]
    assert limiter.check("2.2.2.2", now=0.0)[0]


def test_the_daily_window_rolls_too():
    from app.main import _RateLimiter

    limiter = _RateLimiter(per_hour=100, daily_cap=1)
    assert limiter.check("1.1.1.1", now=0.0)[0]
    assert not limiter.check("1.1.1.1", now=100.0)[0]
    assert limiter.check("1.1.1.1", now=86_401.0)[0]


def test_a_zero_hourly_limit_refuses_with_a_message_rather_than_crashing():
    from app.main import _RateLimiter

    allowed, message = _RateLimiter(per_hour=0, daily_cap=10).check("1.1.1.1", now=0.0)
    assert not allowed
    assert "replay" in message


def test_cors_lists_the_hosting_origins_explicitly(portfolio):
    """C-10: the browser calls Cloud Run directly, so there is no same-origin
    fallback. A wildcard is never used."""
    api = create_app(
        load_settings(
            {
                "GOOGLE_CLOUD_PROJECT": "p",
                "ALLOWED_ORIGINS": "https://techno-crackers-catsight.web.app",
            }
        )
    )
    api.state.portfolio = portfolio
    cors = TestClient(api)
    response = cors.get(
        "/healthz", headers={"Origin": "https://techno-crackers-catsight.web.app"}
    )
    allowed = response.headers["access-control-allow-origin"]
    assert allowed == "https://techno-crackers-catsight.web.app"
    assert allowed != "*"


def test_settings_is_a_frozen_dataclass():
    """Configuration must not drift at runtime."""
    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p"})
    assert isinstance(config, Settings)
    with pytest.raises(Exception):
        config.project = "something-else"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Edge shapes
# --------------------------------------------------------------------------- #


def test_a_region_missing_the_perils_intensity_key_is_skipped():
    """An event file carrying `mmi` for a windstorm, or vice versa, must not
    crash the pricing - the region simply contributes no damage."""
    from app.analysis import _damage_ratios
    from catsight_agent.tools.vulnerability import VulnerabilityModel

    event = {
        "peril": "WS",
        "regions": [
            {"code": "JP-13", "country": "JPN", "intensity": {"mmi": 6.0}},
            {"code": "JP-27", "country": "JPN", "intensity": {"wind_ms": 40.0}},
        ],
    }
    ratios = _damage_ratios(event, VulnerabilityModel.load())
    assert "JP-13" not in ratios
    assert ratios["JP-27"] > 0


def test_an_outcome_with_no_priced_result_is_zero_rather_than_an_error():
    """A matched treaty that is neither a layered Cat XL nor a quota share -
    a structure the generator does not currently produce. Returning zero
    keeps a portfolio total addable; raising would lose the other 12 treaties
    because of one malformed record."""
    from app.analysis import TreatyOutcome

    outcome = TreatyOutcome(
        treaty_id="T-000",
        cedent_id="C-X",
        cedent_name="Structureless Re",
        type="CAT_XL",
        gross=Decimal("10"),
        regions=("JP-13",),
    )
    assert outcome.our_net == Decimal(0)
    assert outcome.ceded == Decimal(0)
    payload = outcome.to_json()
    assert payload["our_net"] == "0.00"
    assert "layers" not in payload


def test_a_cat_xl_with_no_layers_is_matched_but_prices_to_nothing(portfolio):
    """The `elif treaty.qs` false branch. Guards against a half-built treaty
    silently contributing a wrong number instead of an obvious zero."""
    import dataclasses

    from app.analysis import analyse

    broken = dataclasses.replace(portfolio.treaty("T-001"), layers=(), qs=None)
    patched = dataclasses.replace(
        portfolio,
        treaties=tuple(
            broken if t.treaty_id == "T-001" else t for t in portfolio.treaties
        ),
    )
    result = analyse("jebi-2018", portfolio=patched)
    outcome = next(o for o in result.outcomes if o.treaty_id == "T-001")
    assert outcome.cat_xl is None and outcome.quota_share is None
    assert outcome.our_net == Decimal(0)
    assert outcome.gross > 0, "the gross is still computed and reported"


def test_the_app_reads_the_seeded_book_and_never_the_generator(monkeypatch):
    """Production path: the book comes from the store (local JSON here,
    Firestore in the cloud), read once and cached. The generator must not run
    at request time - that is what kept treaty terms in code."""
    import ingest.seed_portfolio as seed

    def forbidden(*a, **k):
        raise AssertionError("the runtime must not call the generator")

    monkeypatch.setattr(seed, "build_portfolio", forbidden)
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}))
    standalone = TestClient(api)
    first = standalone.get("/api/treaties").json()["treaties"]
    assert len(first) == 24
    cached = api.state.store.portfolio()
    standalone.get("/api/treaties")
    assert api.state.store.portfolio() is cached, "the book must be read once"


def test_the_committed_book_matches_the_seed_generator():
    """The seeded book is a build artifact. If the generator changes, the
    seed must be re-run - this fails until it is."""
    from catsight_agent.store import LocalStore
    from ingest.seed_portfolio import build_portfolio

    stored, generated = LocalStore("data").portfolio(), build_portfolio()
    # The store orders by id so local and Firestore reads agree.
    assert stored.cedents == tuple(sorted(generated.cedents, key=lambda c: c.cedent_id))
    assert stored.treaties == tuple(sorted(generated.treaties, key=lambda t: t.treaty_id))
    assert stored.exposures == tuple(sorted(generated.exposures, key=lambda e: e.exposure_id))


def test_an_unseeded_book_is_a_clear_503(tmp_path):
    from catsight_agent.store import LocalStore

    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=LocalStore(tmp_path))
    response = TestClient(api).get("/api/treaties")
    assert response.status_code == 503
    assert "seed_portfolio" in response.json()["detail"]


def test_methodology_endpoint_and_analysis_stamp(client):
    method = client.get("/api/methodology").json()
    assert method["version"] == "2026.1"
    assert "_comment" not in method
    assert "reinstatement_premium" in method["conventions"]
    assert method["vulnerability"]["wind"]["function"] == "emanuel_2011"

    analysis = client.get("/api/analyses/replay-jebi-2018").json()
    assert analysis["methodology"] == {"version": "2026.1", "effective_from": "2026-10-01"}


def test_treaty_detail_carries_its_reconciliation(client):
    detail = client.get("/api/treaties/T-001").json()
    assert "reconciliation" in detail


# --------------------------------------------------------------------------- #
# Serving the SPA from the same service
# --------------------------------------------------------------------------- #


@pytest.fixture
def spa(tmp_path, portfolio, monkeypatch):
    """An app serving a minimal build, so these tests do not depend on
    `frontend/dist` having been built."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>CatSight</title><div id='root'></div>", encoding="utf-8"
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    # A file OUTSIDE the build directory, which must never be reachable.
    (tmp_path / "secret.env").write_text("ADMIN_TOKEN=do-not-serve", encoding="utf-8")

    monkeypatch.setenv("STATIC_DIR", str(dist))
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p", "STATIC_DIR": str(dist)}))
    api.state.portfolio = portfolio
    return TestClient(api)


def test_the_api_serves_the_spa_shell_at_the_root(spa):
    response = spa.get("/")
    assert response.status_code == 200
    assert "CatSight" in response.text


def test_a_client_side_route_serves_the_shell_rather_than_404(spa):
    """Refreshing on a client route must not 404. `StaticFiles(html=True)`
    alone falls back only for directory paths, which is the classic SPA bug,
    and `firebase.json` configures the same rewrite - so behaviour must not
    depend on where this is hosted."""
    response = spa.get("/analysis/replay-jebi-2018")
    assert response.status_code == 200
    assert "CatSight" in response.text


def test_a_real_file_is_served_in_preference_to_the_shell(spa):
    assert spa.get("/favicon.svg").text == "<svg/>"
    assert spa.get("/assets/index-abc123.js").status_code == 200


def test_the_api_routes_still_win_over_the_catch_all(spa):
    """The mount is registered last on purpose. If it shadowed the API the
    whole product would return HTML."""
    assert spa.get("/api/events").status_code == 200
    assert spa.get("/healthz").json()["status"] == "ok"
    assert spa.get("/api/treaties/T-999").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.env",
        "/../../secret.env",
        "/..%2f..%2fsecret.env",
        "/%2e%2e/secret.env",
        "/....//....//secret.env",
    ],
)
def test_traversal_cannot_escape_the_build_directory(spa, path):
    """Without the resolve-and-prefix check this would serve any file on the
    container, including backend/.env."""
    response = spa.get(path)
    assert "ADMIN_TOKEN" not in response.text
    assert "do-not-serve" not in response.text


def test_healthz_reports_whether_the_ui_is_being_served(spa, client):
    """A blank page with a working API is otherwise indistinguishable from a
    broken deploy."""
    assert spa.get("/healthz").json()["frontend"] is True
    # `client` has no STATIC_DIR and no build beside it in the test env.
    assert "frontend" in client.get("/healthz").json()


def test_without_a_build_the_api_still_serves(portfolio, monkeypatch, tmp_path):
    """Developers run `uvicorn app.main:app` with no frontend built. That must
    not break the API."""
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "nonexistent"))
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}))
    api.state.portfolio = portfolio
    bare = TestClient(api)
    assert bare.get("/healthz").json()["frontend"] is False
    assert bare.get("/api/events").status_code == 200
    assert bare.get("/").status_code == 404


def test_a_build_with_no_assets_directory_still_serves(tmp_path, portfolio, monkeypatch):
    """A single-file build - everything inlined into index.html - has no
    `assets/`. Mounting a directory that does not exist raises at startup, so
    the mount has to be conditional."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>CatSight</title>", encoding="utf-8")

    monkeypatch.setenv("STATIC_DIR", str(dist))
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}))
    api.state.portfolio = portfolio
    inlined = TestClient(api)

    assert inlined.get("/healthz").json()["frontend"] is True
    assert "CatSight" in inlined.get("/").text
    assert inlined.get("/assets/anything.js").status_code == 200  # falls back to the shell


def test_knowledge_base_endpoint_totals(tmp_path):
    import shutil

    from catsight_agent.store import LocalStore

    shutil.copytree("data", tmp_path / "data", ignore=shutil.ignore_patterns("synthetic", "raw"))
    (tmp_path / "data" / "extracted" / "ingestions.json").write_text(json.dumps({
        "T-001": {"treaty_id": "T-001", "clauses": 31, "citations_verified": 23,
                  "citations_total": 23, "retrieval_hits": 23, "retrieval_total": 23},
        "T-004": {"treaty_id": "T-004", "clauses": 33, "citations_verified": 26,
                  "citations_total": 27, "retrieval_hits": 28, "retrieval_total": 28},
    }), encoding="utf-8")
    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}),
                     store=LocalStore(tmp_path / "data"))
    body = TestClient(api).get("/api/knowledge-base").json()
    assert [w["treaty_id"] for w in body["wordings"]] == ["T-001", "T-004"]
    assert body["totals"] == {"wordings": 2, "clauses": 64, "citations_verified": 49,
                              "citations_total": 50, "retrieval_hits": 51, "retrieval_total": 51}


def test_agent_analysis_through_the_api_streams_the_graph():
    """API-4 with agents: the real ADK graph behind the endpoint, fake model."""
    from catsight_agent.agents import AgentDeps
    from catsight_agent.store import LocalStore
    from catsight_agent.tools.retrieval import DeterministicEmbedder
    from tests.test_agents import VECTORS, FakeGemini

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "firestore"})
    api = create_app(config, store=LocalStore("data", today="2026-10-10"))
    from app.runs import MemoryRunStore

    api.state.runs = MemoryRunStore()
    api.state.make_deps = lambda emit: AgentDeps(
        client=FakeGemini(), model_main="m", model_reason="r",
        embedder=DeterministicEmbedder(), vectors=VECTORS, emit=emit)
    with TestClient(api) as live:  # runs startup, so the book is warmed
        response = live.post("/api/analyses", json={"event_id": "jebi-2018"})
    frames = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    assert {"retrieval", "verification", "report"} <= {f["type"] for f in frames}
    assert frames[-1]["agents"] is True


def test_treaty_clauses_for_the_clause_viewer():
    from catsight_agent.store import LocalStore
    from tests.test_agents import VECTORS

    config = load_settings({"GOOGLE_CLOUD_PROJECT": "p", "DATA_BACKEND": "firestore"})
    api = create_app(config, store=LocalStore("data"))
    api.state.clauses = VECTORS
    live = TestClient(api)
    body = live.get("/api/treaties/T-004/clauses").json()
    transcribed = [c for c in body["clauses"] if c["source"] == "transcription"]
    assert body["treaty_id"] == "T-004" and len(body["clauses"]) > 30
    assert all({"chunk_id", "clause_no", "page", "pages", "text"} <= set(c) for c in body["clauses"])
    assert transcribed == []  # the offline index has no transcription; live Firestore does
    assert live.get("/api/treaties/T-999/clauses").status_code == 404


def test_treaty_clauses_need_firestore(client):
    response = client.get("/api/treaties/T-001/clauses")
    assert response.status_code == 503


def test_agents_requested_without_gcp_is_a_400(client):
    response = client.post("/api/analyses", json={"event_id": "jebi-2018", "agents": True})
    assert response.status_code == 400
    assert "DATA_BACKEND=firestore" in response.json()["detail"]


def test_warming_an_unseeded_book_does_not_crash_start_up(tmp_path):
    from catsight_agent.store import LocalStore

    api = create_app(load_settings({"GOOGLE_CLOUD_PROJECT": "p"}), store=LocalStore(tmp_path))
    with TestClient(api) as live:
        assert live.get("/healthz").status_code == 200
