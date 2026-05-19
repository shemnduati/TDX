"""Capital-sleeved multi-strategy mix (see portfolio.py)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from backtest import Params
from portfolio import (
    _entry_allowed,
    _vol_scale_from_atr,
    normalize_weights,
    run_allocated_strategy_mix,
    run_multi_strategy_portfolio,
)


def test_normalize_weights_scales_positive_entries() -> None:
    n = normalize_weights({"a": 1.0, "b": 3.0})
    assert pytest.approx(n["a"]) == 0.25
    assert pytest.approx(n["b"]) == 0.75


def test_normalize_weights_rejects_empty() -> None:
    with pytest.raises(ValueError, match="weights must contain"):
        normalize_weights({})


def test_normalize_weights_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative weights"):
        normalize_weights({"ema_crossover": -0.5, "donchian_breakout": 1})


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="unknown strategies"):
        run_allocated_strategy_mix(
            Params(bars=10), {"ema_crossover": 1.0, "__not_real__": 0.5}
        )


def test_combined_balance_is_sum_of_sleeves(sine_ohlcv, fresh_params) -> None:
    df = sine_ohlcv.copy()
    base = replace(
        fresh_params,
        bars=len(df),
        strategy="rsi_mean_reversion",
    )
    out = run_allocated_strategy_mix(
        base,
        {"rsi_mean_reversion": 0.4, "ema_crossover": 0.6},
        df=df,
        use_cache=False,
        verbose=False,
    )
    part = sum(s["summary"]["balance"] for s in out["sleeves"])
    assert pytest.approx(part) == out["combined"]["balance"]
    ini = float(base.initial_balance)
    assert pytest.approx(out["combined"]["total_pnl"]) == part - ini
    assert out["combined"]["total_trades"] == sum(
        int(s["summary"]["trades"]) for s in out["sleeves"]
    )


def test_entry_allowed_blocks_on_limits() -> None:
    assert not _entry_allowed(
        "BUY",
        ["LONG", "SHORT"],
        max_open_positions=2,
        max_correlated_positions=2,
        group_name="g1",
        open_groups=["g1", "g2"],
        max_positions_per_group=2,
        circuit_halted=False,
    )
    assert not _entry_allowed(
        "BUY",
        ["LONG", "LONG"],
        max_open_positions=5,
        max_correlated_positions=2,
        group_name="g1",
        open_groups=["g1", "g1"],
        max_positions_per_group=3,
        circuit_halted=False,
    )
    assert not _entry_allowed(
        "SELL",
        [],
        max_open_positions=5,
        max_correlated_positions=2,
        group_name="g1",
        open_groups=[],
        max_positions_per_group=2,
        circuit_halted=True,
    )

    assert not _entry_allowed(
        "BUY",
        ["SHORT"],
        max_open_positions=5,
        max_correlated_positions=5,
        group_name="trend",
        open_groups=["trend", "trend"],
        max_positions_per_group=2,
        circuit_halted=False,
    )


def test_vol_scale_from_atr_clamps() -> None:
    # target 1.5%, atr_pct 0.5% => 3x, but clamped to 2x
    s = _vol_scale_from_atr(
        atr=0.5,
        price=100.0,
        target_atr_pct=0.015,
        scale_min=0.25,
        scale_max=2.0,
    )
    assert s == pytest.approx(2.0)


def test_multi_strategy_runner_smoke(sine_ohlcv, fresh_params) -> None:
    df = sine_ohlcv.copy()
    base = replace(
        fresh_params,
        bars=len(df),
        strategy="rsi_mean_reversion",
        use_atr_sizing=True,
        atr_period=14,
        atr_risk_pct=0.01,
        atr_stop_mult=2.0,
        atr_tp_mult=3.0,
    )
    out = run_multi_strategy_portfolio(
        base,
        {"rsi_mean_reversion": 0.5, "ema_crossover": 0.5},
        df=df,
        use_cache=False,
        verbose=False,
    )
    assert out["method"] == "shared_market_multi_strategy_runner"
    assert out["combined"]["balance"] > 0
    assert "max_drawdown_pct" in out["combined"]
    assert "circuit_halted_bars" in out["combined"]
    assert "skipped_by_group_limit" in out["combined"]


def test_multi_strategy_runner_accepts_budget_and_groups(sine_ohlcv, fresh_params) -> None:
    from portfolio import PortfolioRiskConfig

    df = sine_ohlcv.copy()
    base = replace(fresh_params, bars=len(df), strategy="ema_crossover")
    out = run_multi_strategy_portfolio(
        base,
        {"ema_crossover": 0.5, "rsi_mean_reversion": 0.5},
        risk=PortfolioRiskConfig(
            risk_budget_overrides={"ema_crossover": 0.8, "rsi_mean_reversion": 0.2},
            correlation_groups={"ema_crossover": "trend", "rsi_mean_reversion": "mr"},
            max_positions_per_group=1,
        ),
        df=df,
        use_cache=False,
        verbose=False,
    )
    assert "risk_budget_weights" in out
    assert out["risk_config"]["max_positions_per_group"] == 1
