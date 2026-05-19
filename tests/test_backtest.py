"""
Tests for backtest.py internals: summary math, ATR overrides, and
replay_on_df smoke.

We deliberately craft trade dicts by hand for the stats functions so we
know the expected values exactly, rather than relying on a strategy's
output.
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from backtest import (
    Params,
    _atr_overrides,
    _max_drawdown_pct,
    _profit_factor,
    _summary,
    _trade_sharpe,
    replay_on_df,
)
from paper_trader import PaperTrader


# --------------------------------------------------------------- summary ---

def _trade(profit: float, **extra) -> dict:
    """Minimal trade dict matching PaperTrader.close()'s schema."""
    return {
        "profit": profit,
        "gross_profit": profit,
        "fee": 0.0,
        "reason": extra.pop("reason", "signal"),
        **extra,
    }


class TestProfitFactor:
    def test_no_losses_and_wins_returns_inf(self):
        trades = [_trade(10.0), _trade(5.0)]
        assert _profit_factor(trades) == float("inf")

    def test_no_trades_returns_zero(self):
        assert _profit_factor([]) == 0.0

    def test_balanced_wins_and_losses(self):
        trades = [_trade(30.0), _trade(-10.0), _trade(10.0)]
        # 40 / 10 = 4.0
        assert _profit_factor(trades) == pytest.approx(4.0)


class TestTradeSharpe:
    def test_too_few_trades_returns_zero(self):
        assert _trade_sharpe([_trade(5.0)], initial=1000.0) == 0.0

    def test_zero_initial_is_guarded(self):
        assert _trade_sharpe([_trade(1), _trade(2)], initial=0.0) == 0.0

    def test_identical_trades_give_zero_variance(self):
        """Zero stdev should return 0, not divide-by-zero."""
        trades = [_trade(10.0), _trade(10.0), _trade(10.0)]
        assert _trade_sharpe(trades, initial=1000.0) == 0.0

    def test_positive_sharpe_for_mixed_positive_trades(self):
        trades = [_trade(10.0), _trade(20.0), _trade(15.0)]
        assert _trade_sharpe(trades, initial=1000.0) > 0.0


class TestMaxDrawdown:
    def test_monotonic_up_series_is_zero_dd(self):
        eq = [{"balance": b} for b in [1000, 1010, 1050, 1100]]
        assert _max_drawdown_pct(eq) == 0.0

    def test_peak_to_trough_measured_against_prior_peak(self):
        # Peak 1200, trough 900 → 25% DD.
        eq = [{"balance": b} for b in [1000, 1200, 900, 1100]]
        assert _max_drawdown_pct(eq) == pytest.approx(25.0)

    def test_drawdown_only_counts_after_peak(self):
        # First bar 1000 is the opening peak → dip to 900 is 10%.
        eq = [{"balance": b} for b in [1000, 900, 1100]]
        assert _max_drawdown_pct(eq) == pytest.approx(10.0)


class TestSummaryShape:
    """_summary must return the exact key set that the frontend + runs
    store depend on — a missing field silently becomes 0 in the UI."""

    REQUIRED_KEYS = {
        "trades",
        "balance",
        "return_pct",
        "profit_factor",
        "trade_sharpe",
        "max_drawdown_pct",
        "timeframe",
        "bars",
    }

    def test_no_trades_has_required_keys(self):
        t = PaperTrader(initial_balance=1000.0, fee_pct=0.0)
        out = _summary(t, Params(), start=0, end=100)
        assert self.REQUIRED_KEYS.issubset(out.keys())
        assert out["trades"] == 0

    def test_with_trades_extends_required_keys(self):
        t = PaperTrader(initial_balance=1000.0, fee_pct=0.0)
        t.on_signal("BUY", 100.0)
        t.close(110.0, reason="take_profit")
        t.on_signal("SELL", 100.0)
        t.close(105.0, reason="stop_loss")
        out = _summary(t, Params(), start=0, end=100)
        extras = {
            "wins",
            "losses",
            "win_rate",
            "total_pnl",
            "avg_trade_pnl",
            "reasons",
            "skipped_by_cooldown",
        }
        assert (self.REQUIRED_KEYS | extras).issubset(out.keys())
        assert out["trades"] == 2
        # reasons dict should count both SL and TP once.
        assert out["reasons"]["take_profit"] == 1
        assert out["reasons"]["stop_loss"] == 1

    def test_profit_factor_is_clamped_not_inf(self):
        """JSON can't serialize inf; _summary must clamp to 999."""
        t = PaperTrader(initial_balance=1000.0, fee_pct=0.0)
        t.on_signal("BUY", 100.0)
        t.close(110.0)
        out = _summary(t, Params(), start=0, end=100)
        assert out["profit_factor"] == 999.0  # no losses → clamped

    def test_summary_reports_funding_separately(self):
        t = PaperTrader(initial_balance=1000.0, fee_pct=0.0)
        t.on_signal("BUY", 100.0)
        t.close(110.0)
        t.cumulative_funding = -2.5
        out = _summary(t, Params(), start=0, end=100)
        assert out["funding_pnl"] == pytest.approx(-2.5)
        assert out["total_pnl"] == pytest.approx(97.5)


