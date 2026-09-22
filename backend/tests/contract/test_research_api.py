"""The research routes, over HTTP, against the synthetic demo.

The demo has prices and signals and no fundamentals at all, which makes it the
right place to pin down the half of the contract that is easiest to get wrong:
a store with nothing filed must answer *empty*, never raise and never zero. A
route that 500s here is a route the runner would have to branch around, and a
route that invents a zero is one that reports a company with no accounts as a
company trading at a P/E of nothing.

The point-in-time arithmetic is exercised against fakes in
tests/unit/test_screen_and_overview.py; what is checked here is the shape of
the responses and the status codes around them.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app
from quantlab.storage import facts

API = "/api/v1"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def symbol(client):
    return client.get(f"{API}/instruments").json()["items"][0]["symbol"]


# --- Fundamentals -----------------------------------------------------------


def test_fundamentals_are_a_bare_array(client, symbol):
    response = client.get(f"{API}/instruments/{symbol}/fundamentals")

    assert response.status_code == 200
    # An array rather than a {total, items} envelope: this is one company's
    # balance sheet, not a page of a collection.
    assert response.json() == []


def test_fundamentals_for_an_unknown_symbol_are_a_404(client):
    response = client.get(f"{API}/instruments/NOSUCH/fundamentals")

    assert response.status_code == 404
    assert "NOSUCH" in response.json()["detail"]


def test_fundamentals_accept_a_concept_filter(client, symbol):
    response = client.get(
        f"{API}/instruments/{symbol}/fundamentals",
        params={"as_of": "2024-06-30", "concepts": "revenue,net_income"},
    )

    assert response.status_code == 200


def test_an_unknown_concept_is_refused_rather_than_quietly_dropped(client, symbol):
    """A filter that silently matches nothing returns an empty inspector, which
    looks exactly like a company that has filed nothing."""
    response = client.get(
        f"{API}/instruments/{symbol}/fundamentals", params={"concepts": "ebitda"}
    )

    assert response.status_code == 422
    assert "ebitda" in response.json()["detail"]


# --- Coverage ---------------------------------------------------------------


def test_coverage_reports_a_real_catalogue_with_nothing_filed(client):
    """Zeroing the instrument total too would say the catalogue is empty, which
    it is not -- the truth is "n names, none of them covered"."""
    body = client.get(f"{API}/fundamentals/coverage").json()

    assert body["instruments_total"] > 0
    assert body["instruments_with_facts"] == 0
    assert body["concepts"] == []
    assert body["symbols_with_facts"] == []
    assert len(body["symbols_without_facts"]) == body["instruments_total"]


# --- Overview ---------------------------------------------------------------


def test_the_overview_composes_a_company_out_of_what_the_demo_has(client, symbol):
    body = client.get(f"{API}/instruments/{symbol}/overview").json()

    assert body["symbol"] == symbol
    assert body["name"]
    assert body["as_of"] == date.today().isoformat()
    assert body["first_bar"] <= body["last_bar"]
    assert body["last_close"] > 0
    assert body["signal_total"] == sum(item["count"] for item in body["signals"])


def test_the_overview_reports_every_concept_as_missing_rather_than_none(client, symbol):
    """Nothing here is merely stale: the demo has filed nothing, so every
    concept is a coverage hole and saying so is the honest answer."""
    body = client.get(f"{API}/instruments/{symbol}/overview").json()

    assert body["facts"] == []
    assert body["concepts_available"] == []
    assert set(body["concepts_missing"]) == set(facts.KNOWN_CONCEPTS)


def test_the_overview_prices_the_company_as_of_the_date_asked_for(client, symbol):
    """The close sits beside accounts resolved to the same date, so a price
    from after it would be the one look-ahead on the page."""
    body = client.get(
        f"{API}/instruments/{symbol}/overview", params={"as_of": "1990-01-01"}
    ).json()

    assert body["last_close"] is None
    assert body["first_bar"] is not None, "the series still has bounds"


def test_an_unknown_symbol_has_no_overview(client):
    assert client.get(f"{API}/instruments/NOSUCH/overview").status_code == 404


# --- Universes and the screen -----------------------------------------------


def test_the_demo_offers_no_universes(client):
    body = client.get(f"{API}/universes").json()

    assert body == {"total": 0, "items": []}


def test_a_screen_with_no_fundamentals_is_empty_rather_than_an_error(client):
    """Empty, not a 404: the universe was not misspelled, there is simply
    nothing filed to screen on."""
    response = client.get(f"{API}/screen", params={"universe": "liquid-500-ftse-core"})

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["universe_size"] == 0
    assert body["excluded_by_constraint"] == 0
    assert body["excluded_unmeasured"] == 0


def test_a_screen_still_says_what_each_metric_would_have_needed(client):
    body = client.get(
        f"{API}/screen",
        params={"universe": "liquid-500-ftse-core", "metrics": "pe,gross_margin"},
    ).json()

    coverage = {item["metric"]: item for item in body["coverage"]}
    assert set(coverage) == {"pe", "gross_margin"}
    assert coverage["pe"]["requires"] == ["net_income", "shares_outstanding"]
    assert coverage["pe"]["measured"] == 0


def test_a_screen_without_a_universe_is_refused(client):
    """Required by the index, not by taste: an unbounded screen cannot use
    fundamentals_pit_idx and falls to a sequential scan (docs/RESEARCH.md §2)."""
    assert client.get(f"{API}/screen").status_code == 422


def test_a_constrained_metric_is_reported_even_when_it_was_not_asked_for(client):
    """Its coverage is the only thing separating "few qualified" from "most
    were never measured"."""
    body = client.get(
        f"{API}/screen",
        params={
            "universe": "liquid-500-ftse-core",
            "metrics": "pe",
            "constraints": "roe:0.15:",
        },
    ).json()

    assert {item["metric"] for item in body["coverage"]} == {"pe", "roe"}


