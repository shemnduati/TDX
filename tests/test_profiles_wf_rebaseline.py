from __future__ import annotations

from experiments.rebaseline_profiles_walkforward import (
    _performance_summary_from_wf,
    run_rebaseline,
)


def test_run_rebaseline_reports_optuna_fallback(monkeypatch):
    import experiments.rebaseline_profiles_walkforward as rebaseline_mod

    monkeypatch.setattr(
        rebaseline_mod,
        "resolve_train_engine",
        lambda _: ("grid", "optuna missing"),
    )
    monkeypatch.setattr(rebaseline_mod.profile_store, "list_profiles", lambda: ["p1"])
    monkeypatch.setattr(
        rebaseline_mod.profile_store,
        "load_profile",
        lambda _name: {"params": {}},
    )
    monkeypatch.setattr(
        rebaseline_mod.profile_store,
        "apply_profile",
        lambda base, _name: base,
    )
    monkeypatch.setattr(
        rebaseline_mod,
        "walk_forward",
        lambda *a, **k: {
            "n_windows": 1,
            "mean_test_ret": 0.0,
            "median_test_ret": 0.0,
            "stdev_test_ret": 0.0,
            "positive_rate": 0.0,
            "mean_test_mdd_pct": 0.0,
            "total_test_trades": 0,
            "total_train_trades": 0,
            "unique_selected_configs": 1,
            "selection_transition_rate": 0.0,
            "tuned_keys": [],
            "train_engine": "grid",
            "dev_end_bar": 0,
            "holdout_start_bar": 0,
            "holdout_bars": 0,
            "final_oos": {},
        },
    )

    out = run_rebaseline(profile_names=["p1"], dry_run=True, wf_train_engine="optuna")
    assert out["requested_engine"] == "optuna"
    assert out["effective_engine"] == "grid"
    assert out["fallback_reason"] is not None
    assert out["rows"][0]["ok"] is True


def test_performance_summary_from_wf_maps_core_and_final_oos_fields() -> None:
    wf = {
        "n_windows": 4,
        "mean_test_ret": 1.25,
        "median_test_ret": 1.0,
        "stdev_test_ret": 0.5,
        "positive_rate": 75.0,
        "mean_test_mdd_pct": 2.0,
        "total_test_trades": 42,
        "total_train_trades": 39,
        "unique_selected_configs": 3,
        "selection_transition_rate": 25.0,
        "tuned_keys": ["ema_short", "ema_long"],
        "train_engine": "grid",
        "dev_end_bar": 750,
        "holdout_start_bar": 750,
        "holdout_bars": 250,
        "final_oos": {
            "return_pct": -0.4,
            "trades": 7,
            "win_rate": 42.0,
            "max_drawdown_pct": 3.2,
            "profit_factor": 0.9,
            "policy": "mode_selected_config",
        },
    }
    s = _performance_summary_from_wf(wf)
    assert s["n_windows"] == 4
    assert s["train_engine"] == "grid"
    assert s["holdout_bars"] == 250
    assert s["final_oos_return_pct"] == -0.4
    assert s["final_oos_trades"] == 7
    assert s["final_oos_policy"] == "mode_selected_config"
