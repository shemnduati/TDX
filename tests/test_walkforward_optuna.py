"""Walk-forward train selection: grid vs optional Optuna (train-only objective)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtest import Params


@pytest.fixture
def wf_stub(monkeypatch, sine_ohlcv):
    import walkforward as wf

    monkeypatch.setattr(wf, "fetch_data", lambda _p: sine_ohlcv.copy())
    return wf


def _rsi_wf_params() -> Params:
    return replace(
        Params(),
        strategy="rsi_mean_reversion",
        bars=300,
        ema_trend=0,
        rsi_period=5,
        fee_pct=0.0,
    )


def test_invalid_train_engine_raises(wf_stub) -> None:
    p = _rsi_wf_params()
    with pytest.raises(ValueError, match="train_engine"):
        wf_stub.walk_forward(p, 100, 50, train_engine="tpe")


def test_resolve_train_engine_falls_back_without_optuna(wf_stub, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "optuna":
            raise ImportError("optuna missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    engine, reason = wf_stub.resolve_train_engine("optuna")
    assert engine == "grid"
    assert reason is not None
    assert "optuna" in reason.lower()


def test_grid_engine_metadata(wf_stub) -> None:
    p = _rsi_wf_params()
    r = wf_stub.walk_forward(p, 100, 50, step=50)
    assert r["train_engine"] == "grid"
    assert r["optuna_trials_requested"] is None
    assert r["optuna_trials_effective"] is None
    assert r["optuna_seed"] is None


def test_grid_matches_optuna_window_shape_when_optuna_installed(wf_stub) -> None:
    pytest.importorskip("optuna")
    p = _rsi_wf_params()
    matrix = {"rsi_oversold": [22.0, 28.0, 34.0]}
    r_grid = wf_stub.walk_forward(
        p, 100, 50, step=50, opt_matrix=matrix, train_engine="grid"
    )
    r_opt = wf_stub.walk_forward(
        p,
        100,
        50,
        step=50,
        opt_matrix=matrix,
        train_engine="optuna",
        optuna_trials=24,
        optuna_seed=11,
    )
    assert r_grid["n_windows"] == r_opt["n_windows"]
    assert r_grid["train_engine"] == "grid"
    assert r_opt["train_engine"] == "optuna"
    assert r_opt["optuna_trials_requested"] == 24
    assert r_opt["optuna_trials_effective"] <= r_opt["search_space_size"]


def test_allowed_sessions_in_tuned_keys_for_donchian_breakout(wf_stub) -> None:
    """_default_tuning_matrix for donchian_breakout must include allowed_sessions
    so that a walk-forward run reports it as a tuned key."""
    from walkforward import _default_tuning_matrix

    p = replace(Params(), strategy="donchian_breakout", bars=300, fee_pct=0.0)
    matrix = _default_tuning_matrix(p)
    assert "allowed_sessions" in matrix, (
        "allowed_sessions axis missing from donchian_breakout tuning matrix"
    )
    candidates = matrix["allowed_sessions"]
    assert isinstance(candidates, list) and len(candidates) >= 2
    # All candidates must be tuples (hashable for Optuna suggest_categorical)
    for cand in candidates:
        assert isinstance(cand, tuple), f"Expected tuple, got {type(cand)}: {cand!r}"


def test_tuning_matrix_session_axis_present_for_all_strategies(wf_stub) -> None:
    """Every strategy with a defined matrix should include an allowed_sessions axis."""
    from walkforward import _default_tuning_matrix

    strategies = [
        "ema_crossover",
        "rsi_mean_reversion",
        "donchian_breakout",
        "intraday_donchian",
        "liquidity_sweep",
    ]
    for strat in strategies:
        p = replace(Params(), strategy=strat, bars=300)
        matrix = _default_tuning_matrix(p)
        assert "allowed_sessions" in matrix, (
            f"allowed_sessions missing from {strat} tuning matrix"
        )


def test_final_oos_holdout_is_reserved_from_wfo_windows(wf_stub) -> None:
    p = _rsi_wf_params()
    r = wf_stub.walk_forward(p, 100, 50, step=50)
    assert r["total_bars"] == 300
    assert r["holdout_start_bar"] == 225
    assert r["holdout_bars"] == 75
    assert r["n_windows"] == 2

    # All WFO windows must end before the final holdout starts.
    max_test_end = max(int(w["test_end"]) for w in r["windows"])
    assert max_test_end <= r["holdout_start_bar"]

    final_oos = r["final_oos"]
    assert final_oos["start_bar"] == r["holdout_start_bar"]
    assert final_oos["end_bar"] == r["total_bars"]
    assert final_oos["bars"] == r["holdout_bars"]
