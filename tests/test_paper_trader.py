"""
Tests for PaperTrader accounting, cooldown, and override handling.

These are the invariants the rest of the codebase depends on:
  - balance == initial + sum(trade.profit) for all closed trades
  - open/close are idempotent with respect to same-side signals
  - cooldown blocks new entries while FLAT, doesn't block while in-position
  - size_override / stop_override / take_override take precedence
"""
from __future__ import annotations

import pytest

from paper_trader import PaperTrader


def _t(balance=1000.0, **kw) -> PaperTrader:
    return PaperTrader(initial_balance=balance, fee_pct=0.0, **kw)


class TestOpenClose:
    def test_open_long_then_close_at_higher_price_profits(self):
        t = _t()
        t.on_signal("BUY", 100.0)
        assert t.position == "LONG"
        assert t.position_size == pytest.approx(10.0)  # 1000 * 1.0 / 100
        t.close(110.0, reason="test")
        assert t.position is None
        assert t.balance == pytest.approx(1100.0)  # +100 profit
        assert len(t.trade_log) == 1
        assert t.trade_log[0]["profit"] == pytest.approx(100.0)

    def test_open_short_then_close_at_lower_price_profits(self):
        t = _t()
        t.on_signal("SELL", 100.0)
        assert t.position == "SHORT"
        t.close(90.0, reason="test")
        assert t.balance == pytest.approx(1100.0)

    def test_same_side_signal_is_noop(self):
        t = _t()
        t.on_signal("BUY", 100.0)
        first_entry = t.entry_price
        t.on_signal("BUY", 105.0)
        # Still in original long, not re-opened at 105.
        assert t.position == "LONG"
        assert t.entry_price == first_entry

    def test_reversal_closes_but_does_not_flip_same_bar(self):
        """Belt-and-suspenders: reversal only closes; next bar is free to
        open the opposite side. This prevents flip-flop on one noisy bar."""
        t = _t()
        t.on_signal("BUY", 100.0)
        t.on_signal("SELL", 110.0)
        assert t.position is None
        assert t.balance == pytest.approx(1100.0)

    def test_balance_equals_initial_plus_sum_of_profits(self):
        """Core accounting invariant used by runs._derive_summary."""
        t = _t()
        t.on_signal("BUY", 100.0)
        t.close(105.0)
        t.on_signal("SELL", 110.0)
        t.close(100.0)
        total = sum(trade["profit"] for trade in t.trade_log)
        assert t.balance == pytest.approx(t.initial_balance + total)


class TestStopTake:
    def test_long_hits_stop_loss(self):
        t = _t(stop_loss_pct=0.02, take_profit_pct=0.10)
        t.on_signal("BUY", 100.0)
        t.on_tick(97.0)  # below 98 stop
        assert t.position is None
        assert t.trade_log[-1]["reason"] == "stop_loss"

    def test_long_hits_take_profit(self):
        t = _t(stop_loss_pct=0.10, take_profit_pct=0.02)
        t.on_signal("BUY", 100.0)
        t.on_tick(103.0)  # above 102 TP
        assert t.position is None
        assert t.trade_log[-1]["reason"] == "take_profit"
        assert t.trade_log[-1]["exit"] == pytest.approx(102.0)

    def test_long_stop_uses_intrabar_low_not_close(self):
        """Wick through stop closes at stop level even if mark (close) is safe."""
        t = _t(stop_loss_pct=0.02, take_profit_pct=0.10)
        t.on_signal("BUY", 100.0)
        t.on_tick(99.5, high=100.0, low=97.0)  # close 99.5 but low hit 98 stop
        assert t.position is None
        assert t.trade_log[-1]["reason"] == "stop_loss"
        assert t.trade_log[-1]["exit"] == pytest.approx(98.0)

    def test_short_hits_stop_loss_above(self):
        t = _t(stop_loss_pct=0.02, take_profit_pct=0.10)
        t.on_signal("SELL", 100.0)
        t.on_tick(103.0)  # above 102 stop (shorts stop UP)
        assert t.position is None
        assert t.trade_log[-1]["reason"] == "stop_loss"


