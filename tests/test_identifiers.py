"""OpenFIGI identifier mapping: job building, batching, parsing, candidate
selection. All offline -- the HTTP layer is stubbed at the provider's client.
"""
from __future__ import annotations

import json

import pytest

from quantlab.config import settings
from quantlab.providers.openfigi import MAPPING_URL, OpenFigiProvider
from quantlab.ratelimit import DEFAULT_LIMITS
from quantlab.store.identifiers import fallback_job_for_symbol, job_for_symbol, select_candidates


@pytest.fixture
def keyless_provider(monkeypatch):
    """An OpenFIGI provider with no API key, its HTTP client stubbed out."""
    monkeypatch.setattr(settings(), "openfigi_api_key", "")
    provider = OpenFigiProvider()
    calls: list[list[dict]] = []

    def fake_post_json(url, payload, **_kw):
        assert url == MAPPING_URL
        calls.append(list(payload))
        return json.dumps([{"data": [{"figi": f"BBG{i:012d}"}]} for i, _ in enumerate(payload)]).encode()

    provider.client.post_json = fake_post_json
    provider.calls = calls
    return provider


# ---------------------------------------------------------------------------
# Job building and candidate selection
# ---------------------------------------------------------------------------


def test_job_for_symbol_maps_exchange_suffixes():
    assert job_for_symbol("SHEL.LON") == {"idType": "TICKER", "idValue": "SHEL", "exchCode": "LN"}
    assert job_for_symbol("BP.L") == {"idType": "TICKER", "idValue": "BP", "exchCode": "LN"}
    assert job_for_symbol("AAPL.US") == {"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"}
    assert job_for_symbol("AAPL") == {"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"}


def test_fallback_job_uses_bloomberg_slash_tickers_for_uk_lines():
    # Live finding: OpenFIGI has no "BP" on LN; the LSE line is "BP/" because
    # the bare ticker is BP's NYSE ADR. Class-share dots become slashes.
    assert fallback_job_for_symbol("BP.LON") == {"idType": "TICKER", "idValue": "BP/", "exchCode": "LN"}
    assert fallback_job_for_symbol("BT.A.LON") == {"idType": "TICKER", "idValue": "BT/A", "exchCode": "LN"}
    assert fallback_job_for_symbol("AAPL.US") is None  # no US equivalent convention
    assert fallback_job_for_symbol("AAPL") is None


def test_uk_fallback_pass_recovers_slash_ticker_names(monkeypatch):
    """A bare-ticker miss on LN is retried once as the slash ticker."""
    from quantlab.store import identifiers as identifiers_mod
    from quantlab.store.identifiers import map_identifiers

    class SlashAwareStub:
        jobs_per_request = 10

        def map_identifiers(self, jobs):
            out = []
            for job in jobs:
                if job["idValue"] == "BP/":
                    out.append([{"figi": "BBG000C05BD1", "ticker": "BP/", "exchCode": "LN"}])
                else:
                    out.append([])
            return out

    symbols = ["BP.LON", "GONE.US"]
    rows = [(s, "", {}) for s in symbols]

    class FakeResult:
        def fetchall(self):
            return rows

    class FakeConn:
        def execute(self, query, params=None):
            return FakeResult()

        def commit(self):
            pass

    recorded: dict[str, dict] = {}
    monkeypatch.setattr(
        identifiers_mod.catalog, "instrument_ids",
        lambda conn, syms: {s: i for i, s in enumerate(syms)},
    )
    monkeypatch.setattr(
        identifiers_mod.catalog, "record_figi_mappings",
        lambda conn, m, ids, source: recorded.update(m) or len(m),
    )

    report = map_identifiers(FakeConn(), provider=SlashAwareStub())

    assert report.mapped == 1 and report.status == "partial"
    assert recorded["BP.LON"]["figi"] == "BBG000C05BD1"
    assert report.unresolved == ["GONE.US"]


