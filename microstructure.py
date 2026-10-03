"""Live market microstructure helpers (spread / liquidity proxies).

Backtests use static ``half_spread_bps`` on ``PaperTrader``; this module
supports *live* paper steps with real bid/ask from the exchange ticker.
"""
from __future__ import annotations

from typing import Any, Optional


def spread_bps_from_bid_ask(bid: float, ask: float) -> Optional[float]:
    """Full bid–ask spread in basis points vs mid. None if inputs invalid."""
    b, a = float(bid), float(ask)
    if b <= 0 or a <= 0 or a < b:
        return None
    mid = (b + a) / 2.0
    if mid <= 0:
        return None
    return (a - b) / mid * 10_000.0


def spread_bps_from_ticker(ticker: dict[str, Any]) -> Optional[float]:
    """Parse ccxt ``fetch_ticker`` result into spread bps."""
    bid = ticker.get("bid")
    ask = ticker.get("ask")
    if bid is None or ask is None:
        return None
    return spread_bps_from_bid_ask(float(bid), float(ask))


def fetch_spread_bps(exchange, symbol: str) -> Optional[float]:
    """Best-effort live spread; returns None on missing bid/ask or API errors."""
    try:
        ticker = exchange.fetch_ticker(symbol)
    except Exception:
        return None
    if not isinstance(ticker, dict):
        return None
    return spread_bps_from_ticker(ticker)


def apply_spread_entry_gate(
    signal: str,
    spread_bps: Optional[float],
    max_spread_bps: float,
    *,
    position: str | None,
) -> tuple[str, bool]:
    """Block *new* entries when spread is too wide.

    Returns ``(effective_signal, blocked)``. Closing an open leg (SELL while
    LONG, BUY while SHORT) is never gated; only flat → open attempts are.
    """
    cap = float(max_spread_bps)
    if cap <= 0 or signal not in ("BUY", "SELL"):
        return signal, False
    if position == "LONG" and signal == "SELL":
        return signal, False
    if position == "SHORT" and signal == "BUY":
        return signal, False
    if position is not None:
        return signal, False
    if spread_bps is None:
        return "HOLD", True
    if float(spread_bps) > cap:
        return "HOLD", True
    return signal, False
