"""CustomRuleStore: CRUD, slugging, and per-user scoping (feature 008, M2).

Driven against the SQLite adapter with a real users table, so scoping is
tested against real foreign keys, not stubs.
"""

from __future__ import annotations

import pytest

from quantlab.auth import SqliteUserStore
from quantlab.storage.custom_rules import SqliteCustomRuleStore, slugify

THRESHOLD_CONFIG = {
    "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}},
    "comparator": "exits_zone",
    "threshold": 70,
    "bullish_on": "above",
}


@pytest.fixture()
def store(tmp_path):
    return SqliteCustomRuleStore(tmp_path / "quantlab.db")


@pytest.fixture()
def users(tmp_path):
    # Main's identity store, not this branch's: the merge kept the reviewed
    # implementation, and scoping has to be tested against the users table the
    # application actually writes. There is no admin flag -- ownership is the
    # only thing custom-rule scoping asks about.
    store = SqliteUserStore(tmp_path / "quantlab.db")
    return (
        store.create_user("alice@example.com", "hash").to_dict(),
        store.create_user("bob@example.com", "hash").to_dict(),
    )


def test_create_assigns_id_slug_and_timestamps(store):
    rule = store.create_rule(None, "My RSI Exit!", "indicator-threshold", THRESHOLD_CONFIG)

    assert rule["rule_id"]
    assert rule["slug"] == "my-rsi-exit"
    assert rule["template"] == "indicator-threshold"
    assert rule["config"] == THRESHOLD_CONFIG
    assert rule["created_at"] == rule["updated_at"]


def test_slugs_dedup_within_a_scope(store):
    first = store.create_rule(None, "Same Name", "indicator-threshold", THRESHOLD_CONFIG)
    second = store.create_rule(None, "Same Name", "indicator-threshold", THRESHOLD_CONFIG)

    assert second["slug"] == f"{first['slug']}-2"


def test_slugify_normalises_names():
    assert slugify("My RSI Exit!") == "my-rsi-exit"
    assert slugify("  --  ") == "rule"


def test_scoping_hides_other_users_rules(store, users):
    alice, bob = users
    own = store.create_rule(alice["id"], "Alice's Rule", "indicator-threshold", THRESHOLD_CONFIG)
    unscoped = store.create_rule(None, "Shared Rule", "indicator-threshold", THRESHOLD_CONFIG)

    alice_rules = store.list_rules(alice["id"])
    assert {r["rule_id"] for r in alice_rules["items"]} == {own["rule_id"], unscoped["rule_id"]}
    # Bob sees the unscoped rule but not Alice's.
    bob_rules = store.list_rules(bob["id"])
    assert [r["rule_id"] for r in bob_rules["items"]] == [unscoped["rule_id"]]
    assert store.get_rule(own["rule_id"], bob["id"]) is None
    assert store.delete_rule(own["rule_id"], bob["id"]) is False
    assert store.get_rule(own["rule_id"], alice["id"]) is not None


def test_update_renames_re_slug_and_replaces_config(store):
    rule = store.create_rule(None, "Old Name", "indicator-threshold", THRESHOLD_CONFIG)

    updated = store.update_rule(
        rule["rule_id"], None, name="New Name", config={**THRESHOLD_CONFIG, "threshold": 75}
    )

    assert updated["name"] == "New Name"
    assert updated["slug"] == "new-name"
    assert updated["config"]["threshold"] == 75
    assert updated["updated_at"] >= updated["created_at"]
    # A no-name update keeps the existing slug stable.
    again = store.update_rule(rule["rule_id"], None, config=THRESHOLD_CONFIG)
    assert again["slug"] == "new-name"


def test_update_of_an_absent_rule_is_none(store):
    assert store.update_rule("nope", None, name="x") is None


def test_delete(store):
    rule = store.create_rule(None, "Gone", "indicator-threshold", THRESHOLD_CONFIG)

    assert store.delete_rule(rule["rule_id"], None) is True
    assert store.get_rule(rule["rule_id"]) is None
    assert store.delete_rule(rule["rule_id"], None) is False
