from __future__ import annotations

import automation


def test_tournament_optuna_importerror_falls_back_to_grid(monkeypatch):
    calls: list[str] = []

    def _fake_run_rebaseline(**kwargs):
        calls.append(str(kwargs.get("wf_train_engine")))
        if kwargs.get("wf_train_engine") == "optuna":
            raise ImportError("optuna missing")
        return {"rows": [], "ok": 0, "total": 0}

    monkeypatch.setattr(automation, "run_rebaseline", _fake_run_rebaseline)
    out = automation.run_weekly_tournament(
        profile_names=[],
        dry_run=True,
        wf_train_engine="optuna",
    )
    assert calls == ["optuna", "grid"]
    assert out["requested_engine"] == "optuna"
    assert out["effective_engine"] == "grid"
    assert "optuna" in str(out.get("fallback_reason", "")).lower()


def test_divergence_report_includes_fill_metrics_and_thresholds():
    live = {
        "initial_balance": 1000.0,
        "balance": 1010.0,
        "trades": [
            {
                "timestamp": "2026-05-01T10:00:10+00:00",
                "side": "BUY",
                "entry": 100.1,
                "exit": 101.2,
                "profit": 4.0,
            }
        ],
    }
    bt = {
        "initial_balance": 1000.0,
        "balance": 1012.0,
        "return_pct": 1.2,
        "win_rate": 100.0,
        "trades_detail": [
            {
                "timestamp": "2026-05-01T10:00:30+00:00",
                "side": "BUY",
                "entry": 100.0,
                "exit": 101.0,
                "profit": 5.0,
            }
        ],
    }
    out = automation.divergence_report(
        live_data=live,
        backtest_summary=bt,
        thresholds={"min_timestamp_match_rate": 10},
    )
    assert out["matched_trades"] == 1
    assert out["unmatched_live_trades"] == 0
    assert out["unmatched_backtest_trades"] == 0
    assert out["mean_abs_entry_slip_pct"] > 0
    assert out["mean_abs_exit_slip_pct"] > 0
    assert out["mean_abs_pnl_delta_pct"] > 0
    assert out["thresholds"]["min_timestamp_match_rate"] == 10.0


def test_readiness_rolls_up_new_averages():
    out = automation.readiness_from_divergences(
        reports=[
            {
                "verdict": "aligned",
                "timestamp_match_rate": 90.0,
                "mean_abs_pnl_delta_pct": 0.5,
            },
            {
                "verdict": "diverged",
                "timestamp_match_rate": 50.0,
                "mean_abs_pnl_delta_pct": 2.5,
            },
        ],
        min_aligned_pct=40,
        min_samples=1,
    )
    assert out["verdict"] == "READY"
    assert out["avg_timestamp_match_rate"] == 70.0
    assert out["avg_mean_abs_pnl_delta_pct"] == 1.5
    assert out["min_avg_timestamp_match_rate"] == 60.0
    assert out["max_avg_mean_abs_pnl_delta_pct"] == 2.0


def test_readiness_fails_on_low_average_match_quality():
    out = automation.readiness_from_divergences(
        reports=[
            {
                "verdict": "aligned",
                "timestamp_match_rate": 30.0,
                "mean_abs_pnl_delta_pct": 0.1,
            }
        ],
        min_aligned_pct=50,
        min_samples=1,
        min_avg_timestamp_match_rate=50,
    )
    assert out["aligned_pct"] == 100.0
    assert out["verdict"] == "NOT_READY"
