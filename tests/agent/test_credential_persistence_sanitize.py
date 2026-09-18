"""C3-21: nested-mapping secret leakage through the borrowed-credential sanitizer."""

from agent.credential_persistence import sanitize_borrowed_credential_payload


def _borrowed_payload():
    # source "relay" is NOT in _PERSISTABLE_PROVIDER_SOURCES → borrowed.
    return {
        "source": "relay",
        "label": "pool-relay-1",
        "access_token": "TOP-LEVEL-SECRET",
        "oauth_state": {
            "refresh_token": "NESTED-SECRET",
            "expires_at": 123,
        },
        "entries": [
            {"api_key": "LISTED-SECRET", "name": "a"},
            {"name": "b"},
        ],
        "nested_tuple": ("x", {"token": "TUPLED-SECRET"}),
    }


def test_top_level_and_nested_secrets_are_stripped():
    out = sanitize_borrowed_credential_payload(_borrowed_payload())
    blob = repr(out)
    for secret in ("TOP-LEVEL-SECRET", "NESTED-SECRET", "LISTED-SECRET", "TUPLED-SECRET"):
        assert secret not in blob, secret
    # Non-secret metadata survives at every depth.
    assert out["label"] == "pool-relay-1"
    assert out["oauth_state"]["expires_at"] == 123
    assert out["entries"][0]["name"] == "a"
    assert out["entries"][1] == {"name": "b"}
    assert out["nested_tuple"][0] == "x"
    assert "token" not in out["nested_tuple"][1]


def test_owned_source_payload_passes_through_unchanged():
    payload = _borrowed_payload()
    payload["source"] = "manual:device_code"
    out = sanitize_borrowed_credential_payload(payload, "nous")
    assert out["oauth_state"]["refresh_token"] == "NESTED-SECRET"
