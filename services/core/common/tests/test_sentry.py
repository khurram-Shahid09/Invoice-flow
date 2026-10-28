from typing import Any

from config.sentry import _scrub, init_sentry


def test_no_dsn_means_no_reporting(monkeypatch) -> None:
    import sentry_sdk

    called = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    init_sentry("", "test")
    assert called == []
    init_sentry("https://key@o0.ingest.sentry.io/1", "test")
    assert called and called[0]["send_default_pii"] is False
    assert called[0]["include_local_variables"] is False


def test_events_lose_bodies_cookies_and_credentials() -> None:
    event: Any = {
        "request": {
            "data": {"inputs": {"amount": 1}},
            "cookies": {"wo_access": "jwt"},
            "headers": {"Authorization": "Bearer pat_x", "User-Agent": "ua"},
        }
    }
    scrubbed = _scrub(event, {})
    assert scrubbed is not None
    request = scrubbed["request"]
    assert "data" not in request and "cookies" not in request
    assert request["headers"] == {"Authorization": "[removed]", "User-Agent": "ua"}