class TestCooldown:
    def test_cooldown_blocks_reentry_while_flat(self):
        t = _t(entry_cooldown_bars=3)
        t.on_signal("BUY", 100.0)
        t.close(105.0)
        # Cooldown armed. Next signal must be blocked.
        t.on_signal("BUY", 106.0)
        assert t.position is None
        assert t.skipped_by_cooldown == 1

    def test_cooldown_expires_after_n_ticks(self):
        t = _t(entry_cooldown_bars=2)
        t.on_signal("BUY", 100.0)
        t.close(105.0)
        # While flat, each on_tick decrements cooldown.
        t.on_tick(105.0)
        t.on_tick(105.0)
        t.on_signal("BUY", 106.0)
        assert t.position == "LONG"

    def test_cooldown_does_not_apply_while_in_position(self):
        t = _t(entry_cooldown_bars=5)
        t.on_signal("BUY", 100.0)
        # Reversing should still close even though cooldown would block an entry.
        t.on_signal("SELL", 110.0)
        assert t.position is None
        assert t.skipped_by_cooldown == 0


class TestOverrides:
    def test_size_override_overrides_allocation_pct(self):
        t = _t(balance=1000.0)
        t.on_signal("BUY", 100.0, size_override=3.0)
        assert t.position_size == pytest.approx(3.0)

    def test_stop_and_take_overrides_bypass_pct_defaults(self):
        t = _t(stop_loss_pct=0.02, take_profit_pct=0.04)
        t.on_signal(
            "BUY",
            100.0,
            size_override=1.0,
            stop_override=95.0,
            take_override=115.0,
        )
        assert t.stop_price == 95.0
        assert t.take_price == 115.0

    def test_overrides_ignored_when_size_non_positive(self):
        t = _t()
        t.on_signal("BUY", 100.0, size_override=0.0)
        assert t.position is None  # refused to open


class TestMarkToMarket:
    def test_mtm_while_long(self):
        t = _t()
        t.on_signal("BUY", 100.0)
        # size = 10, price +2 → unrealized +20
        assert t.mark_to_market(102.0) == pytest.approx(t.balance + 20.0)

    def test_mtm_flat_is_just_balance(self):
        t = _t()
        assert t.mark_to_market(9999.0) == pytest.approx(t.balance)


class TestSlippage:
    def test_long_entry_pays_adverse_slip(self):
        t = _t(slippage_pct=0.01)
        t.on_signal("BUY", 100.0)
        assert t.entry_price == pytest.approx(101.0)
        assert t.position_size == pytest.approx(1000.0 / 101.0)

    def test_half_spread_bps_long_entry_additive(self):
        t = PaperTrader(
            fee_pct=0.0,
            slippage_pct=0.0,
            half_spread_bps=10.0,
        )
        # 10 bps adverse on a long ⇒ +0.10% on fill price.
        t.on_signal("BUY", 100.0)
        assert t.entry_price == pytest.approx(100.1)

    def test_half_spread_bps_stacks_with_slippage_pct(self):
        # 50 bps (=0.5%) + proportional 0.5% ⇒ +1.0% on fill.
        t = PaperTrader(
            fee_pct=0.0, slippage_pct=0.005, half_spread_bps=50.0
        )
        t.on_signal("BUY", 100.0)
        assert t.entry_price == pytest.approx(101.0)

    def test_slippage_atr_mult_adds_atr_frac_of_price_long(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.0,
            slippage_pct=0.0,
            slippage_atr_mult=1.0,
        )
        t.on_signal("BUY", 100.0, atr=2.0)
        assert t.entry_price == pytest.approx(102.0)


class TestIntrabarSlTpConflict:
    def test_long_both_touch_stop_first_policy(self):
        t = PaperTrader(
            fee_pct=0.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            intrabar_sl_tp_policy="stop_first",
        )
        t.on_signal("BUY", 100.0)
        t.on_tick(100.0, high=105.0, low=97.0)
        assert t.trade_log[-1]["reason"] == "stop_loss"

    def test_long_both_touch_take_first_policy(self):
        t = PaperTrader(
            fee_pct=0.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            intrabar_sl_tp_policy="take_first",
        )
        t.on_signal("BUY", 100.0)
        t.on_tick(100.0, high=105.0, low=97.0)
        assert t.trade_log[-1]["reason"] == "take_profit"

    def test_short_both_touch_take_first_policy(self):
        t = PaperTrader(
            fee_pct=0.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            intrabar_sl_tp_policy="take_first",
        )
        t.on_signal("SELL", 100.0)
        t.on_tick(100.0, high=103.0, low=95.0)
        assert t.trade_log[-1]["reason"] == "take_profit"

    def test_random_policy_is_seeded_repeatable(self):
        reasons = []
        for _ in range(3):
            t = PaperTrader(
                fee_pct=0.0,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                intrabar_sl_tp_policy="random",
                intrabar_random_seed=999,
                verbose=False,
            )
            t.on_signal("BUY", 100.0)
            t.on_tick(100.0, high=105.0, low=97.0)
            reasons.append(t.trade_log[-1]["reason"])
        assert len(set(reasons)) == 1

    def test_invalid_intrabar_policy_raises(self):
        with pytest.raises(ValueError):
            PaperTrader(intrabar_sl_tp_policy="wrong")


