"""Integration tests for the /profiles Flask endpoints.

These tests exercise the HTTP surface, not profiles.py directly (that's
covered by test_profiles.py). We use Flask's test client so we don't
need to spin up a real server.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client():
    import dashboard
    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def _save_profile(client, name: str, params: dict, **meta):
    body = {"name": name, "params": params, **meta}
    return client.post(
        "/profiles",
        data=json.dumps(body),
        content_type="application/json",
    )


# ------------------------------------------------------------- listing -----


def test_list_profiles_empty(client):
    res = client.get("/profiles")
    assert res.status_code == 200
    assert res.get_json() == {"profiles": []}


def test_list_profiles_returns_summaries(client):
    # Use non-default values so save_profile's auto-minimisation retains
    # them; otherwise the profile stores zero overrides (profiles only
    # record deltas from config.py defaults).
    r = _save_profile(
        client, "test-1",
        {"symbol": "ETH/USDT", "timeframe": "1h", "strategy": "rsi_mean_reversion",
         "ema_short": 9},
        description="first test",
    )
    assert r.status_code == 200

    r = _save_profile(
        client, "test-2",
        {"symbol": "SOL/USDT", "timeframe": "30m",
         "strategy": "donchian_breakout"},
    )
    assert r.status_code == 200

    res = client.get("/profiles")
    body = res.get_json()
    assert res.status_code == 200
    names = [p["name"] for p in body["profiles"]]
    # Sorted
    assert names == ["test-1", "test-2"]

    first = body["profiles"][0]
    assert first["description"] == "first test"
    assert first["preview"] == {
        "symbol": "ETH/USDT", "timeframe": "1h", "strategy": "rsi_mean_reversion"
    }
    # override_count should reflect the four changed fields we sent
    assert first["override_count"] == 4


# --------------------------------------------------------------- get -------


def test_get_profile_returns_full_doc(client):
    _save_profile(
        client, "full",
        {"symbol": "SOL/USDT", "ema_short": 7},
        description="d", source="s",
    )
    res = client.get("/profiles/full")
    assert res.status_code == 200
    body = res.get_json()
    assert body["name"] == "full"
    assert body["description"] == "d"
    assert body["source"] == "s"
    # SOL/USDT differs from BTC/USDT default -> preserved
    assert body["params"]["symbol"] == "SOL/USDT"
    # 7 differs from the ema_short default (12) -> preserved
    assert body["params"]["ema_short"] == 7


def test_get_missing_profile_returns_404(client):
    res = client.get("/profiles/nonexistent")
    assert res.status_code == 404
    assert "error" in res.get_json()


# ---------------------------------------------------------- save/validate --


def test_save_rejects_missing_name(client):
    res = client.post(
        "/profiles",
        data=json.dumps({"params": {"symbol": "ETH/USDT"}}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "name" in res.get_json()["error"]


def test_save_rejects_missing_params(client):
    res = client.post(
        "/profiles",
        data=json.dumps({"name": "x"}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "params" in res.get_json()["error"]


def test_save_rejects_bad_name(client):
    res = _save_profile(client, "has space", {"symbol": "ETH/USDT"})
    assert res.status_code == 400
    assert "invalid profile name" in res.get_json()["error"]


def test_save_ignores_unknown_params_silently(client):
    """`_params_from_payload` filters unknown keys BEFORE profile store
    validation, so a UI sending extra fields (e.g. UI-only state)
    doesn't break the save path. Contrast with hand-edited JSON, which
    loads through profiles.load_profile directly and does flag typos."""
    res = _save_profile(
        client, "lenient",
        {"symbol": "ETH/USDT", "something_bogus": 123},
    )
    assert res.status_code == 200
    # Verify the bogus field was dropped
    got = client.get("/profiles/lenient").get_json()
    assert "something_bogus" not in got["params"]


def test_save_returns_created_doc(client):
    res = _save_profile(
        client, "s1",
        {"symbol": "ETH/USDT"},
        description="saved via API",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["saved"]["name"] == "s1"
    assert body["saved"]["description"] == "saved via API"
    assert "created_at" in body["saved"]
    assert body["saved"]["params"]["symbol"] == "ETH/USDT"
    assert "path" in body


# -------------------------------------------------------------- delete -----


def test_delete_existing_profile(client):
    _save_profile(client, "temp", {"symbol": "ETH/USDT"})
    assert client.get("/profiles/temp").status_code == 200

    res = client.delete("/profiles/temp")
    assert res.status_code == 200
    assert res.get_json() == {"deleted": True}
    assert client.get("/profiles/temp").status_code == 404


def test_delete_missing_profile_is_idempotent(client):
    res = client.delete("/profiles/never-existed")
    assert res.status_code == 200
    assert res.get_json() == {"deleted": True}


def test_delete_bad_name_returns_400(client):
    res = client.delete("/profiles/has space")
    assert res.status_code == 400


# ----------------------------------------------------- end-to-end round-trip


# ------------------------------------ extended schema via /profiles --------


def test_post_accepts_parent_changelog_performance(client):
    r = _save_profile(
        client, "parent-v1",
        {"symbol": "ETH/USDT"},
    )
    assert r.status_code == 200

    body = {
        "name": "parent-v2",
        "params": {"symbol": "ETH/USDT", "donchian_period": 30},
        "description": "added Donchian tweak",
        "parent": "parent-v1",
        "changelog_message": "Widened Donchian 20 -> 30; WF +0.03",
        "performance": {
            "kind": "backtest",
            "run_id": "abc123",
            "summary": {
                "trades": 47,
                "return_pct": 8.4,
                "max_drawdown_pct": -4.7,
                "profit_factor": 1.6,
            },
        },
    }
    res = client.post(
        "/profiles", data=json.dumps(body), content_type="application/json"
    )
    assert res.status_code == 200
    saved = res.get_json()["saved"]
    assert saved["parent"] == "parent-v1"
    assert len(saved["changelog"]) == 1
    assert (saved["changelog"][0]["message"]
            == "Widened Donchian 20 -> 30; WF +0.03")
    assert saved["performance"]["run_id"] == "abc123"
    assert saved["performance"]["summary"]["trades"] == 47


def test_list_surfaces_performance_preview_and_version_count(client):
    _save_profile(
        client, "p1",
        {"symbol": "ETH/USDT"},
        performance={
            "kind": "backtest",
            "summary": {
                "return_pct": 5.5,
                "trades": 30,
                "max_drawdown_pct": -3.1,
                "profit_factor": 1.4,
            },
        },
    )
    _save_profile(
        client, "p2",
        {"symbol": "ETH/USDT", "donchian_period": 25},
        parent="p1",
    )
    _save_profile(
        client, "p3",
        {"symbol": "ETH/USDT", "donchian_period": 30},
        parent="p1",
    )

    listing = client.get("/profiles").get_json()["profiles"]
    by_name = {p["name"]: p for p in listing}

    # p1 has two children
    assert by_name["p1"]["version_count"] == 2
    assert by_name["p2"]["version_count"] == 0
    assert by_name["p2"]["parent"] == "p1"

    # Performance preview only on profiles that have one
    pp = by_name["p1"]["performance_preview"]
    assert pp["return_pct"] == 5.5
    assert pp["trades"] == 30
    assert pp["kind"] == "backtest"
    assert by_name["p2"]["performance_preview"] is None


def test_post_rejects_invalid_parent_name(client):
    res = client.post(
        "/profiles",
        data=json.dumps({
            "name": "child",
            "params": {"symbol": "ETH/USDT"},
            "parent": "has space",
        }),
        content_type="application/json",
    )
    assert res.status_code == 400


# ----------------------------------------------------- PATCH /profiles ------


def test_patch_appends_changelog_entry(client):
    _save_profile(
        client, "iter",
        {"symbol": "ETH/USDT"},
        changelog_message="initial version",
    )
    res = client.patch(
        "/profiles/iter",
        data=json.dumps({"append_message": "bumped ema_short"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    saved = res.get_json()["saved"]
    assert len(saved["changelog"]) == 2
    assert saved["changelog"][-1]["message"] == "bumped ema_short"


def test_patch_edits_description(client):
    _save_profile(client, "d", {"symbol": "ETH/USDT"}, description="old")
    res = client.patch(
        "/profiles/d",
        data=json.dumps({"description": "new and improved"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json()["saved"]["description"] == "new and improved"


def test_patch_can_clear_performance(client):
    _save_profile(
        client, "clr",
        {"symbol": "ETH/USDT"},
        performance={"summary": {"return_pct": 5.0}},
    )
    res = client.patch(
        "/profiles/clr",
        data=json.dumps({"clear_performance": True}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json()["saved"]["performance"] is None


def test_patch_returns_404_for_missing_profile(client):
    res = client.patch(
        "/profiles/ghost",
        data=json.dumps({"description": "x"}),
        content_type="application/json",
    )
    assert res.status_code == 404


def test_patch_cannot_change_params(client):
    """The backend API surface doesn't accept `params` on PATCH (by
    design — see profiles.update_profile docstring). If a client
    includes it anyway, it must be silently ignored, not applied."""
    _save_profile(
        client, "immut",
        {"symbol": "ETH/USDT", "donchian_period": 25},
    )
    client.patch(
        "/profiles/immut",
        data=json.dumps({
            "description": "touched",
            # This should NOT leak into params.
            "params": {"donchian_period": 99},
        }),
        content_type="application/json",
    )
    doc = client.get("/profiles/immut").get_json()
    assert doc["params"]["donchian_period"] == 25


def test_profile_round_trip_survives_save_load_get(client):
    """Save a profile, fetch it, verify every non-default field we set
    is present and typed correctly after the JSON round-trip.

    We build the payload dynamically by reading /config/defaults and
    perturbing each field, so the test stays green as config.py
    evolves. save_profile's auto-minimisation drops any field that
    matches defaults; picking non-default values makes the persistence
    behaviour observable.
    """
    defaults = client.get("/config/defaults").get_json()

    # Pick a concrete delta per field of interest — numeric fields
    # bump by +5, booleans flip, the "symbol" is a known-different
    # ticker. Keeping this to a small representative set so a
    # regression in save/load is easy to debug.
    payload = {
        "symbol": "ETH/USDT" if defaults["symbol"] != "ETH/USDT"
        else "SOL/USDT",
        "timeframe": "1h" if defaults["timeframe"] != "1h" else "30m",
        "strategy": ("donchian_breakout"
                     if defaults["strategy"] != "donchian_breakout"
                     else "rsi_mean_reversion"),
        "donchian_period": int(defaults["donchian_period"]) + 5,
        "use_adx_filter": not bool(defaults["use_adx_filter"]),
        "atr_stop_mult": float(defaults["atr_stop_mult"]) + 0.5,
    }
    r = _save_profile(client, "eth-rt", payload)
    assert r.status_code == 200

    got = client.get("/profiles/eth-rt").get_json()
    params = got["params"]
    for k, v in payload.items():
        assert params[k] == v, (
            f"field {k!r} did not round-trip "
            f"(got {params.get(k)!r}, expected {v!r})"
        )
