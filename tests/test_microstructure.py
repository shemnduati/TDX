from __future__ import annotations

import pytest

from microstructure import (
    apply_spread_entry_gate,
    spread_bps_from_bid_ask,
    spread_bps_from_ticker,
)


def test_spread_bps_from_bid_ask():
    # mid 100, spread 0.10 => 10 bps
    assert spread_bps_from_bid_ask(99.95, 100.05) == pytest.approx(10.0)


def test_spread_bps_from_ticker():
    assert spread_bps_from_ticker({"bid": 99.95, "ask": 100.05}) == pytest.approx(
        10.0
    )


def test_spread_gate_off():
    sig, blocked = apply_spread_entry_gate("BUY", 50.0, 0.0, position=None)
    assert sig == "BUY" and blocked is False


def test_spread_gate_blocks_flat_entry():
    sig, blocked = apply_spread_entry_gate("BUY", 25.0, 20.0, position=None)
    assert sig == "HOLD" and blocked is True


def test_spread_gate_allows_exit_long():
    sig, blocked = apply_spread_entry_gate("SELL", 999.0, 1.0, position="LONG")
    assert sig == "SELL" and blocked is False


def test_spread_gate_allows_exit_short():
    sig, blocked = apply_spread_entry_gate("BUY", 999.0, 1.0, position="SHORT")
    assert sig == "BUY" and blocked is False