class TestFunding:
    def test_long_pays_positive_funding_rate(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.0,
            enable_funding=True,
            funding_rate_bps=10.0,
            funding_interval_hours=8,
            verbose=False,
        )
        t.on_signal("BUY", 100.0, timestamp="2026-01-01T00:00:00Z")
        # After one 8h interval: notional ~= 1000, rate=0.1% => -1.0 for long.
        t.on_tick(100.0, timestamp="2026-01-01T08:00:00Z")
        assert t.cumulative_funding == pytest.approx(-1.0, rel=1e-3)
        assert t.balance == pytest.approx(999.0, rel=1e-3)

    def test_short_receives_positive_funding_rate(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.0,
            enable_funding=True,
            funding_rate_bps=10.0,
            funding_interval_hours=8,
            verbose=False,
        )
        t.on_signal("SELL", 100.0, timestamp="2026-01-01T00:00:00Z")
        t.on_tick(100.0, timestamp="2026-01-01T08:00:00Z")
        assert t.cumulative_funding == pytest.approx(1.0, rel=1e-3)
        assert t.balance == pytest.approx(1001.0, rel=1e-3)

    def test_funding_applies_multiple_intervals(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.0,
            enable_funding=True,
            funding_rate_bps=5.0,
            funding_interval_hours=8,
            verbose=False,
        )
        t.on_signal("BUY", 100.0, timestamp="2026-01-01T00:00:00Z")
        # 24h = 3 intervals, each 0.05% of ~1000 => 0.5; long pays => -1.5
        t.on_tick(100.0, timestamp="2026-01-02T00:00:00Z")
        assert t.cumulative_funding == pytest.approx(-1.5, rel=1e-3)


class TestExecutionComposition:
    def test_long_cost_stack_and_funding_with_same_bar_conflict(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.001,
            slippage_pct=0.001,
            half_spread_bps=10.0,
            intrabar_sl_tp_policy="stop_first",
            stop_loss_pct=0.02,
            take_profit_pct=0.03,
            enable_funding=True,
            funding_rate_bps=8.0,
            funding_interval_hours=8,
            verbose=False,
        )
        t.on_signal("BUY", 100.0, timestamp="2026-01-01T00:00:00Z")
        # High/low touch both brackets; policy forces stop-first close.
        t.on_tick(
            100.0,
            timestamp="2026-01-01T08:00:00Z",
            high=104.0,
            low=96.0,
        )
        assert t.trade_log[-1]["reason"] == "stop_loss"
        assert t.cumulative_funding < 0.0
        trade_total = sum(x["profit"] for x in t.trade_log)
        assert t.balance == pytest.approx(
            t.initial_balance + trade_total + t.cumulative_funding, rel=1e-9
        )

    def test_short_cost_stack_and_funding_with_same_bar_conflict(self):
        t = PaperTrader(
            initial_balance=1000.0,
            fee_pct=0.001,
            slippage_pct=0.001,
            half_spread_bps=10.0,
            intrabar_sl_tp_policy="take_first",
            stop_loss_pct=0.02,
            take_profit_pct=0.03,
            enable_funding=True,
            funding_rate_bps=8.0,
            funding_interval_hours=8,
            verbose=False,
        )
        t.on_signal("SELL", 100.0, timestamp="2026-01-01T00:00:00Z")
        # Both touched; policy forces take-first close.
        t.on_tick(
            100.0,
            timestamp="2026-01-01T08:00:00Z",
            high=104.0,
            low=95.0,
        )
        assert t.trade_log[-1]["reason"] == "take_profit"
        assert t.cumulative_funding > 0.0
        trade_total = sum(x["profit"] for x in t.trade_log)
        assert t.balance == pytest.approx(
            t.initial_balance + trade_total + t.cumulative_funding, rel=1e-9
        )


class TestCircuitBreaker:
    def test_halts_new_entries_after_consecutive_losses(self):
        t = _t(max_consecutive_losses=2)
        t.on_signal("BUY", 100.0)
        t.close(99.0)  # loss
        t.on_signal("BUY", 100.0)
        t.close(99.0)  # second loss, halt
        assert t._trading_halted
        t.on_signal("BUY", 100.0)
        assert t.position is None
        assert t.skipped_by_circuit == 1