@pytest.mark.parametrize(
    "constraints",
    ["pe:20", "ebitda::20", "pe:cheap:20", "pe:20:10"],
)
def test_a_malformed_constraint_is_refused(client, constraints):
    response = client.get(
        f"{API}/screen",
        params={"universe": "liquid-500-ftse-core", "constraints": constraints},
    )

    assert response.status_code == 422


def test_an_unknown_metric_is_refused(client):
    response = client.get(
        f"{API}/screen", params={"universe": "liquid-500-ftse-core", "metrics": "momentum"}
    )

    assert response.status_code == 422
    assert "momentum" in response.json()["detail"]


def test_an_unknown_sort_metric_is_refused(client):
    response = client.get(
        f"{API}/screen", params={"universe": "liquid-500-ftse-core", "sort_by": "sharpe"}
    )

    assert response.status_code == 422


# --- Unresolved universes ---------------------------------------------------
#
# Only a store with universe history can produce these, so the backend is
# stubbed: the demo answers every screen with an empty result and never reaches
# the failure path at all.


class _WithUniverses:
    """A backend that has one universe, captured once, in 2026."""

    name = "warehouse"

    def health(self):
        return True, 0

    def list_universes(self):
        return {
            "total": 1,
            "items": [{"name": "liquid-500-ftse-core", "as_of": "2026-09-20", "size": 598}],
        }

    def screen(self, **kwargs):
        return None


@pytest.fixture()
def stubbed():
    with TestClient(create_app("/nonexistent.db", backend=_WithUniverses())) as c:
        yield c


def test_a_misspelled_universe_says_so(stubbed):
    response = stubbed.get(f"{API}/screen", params={"universe": "ftse-1000"})

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown universe: ftse-1000"


def test_a_universe_that_does_not_reach_back_that_far_says_that_instead(stubbed):
    """A different correction from a misspelling: the name was right and the
    date was not, and one message covering both sends the caller to fix the
    wrong half of the request."""
    response = stubbed.get(
        f"{API}/screen", params={"universe": "liquid-500-ftse-core", "as_of": "2015-01-01"}
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "no snapshot on or before 2015-01-01" in detail
    assert "2026-09-20" in detail
