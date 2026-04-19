"""Tests for the per-market profile loader.

We isolate disk via `TDX_PROFILES_DIR` so the real `profiles/` directory
is never touched. Every test gets a fresh sandbox.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def _isolate_profiles_dir(tmp_path, monkeypatch):
    """Redirect profile storage to tmp_path for every profile test.

    profiles.py reads its dir via module-level os.environ.get(...) at
    import time, so we re-import the module after setting the env var
    to make sure the new dir takes effect.
    """
    monkeypatch.setenv("TDX_PROFILES_DIR", str(tmp_path / "profiles"))
    import importlib
    import profiles as _p
    importlib.reload(_p)
    yield
    # Restore after each test so other tests don't see a reloaded module.
    importlib.reload(_p)


def _make_sample_profile(name: str, overrides: dict, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir(exist_ok=True)
    doc = {
        "name": name,
        "description": "test profile",
        "source": "test",
        "created_at": "2026-04-18T00:00:00Z",
        "params": overrides,
    }
    path = pdir / f"{name}.json"
    with open(path, "w") as f:
        json.dump(doc, f)
    return path


# --------------------------------------------------------- basic API -----


def test_list_profiles_empty_on_fresh_dir():
    import profiles
    assert profiles.list_profiles() == []


def test_list_profiles_returns_sorted_names(tmp_path):
    _make_sample_profile("zebra", {"symbol": "BTC/USDT"}, tmp_path)
    _make_sample_profile("alpha", {"symbol": "ETH/USDT"}, tmp_path)
    _make_sample_profile("mango", {"symbol": "SOL/USDT"}, tmp_path)

    import profiles
    assert profiles.list_profiles() == ["alpha", "mango", "zebra"]


def test_list_profiles_ignores_non_json(tmp_path):
    _make_sample_profile("real", {"symbol": "BTC/USDT"}, tmp_path)
    # Stray non-json file should be quietly ignored.
    (tmp_path / "profiles" / "notes.txt").write_text("not a profile")

    import profiles
    assert profiles.list_profiles() == ["real"]


# ---------------------------------------------------------- load ----------


def test_load_profile_returns_full_doc(tmp_path):
    _make_sample_profile("x", {"symbol": "ETH/USDT", "ema_short": 7}, tmp_path)

    import profiles
    doc = profiles.load_profile("x")
    assert doc["name"] == "x"
    assert doc["params"]["symbol"] == "ETH/USDT"
    assert doc["params"]["ema_short"] == 7


def test_load_profile_missing_raises_with_helpful_message():
    import profiles
    with pytest.raises(FileNotFoundError) as excinfo:
        profiles.load_profile("does-not-exist")
    # The error should help the user discover what IS available.
    assert "Available" in str(excinfo.value)


def test_load_profile_unknown_field_raises(tmp_path):
    """Typos in hand-edited JSON should fail loud, not silently."""
    _make_sample_profile(
        "bad", {"symbol": "BTC/USDT", "ema_shrt": 7}, tmp_path  # typo!
    )
    import profiles
    with pytest.raises(ValueError, match="unknown Params field"):
        profiles.load_profile("bad")


def test_load_profile_missing_params_key(tmp_path):
    path = tmp_path / "profiles" / "malformed.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"name": "malformed", "description": ""}))

    import profiles
    with pytest.raises(ValueError, match="missing 'params'"):
        profiles.load_profile("malformed")


# --------------------------------------------------------- apply ----------


def test_apply_profile_overrides_specified_fields_only(tmp_path):
    _make_sample_profile(
        "p", {"symbol": "ETH/USDT", "strategy": "donchian_breakout",
              "donchian_period": 55}, tmp_path
    )

    import profiles
    from backtest import Params

    base = Params(symbol="BTC/USDT", ema_short=20, donchian_period=20)
    result = profiles.apply_profile(base, "p")

    assert result.symbol == "ETH/USDT"
    assert result.strategy == "donchian_breakout"
    assert result.donchian_period == 55
    # Unspecified field preserved from base
    assert result.ema_short == 20


def test_apply_profile_returns_new_instance(tmp_path):
    _make_sample_profile("p", {"symbol": "ETH/USDT"}, tmp_path)

    import profiles
    from backtest import Params

    base = Params()
    result = profiles.apply_profile(base, "p")
    assert result is not base
    # Input untouched
    assert base.symbol != "ETH/USDT" or result.symbol == base.symbol


# ---------------------------------------------------------- save ----------


def test_save_profile_writes_minimal_delta_by_default(tmp_path):
    import profiles
    from backtest import Params

    # A Params that differs from defaults only in two fields
    custom = replace(Params(), symbol="SOL/USDT", ema_short=7)

    path = profiles.save_profile(
        "my-test", custom, description="test", source="unit-test"
    )

    assert os.path.exists(path)
    with open(path) as f:
        doc = json.load(f)

    # Minimal-delta mode: only the two changed fields are persisted
    assert doc["params"]["symbol"] == "SOL/USDT"
    assert doc["params"]["ema_short"] == 7
    assert "ema_long" not in doc["params"]
    assert "strategy" not in doc["params"]
    # Metadata round-trips
    assert doc["description"] == "test"
    assert doc["source"] == "unit-test"
    assert "created_at" in doc


def test_save_profile_full_includes_every_field(tmp_path):
    import profiles
    from backtest import Params

    profiles.save_profile(
        "full", Params(), description="", source="", include_defaults=True
    )
    doc = profiles.load_profile("full")
    # Full mode should contain every non-runtime-only field
    assert "ema_long" in doc["params"]
    assert "atr_period" in doc["params"]
    # Runtime-only fields are still excluded even in full mode
    assert "initial_balance" not in doc["params"]
    assert "bars" not in doc["params"]


def test_save_profile_round_trip_preserves_non_runtime_fields(tmp_path):
    import profiles
    from backtest import Params

    custom = replace(
        Params(),
        symbol="SOL/USDT",
        strategy="donchian_breakout",
        donchian_period=55,
        use_adx_filter=True,
        adx_min=15.0,
    )
    profiles.save_profile("rt", custom)
    restored = profiles.apply_profile(Params(), "rt")

    assert restored.symbol == "SOL/USDT"
    assert restored.strategy == "donchian_breakout"
    assert restored.donchian_period == 55
    assert restored.use_adx_filter is True
    assert restored.adx_min == 15.0


# --------------------------------------------------------- delete --------


def test_delete_profile_removes_file(tmp_path):
    _make_sample_profile("throwaway", {"symbol": "BTC/USDT"}, tmp_path)
    import profiles

    assert "throwaway" in profiles.list_profiles()
    profiles.delete_profile("throwaway")
    assert "throwaway" not in profiles.list_profiles()


def test_delete_profile_silently_ignores_missing():
    import profiles
    # Should not raise — idempotent.
    profiles.delete_profile("never-existed")


# ----------------------------------------------------- name validation -----


@pytest.mark.parametrize("bad_name", [
    "has space",
    "has/slash",
    "has\\backslash",
    ".hidden",
    "",
    "a" * 65,
    "with:colon",
    "../escape",
])
def test_invalid_profile_names_rejected(bad_name):
    import profiles
    from backtest import Params
    with pytest.raises(ValueError, match="invalid profile name"):
        profiles.save_profile(bad_name, Params())


# ------------------------------------ extended schema (parent / changelog /
# performance) ----------------------------------------------------------------


def test_save_stores_parent_changelog_performance():
    import profiles
    from backtest import Params

    params = replace(Params(), symbol="ETH/USDT", donchian_period=30)
    profiles.save_profile(
        "child",
        params,
        description="child of btc-baseline",
        parent="btc-baseline",
        changelog_message="Initial version: widened Donchian window",
        performance={
            "kind": "backtest",
            "run_id": "run_xyz",
            "summary": {"trades": 41, "return_pct": 7.3,
                        "max_drawdown_pct": -6.1},
        },
    )
    doc = profiles.load_profile("child")
    assert doc["parent"] == "btc-baseline"
    assert len(doc["changelog"]) == 1
    entry = doc["changelog"][0]
    assert entry["message"] == "Initial version: widened Donchian window"
    assert "at" in entry  # auto-stamped
    assert doc["performance"]["kind"] == "backtest"
    assert doc["performance"]["run_id"] == "run_xyz"
    assert doc["performance"]["summary"]["trades"] == 41
    assert "recorded_at" in doc["performance"]


def test_save_without_changelog_leaves_empty_list():
    import profiles
    from backtest import Params

    profiles.save_profile("bare", Params(), description="no changelog")
    doc = profiles.load_profile("bare")
    assert doc["changelog"] == []
    assert doc["parent"] is None
    assert doc["performance"] is None


def test_save_rejects_non_object_performance():
    import profiles
    from backtest import Params

    with pytest.raises(ValueError, match="performance must be an object"):
        profiles.save_profile(
            "p", Params(), performance="not-a-dict"  # type: ignore[arg-type]
        )


def test_save_rejects_non_dict_summary():
    import profiles
    from backtest import Params

    with pytest.raises(ValueError, match="performance.summary"):
        profiles.save_profile(
            "p", Params(),
            performance={"summary": [1, 2, 3]},  # type: ignore[dict-item]
        )


def test_save_validates_parent_name():
    import profiles
    from backtest import Params

    with pytest.raises(ValueError, match="invalid profile name"):
        profiles.save_profile("child", Params(), parent="has space")


def test_load_upgrades_old_profile_without_new_fields(tmp_path):
    # Pre-existing profile written before `parent`/`changelog`/`performance`
    # existed; load should fill in the missing keys so downstream code
    # doesn't need to branch.
    pdir = tmp_path / "profiles"
    pdir.mkdir(exist_ok=True)
    with open(pdir / "legacy.json", "w") as f:
        json.dump({
            "name": "legacy",
            "description": "old",
            "source": "",
            "created_at": "2026-01-01T00:00:00Z",
            "params": {"symbol": "ETH/USDT"},
        }, f)

    import profiles
    doc = profiles.load_profile("legacy")
    assert doc["parent"] is None
    assert doc["changelog"] == []
    assert doc["performance"] is None


# ----------------------------------------------- update_profile (PATCH) ------


def test_update_profile_edits_description_and_source():
    import profiles
    from backtest import Params

    profiles.save_profile("editable", Params(),
                          description="first", source="orig")
    doc = profiles.update_profile(
        "editable",
        description="second",
        source="revised",
    )
    assert doc["description"] == "second"
    assert doc["source"] == "revised"

    # Persisted on disk, not just returned.
    reread = profiles.load_profile("editable")
    assert reread["description"] == "second"
    assert reread["source"] == "revised"


def test_update_profile_appends_changelog_entry():
    import profiles
    from backtest import Params

    profiles.save_profile("iterate", Params(),
                          changelog_message="initial")
    profiles.update_profile("iterate",
                            append_message="tweaked ema_short 9->12")
    profiles.update_profile("iterate",
                            append_message="widened ATR period 14->20")

    doc = profiles.load_profile("iterate")
    msgs = [e["message"] for e in doc["changelog"]]
    assert msgs == [
        "initial",
        "tweaked ema_short 9->12",
        "widened ATR period 14->20",
    ]


def test_update_profile_can_replace_performance():
    import profiles
    from backtest import Params

    profiles.save_profile(
        "p", Params(),
        performance={"kind": "backtest",
                     "summary": {"return_pct": 5.0}},
    )
    profiles.update_profile(
        "p",
        performance={"kind": "walkforward",
                     "summary": {"return_pct": 9.0,
                                 "positive_rate": 0.72}},
    )
    doc = profiles.load_profile("p")
    assert doc["performance"]["kind"] == "walkforward"
    assert doc["performance"]["summary"]["return_pct"] == 9.0


def test_update_profile_clear_performance_explicit_flag():
    import profiles
    from backtest import Params

    profiles.save_profile(
        "p", Params(),
        performance={"summary": {"return_pct": 5.0}},
    )
    profiles.update_profile("p", clear_performance=True)
    doc = profiles.load_profile("p")
    assert doc["performance"] is None


def test_update_profile_preserves_params():
    """Core invariant: PATCH must never mutate params — that's what
    makes profiles reproducible. Tweaks to params require a new
    profile name (with optional parent) so lineage stays honest."""
    import profiles
    from backtest import Params

    params = replace(Params(), symbol="ETH/USDT", donchian_period=25)
    profiles.save_profile("stable", params)
    before = profiles.load_profile("stable")["params"]

    profiles.update_profile("stable",
                            description="totally different",
                            append_message="just metadata")

    after = profiles.load_profile("stable")["params"]
    assert before == after


def test_update_profile_missing_raises():
    import profiles
    with pytest.raises(FileNotFoundError):
        profiles.update_profile("nope", description="x")


def test_update_profile_ignores_empty_append_message():
    import profiles
    from backtest import Params

    profiles.save_profile("q", Params())
    profiles.update_profile("q", append_message="   ")  # whitespace only
    assert profiles.load_profile("q")["changelog"] == []


@pytest.mark.parametrize("good_name", [
    "btc-4h-adx",
    "eth_4h_donchian",
    "strategy.v2",
    "a",
    "BTCUSDT4h",
])
def test_valid_profile_names_accepted(good_name, tmp_path):
    import profiles
    from backtest import Params
    profiles.save_profile(good_name, Params())
    assert good_name in profiles.list_profiles()
