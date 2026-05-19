from __future__ import annotations

from experiments.rebaseline_profiles_walkforward import _performance_summary_from_wf


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
