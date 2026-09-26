"""ClickHouse URL parsing, including a managed ClickHouse Cloud service.

The self-hosted container is plain HTTP on 8123 with a simple password; a
managed service is TLS on 8443 with a generated one. Both have to parse.
"""

from __future__ import annotations

from quantlab.storage.warehouse import ch_settings

CLOUD_HOST = "abc123.europe-west2.gcp.clickhouse.cloud"


def test_the_self_hosted_container_url_is_unchanged(monkeypatch):
    monkeypatch.delenv("QUANTLAB_CH_PASSWORD", raising=False)
    assert ch_settings("clickhouse://quantlab:quantlab@clickhouse:8123/quantlab") == {
        "host": "clickhouse",
        "port": 8123,
        "username": "quantlab",
        "password": "quantlab",
        "database": "quantlab",
        "secure": False,
    }


def test_a_cloud_url_is_tls_on_8443(monkeypatch):
    monkeypatch.delenv("QUANTLAB_CH_PASSWORD", raising=False)
    settings = ch_settings(f"clickhouses://default:pw@{CLOUD_HOST}/quantlab")
    assert settings["secure"] is True
    assert settings["port"] == 8443
    assert settings["host"] == CLOUD_HOST


def test_secure_can_be_asked_for_as_a_query_parameter(monkeypatch):
    monkeypatch.delenv("QUANTLAB_CH_PASSWORD", raising=False)
    settings = ch_settings(f"clickhouse://default:pw@{CLOUD_HOST}:8443/quantlab?secure=true")
    assert settings["secure"] is True
    assert settings["database"] == "quantlab"


def test_a_generated_password_survives_percent_encoding(monkeypatch):
    """`@`, `/` and `%` only survive in a URL encoded, and urlparse does not
    decode them -- handing clickhouse_connect `p%40ss` authenticates nobody."""
    monkeypatch.delenv("QUANTLAB_CH_PASSWORD", raising=False)
    settings = ch_settings(f"clickhouses://default:p%40ss%2Fw%25rd@{CLOUD_HOST}/quantlab")
    assert settings["password"] == "p@ss/w%rd"


def test_the_password_can_live_outside_the_url(monkeypatch):
    monkeypatch.setenv("QUANTLAB_CH_PASSWORD", "from-the-environment")
    settings = ch_settings(f"clickhouses://default@{CLOUD_HOST}:8443/quantlab")
    assert settings["password"] == "from-the-environment"
    assert settings["username"] == "default"


def test_a_password_in_the_url_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("QUANTLAB_CH_PASSWORD", "from-the-environment")
    assert ch_settings(f"clickhouses://default:in-url@{CLOUD_HOST}/quantlab")["password"] == "in-url"