def test_select_candidates_skips_synthetic_macro_and_mapped():
    rows = [
        {"symbol": "AAPL.US", "figi": "", "meta": {}},
        {"symbol": "DONE.US", "figi": "BBG000B9XRY4", "meta": {}},
        {"symbol": "ZX1.US", "figi": "", "meta": {"synthetic": True}},
        {"symbol": "GBPUSD.BOE", "figi": "", "meta": {"macro": True}},
    ]
    assert select_candidates(rows) == ["AAPL.US"]
    # --all re-maps instruments that already carry a FIGI, but synthetic and
    # macro pseudo-instruments are never submitted either way.
    assert select_candidates(rows, only_missing=False) == ["AAPL.US", "DONE.US"]


# ---------------------------------------------------------------------------
# Provider behaviour the mapping run relies on
# ---------------------------------------------------------------------------


def test_keyless_batches_ten_jobs_per_request(keyless_provider):
    provider = keyless_provider
    assert provider.jobs_per_request == 10

    jobs = [{"idType": "TICKER", "idValue": f"T{i}", "exchCode": "US"} for i in range(25)]
    results = provider.map_identifiers(jobs)

    assert [len(c) for c in provider.calls] == [10, 10, 5]
    assert len(results) == 25
    assert all(r and r[0]["figi"].startswith("BBG") for r in results)


def test_keyless_pacing_is_25_requests_per_minute():
    # The polite pacing lives in the shared token bucket the provider's
    # HttpClient draws from; keyless OpenFIGI publishes 25 req/min and rejects
    # bursts, so the bucket must not allow one (the first live run 429'd on
    # exactly that).
    limit = DEFAULT_LIMITS["openfigi"]
    assert limit.rate * 60 == pytest.approx(25)
    assert limit.burst == 1


def test_a_failed_chunk_marks_its_symbols_unresolved_and_continues(monkeypatch):
    """One transient 429 must cost its chunk of ten jobs, not the whole run."""
    from quantlab.store import identifiers as identifiers_mod
    from quantlab.store.identifiers import map_identifiers

    class FlakyStub:
        jobs_per_request = 10

        def map_identifiers(self, jobs):
            if jobs[0]["idValue"] == "B0":  # second chunk of ten
                raise RuntimeError("HTTP 429")
            return [[{"figi": f"BBG{job['idValue']}"}] for job in jobs]

    symbols = [f"A{i}.US" for i in range(10)] + [f"B{i}.US" for i in range(10)]
    rows = [(s, "", {}) for s in symbols]

    class FakeResult:
        def fetchall(self):
            return rows

    class FakeConn:
        def execute(self, query, params=None):
            return FakeResult()

        def commit(self):
            pass

    recorded: dict[str, dict] = {}
    monkeypatch.setattr(
        identifiers_mod.catalog, "instrument_ids",
        lambda conn, syms: {s: i for i, s in enumerate(syms)},
    )
    monkeypatch.setattr(
        identifiers_mod.catalog, "record_figi_mappings",
        lambda conn, m, ids, source: recorded.update(m) or len(m),
    )

    report = map_identifiers(FakeConn(), provider=FlakyStub())

    assert report.candidates == 20
    assert report.mapped == 10
    assert sorted(report.unresolved) == sorted(f"B{i}.US" for i in range(10))
    assert report.status == "partial"
    assert set(recorded) == {f"A{i}.US" for i in range(10)}


def test_mapping_response_parsing_handles_errors_and_empty_data(keyless_provider):
    provider = keyless_provider

    def mixed_payload(url, payload, **_kw):
        return json.dumps(
            [
                {"data": [{"figi": "BBG000B9XRY4", "ticker": "AAPL", "exchCode": "US"}]},
                {"error": "Invalid identifier"},
                {"data": []},
            ]
        ).encode()

    provider.client.post_json = mixed_payload
    results = provider.map_identifiers(
        [{"idType": "TICKER", "idValue": t} for t in ("AAPL", "NOPE", "GONE")]
    )
    assert results[0][0]["figi"] == "BBG000B9XRY4"
    assert results[1] == [], "an error entry maps to no candidates, not an exception"
    assert results[2] == []
