from __future__ import annotations

from backtest import Params, apply_full_indicators, replay_on_df
from regime import attach_regime_columns, strategy_regime_expectancy


def test_attach_regime_columns_adds_expected_fields(sine_ohlcv):
    out = attach_regime_columns(sine_ohlcv.copy())
    for k in ("regime_trend", "regime_vol", "regime_micro", "regime"):
        assert k in out.columns
    assert out["regime"].astype(str).str.contains(r"\|").any()


def test_strategy_regime_expectancy_returns_rows(sine_ohlcv):
    p = Params(
        strategy="rsi_mean_reversion",
        bars=300,
        fee_pct=0.0,
        use_atr_sizing=False,
    )
    out = strategy_regime_expectancy(
        base_params=p,
        strategy_names=["rsi_mean_reversion", "ema_crossover"],
        df_raw=sine_ohlcv.copy(),
        apply_full_indicators_fn=apply_full_indicators,
        replay_on_df_fn=replay_on_df,
    )
    assert out["strategies"] == ["ema_crossover", "rsi_mean_reversion"]
    assert isinstance(out["regimes"], list)
    assert isinstance(out["rows"], list)
    if out["rows"]:
        row = out["rows"][0]
        assert "strategy" in row
        assert "regime" in row
        assert "expectancy_pct" in row
