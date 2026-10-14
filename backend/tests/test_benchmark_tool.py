"""Tests for benchmarks/run_all.py offline functionality (2a-2e)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to sys.path to import benchmarks.run_all
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.run_all import _stats, _usd, courtroom, write, main


def test_stats_and_usd_use_unicode_middle_dot():
    """2.e: Verify that middle dot uses \\u00b7 without mojibake."""
    s = _stats([1.0, 2.0, 3.0])
    assert "\u00b7" in s
    assert "Â·" not in s
    assert s == "p50 2.0 \u00b7 min 1.0 \u00b7 max 3.0 (n=3)"

    u = _usd([0.01, 0.02, 0.03])
    assert "\u00b7" in u
    assert "Â·" not in u
    assert u == "p50 $0.0200 \u00b7 min $0.0100 \u00b7 max $0.0300 (n=3)"


def test_courtroom_records_treaty_id():
    """2.a: Verify courtroom() extracts court['flag']['treaty_id'] as treaty_id."""
    fake_response_data = {
        "skipped": False,
        "reason": None,
        "flag": {"treaty_id": "T-004"},
        "cost_usd": "0.005",
        "unsupported_figures": [],
        "sides": {
            "reinsurer": {"verified": True, "excluded_share": 0.2, "priced": {"money_at_stake": {"our_net": "-1.34"}}},
            "cedent": {"verified": True, "excluded_share": 0.0, "priced": {"money_at_stake": {"our_net": "0.00"}}},
        },
        "money_at_stake": {"our_net": "-1.34"},
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("benchmarks.run_all._post", return_value=mock_resp):
        out = courtroom("http://fake", "run-123")

    assert out["treaty_id"] == "T-004"
    assert out["reinsurer_verified"] is True
    assert out["cedent_verified"] is True


def test_write_formats_live_count_treaty_column_and_summary(tmp_path, monkeypatch):
    """2.a, 2.c, 2.d: write() states live count, Treaty argued column, and Courtrooms that ran."""
    doc_path = tmp_path / "RESULTS.md"
    results_dir = tmp_path / "results"
    doc_path.write_text("Header\n<!-- benchmarks:start -->\nOld\n<!-- benchmarks:end -->\nTail", encoding="utf-8")

    monkeypatch.setattr("benchmarks.run_all.DOC", doc_path)
    monkeypatch.setattr("benchmarks.run_all.RESULTS", results_dir)

    results = {
        "api_url": "http://fake.app",
        "build": "test-build",
        "event_id": "jebi-2018",
        "measured_at": "2026-10-15 02:00 UTC",
        "analyses": [
            {"event_id": "jebi-2018", "money_s": 1.0, "total_s": 10.0, "cost_usd": "0.01", "flags": [{"treaty_id": "T-004", "issue_type": "EXCLUSION", "severity": "HIGH", "status": "verified"}]},
            {"event_id": "jebi-2018", "money_s": 1.1, "total_s": 11.0, "cost_usd": "0.01", "flags": []},
            {"event_id": "jebi-2018", "error": "HTTP 429", "replay": False},  # error analysis
        ],
        "courtrooms": [
            {"treaty_id": "T-004", "cedent_verified": True, "reinsurer_verified": True, "reinsurer_share": 0.2, "money_at_stake": {"our_net": "-1.34"}},
            {"treaty_id": None, "skipped": True, "reason": "rate limit"},
        ],
    }

    write(results)

    content = doc_path.read_text(encoding="utf-8")
    # 2.c: Header states number of live analyses actually used (2, not 3)
    assert "2 live analyses" in content
    # 2.a: Table contains Treaty argued column
    assert "Treaty argued" in content
    assert "| 1 | 10.0 | 0.01 | T-004 EXCLUSION HIGH verified | T-004 |" in content
    # 2.d: Summary line format
    assert "Both sides verified in **1 of 1** Courtrooms that ran." in content
    assert "*Courtrooms not run (1):* Run 2: rate limit" in content


def test_main_aborts_immediately_on_replay_or_error(monkeypatch):
    """2.b: Stop immediately (non-zero exit, nothing written) if replay=True or error."""
    mock_health = MagicMock()
    mock_health.read.return_value = json.dumps({"build": "test"}).encode("utf-8")
    mock_health.__enter__.return_value = mock_health

    write_called = []
    monkeypatch.setattr("benchmarks.run_all.write", lambda res: write_called.append(res))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: mock_health)

    # 1. Replay response triggers SystemExit
    with patch("benchmarks.run_all.analysis", return_value={"event_id": "jebi-2018", "replay": True}):
        with pytest.raises(SystemExit) as excinfo:
            with patch("sys.argv", ["run_all.py", "--api-url", "http://fake"]):
                main()
        assert "served as replay" in str(excinfo.value)

    # 2. Daily cap notice triggers SystemExit
    with patch("benchmarks.run_all.analysis", return_value={"event_id": "jebi-2018", "notice": "The daily analysis cap has been reached"}):
        with pytest.raises(SystemExit) as excinfo:
            with patch("sys.argv", ["run_all.py", "--api-url", "http://fake"]):
                main()
        assert "notice/limit" in str(excinfo.value)

    # 3. Courtroom error triggers SystemExit
    with patch("benchmarks.run_all.analysis", return_value={"event_id": "jebi-2018", "run_id": "run-1"}):
        with patch("benchmarks.run_all.courtroom", return_value={"error": "HTTP 429"}):
            with pytest.raises(SystemExit) as excinfo:
                with patch("sys.argv", ["run_all.py", "--api-url", "http://fake"]):
                    main()
            assert "courtroom 1 returned error: HTTP 429" in str(excinfo.value)

    assert write_called == [], "write() must never be called on an aborted run"