# -------------------------------------------------------- _atr_overrides ---

class _Bar(dict):
    """A dict that mimics a pandas Series well enough for _atr_overrides."""
    def get(self, k, default=None):
        return super().get(k, default)


def _trader(balance=1000.0) -> PaperTrader:
    return PaperTrader(initial_balance=balance, fee_pct=0.0)


def _atr_params(**kw) -> Params:
    return replace(
        Params(),
        use_atr_sizing=True,
        atr_risk_pct=0.01,
        atr_stop_mult=2.0,
        atr_tp_mult=3.0,
        **kw,
    )


class TestAtrOverrides:
    def test_disabled_when_use_atr_sizing_false(self):
        # Explicit opt-out — the project-wide default in config.py is now ATR-on,
        # so we can't rely on the Params() default to assert the "disabled" path.
        params = Params(use_atr_sizing=False)
        out = _atr_overrides("BUY", 100.0, _Bar(atr=2.0), _trader(), params)
        assert out == {}

    def test_hold_signal_returns_empty(self):
        out = _atr_overrides("HOLD", 100.0, _Bar(atr=2.0), _trader(), _atr_params())
        assert out == {}

    def test_missing_atr_returns_empty(self):
        bar = _Bar(atr=None)
        out = _atr_overrides("BUY", 100.0, bar, _trader(), _atr_params())
        assert out == {}

    def test_nan_atr_returns_empty(self):
        bar = _Bar(atr=float("nan"))
        out = _atr_overrides("BUY", 100.0, bar, _trader(), _atr_params())
        assert out == {}

    def test_buy_long_stop_below_take_above(self):
        """Long: SL = entry - 2*ATR, TP = entry + 3*ATR, size = risk/stop_dist."""
        out = _atr_overrides(
            "BUY", 100.0, _Bar(atr=2.0), _trader(balance=1000.0), _atr_params()
        )
        # risk = 1000 * 0.01 = 10; stop_dist = 2*2 = 4 → size = 2.5
        assert out["size_override"] == pytest.approx(2.5)
        assert out["stop_override"] == pytest.approx(96.0)
        assert out["take_override"] == pytest.approx(106.0)

    def test_sell_short_stop_above_take_below(self):
        out = _atr_overrides(
            "SELL", 100.0, _Bar(atr=2.0), _trader(balance=1000.0), _atr_params()
        )
        assert out["stop_override"] == pytest.approx(104.0)
        assert out["take_override"] == pytest.approx(94.0)


# -------------------------------------------------------- replay smoke ---

class TestReplayOnDf:
    def test_raises_when_history_shorter_than_warmup(self, ohlcv):
        """Guard the backend from producing a silently-empty run. The live
        bot manager relies on this behavior — without it, a mistimed
        --bars flag would yield a run with 0 trades and 0 everything."""
        df = ohlcv([100.0] * 10)
        with pytest.raises(ValueError, match="warm-up"):
            replay_on_df(df, Params(bars=10))

    def test_sine_run_is_deterministic(self, sine_ohlcv, fresh_params, tmp_path):
        """Running the same inputs twice must produce identical summaries.

        Catches any hidden stateful globals or RNG creeping into the hot path.
        """
        params = replace(fresh_params, strategy="rsi_mean_reversion", bars=300)
        out_a = replay_on_df(
            sine_ohlcv.copy(), params,
            data_file=str(tmp_path / "a.json"), verbose=False,
        )
        out_b = replay_on_df(
            sine_ohlcv.copy(), params,
            data_file=str(tmp_path / "b.json"), verbose=False,
        )
        # Only compare fields that are scalar — `reasons` is a dict.
        for k in ("trades", "balance", "return_pct", "max_drawdown_pct"):
            assert out_a[k] == out_b[k], f"{k} diverged: {out_a[k]} vs {out_b[k]}"
