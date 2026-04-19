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
