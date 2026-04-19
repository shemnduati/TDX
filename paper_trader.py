"""
PaperTrader with long/short support, position sizing, and bracket risk
management (stop-loss + take-profit).

Accounting model (simple, common for paper trading):

- `balance` is realized cash.
- Opening a position does NOT change balance; we just record entry + size.
- On close, realized P&L is added to balance:
    LONG  P&L = (exit - entry) * size
    SHORT P&L = (entry - exit) * size
- Unrealized P&L is computed on every tick for mark-to-market equity.

Every tick the bot calls `on_tick(price)`, which:
  1. Checks stop / take-profit and closes if hit.
  2. Appends a mark-to-market point to the equity curve.
  3. Persists to disk (unless a deferred save is active, used by the backtester).
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data.json"
)

# Cap equity-history length so the JSON file stays bounded over long runs.
MAX_EQUITY_POINTS = 5000


class PaperTrader:
    def __init__(
        self,
        initial_balance: float = 1000,
        allocation_pct: float = 1.0,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        entry_cooldown_bars: int = 0,
        fee_pct: float = 0.0,
        data_file: Optional[str] = None,
    ):
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.allocation_pct = float(allocation_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.take_profit_pct = float(take_profit_pct)
        self.entry_cooldown_bars = int(entry_cooldown_bars)
        self.fee_pct = float(fee_pct)  # per-side taker fee (e.g. 0.001 = 0.1%)
        self.data_file = data_file or DEFAULT_DATA_FILE

        self.position: Optional[str] = None   # "LONG" | "SHORT" | None
        self.entry_price: float = 0.0
        self.position_size: float = 0.0       # units of base asset
        self.stop_price: float = 0.0
        self.take_price: float = 0.0
        self.opened_at: Optional[str] = None

        # Cooldown only counts while FLAT; each on_tick() while FLAT decrements it.
        self._cooldown_remaining: int = 0
        self.skipped_by_cooldown: int = 0

        self.trade_log: list[dict] = []
        self.equity_history: list[dict] = [
            {
                "timestamp": self._now(),
                "balance": float(initial_balance),
                "realized": True,
            }
        ]

        self._deferred_save = False
        self.save_data()

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _ts(self, timestamp) -> str:
        """Accept pandas Timestamp / datetime / str / None."""
        if timestamp is None:
            return self._now()
        if isinstance(timestamp, str):
            return timestamp
        try:
            return timestamp.isoformat()
        except AttributeError:
            return str(timestamp)

    @contextmanager
    def batch(self):
        """Defer `save_data()` until the block exits (used by the backtester
        to avoid writing JSON on every bar)."""
        self._deferred_save = True
        try:
            yield
        finally:
            self._deferred_save = False
            self.save_data()

    # ---------------------------------------------------------------- equity
    def unrealized_pnl(self, price: float) -> float:
        if self.position is None:
            return 0.0
        if self.position == "LONG":
            return (price - self.entry_price) * self.position_size
        if self.position == "SHORT":
            return (self.entry_price - price) * self.position_size
        return 0.0

    def mark_to_market(self, price: float) -> float:
        return self.balance + self.unrealized_pnl(price)

    def _append_equity(self, balance: float, realized: bool, timestamp=None):
        self.equity_history.append(
            {
                "timestamp": self._ts(timestamp),
                "balance": float(balance),
                "realized": realized,
            }
        )
        if len(self.equity_history) > MAX_EQUITY_POINTS:
            self.equity_history = (
                self.equity_history[:1]
                + self.equity_history[-(MAX_EQUITY_POINTS - 1):]
            )

    # --------------------------------------------------------------- persist
    def save_data(self):
        if self._deferred_save:
            return
        data = {
            "initial_balance": self.initial_balance,
            "balance": self.balance,
            "position": self.position,
            "entry_price": self.entry_price,
            "position_size": self.position_size,
            "stop_price": self.stop_price,
            "take_price": self.take_price,
            "trades": self.trade_log,
            "equity_history": self.equity_history,
            "updated_at": self._now(),
            "config": {
                "allocation_pct": self.allocation_pct,
                "stop_loss_pct": self.stop_loss_pct,
                "take_profit_pct": self.take_profit_pct,
                "entry_cooldown_bars": self.entry_cooldown_bars,
                "fee_pct": self.fee_pct,
            },
            "cooldown_remaining": self._cooldown_remaining,
        }
        with open(self.data_file, "w") as f:
            json.dump(data, f, indent=4)

    # --------------------------------------------------------- position mgmt
    def _open(
        self,
        side: str,
        price: float,
        timestamp=None,
        *,
        size_override: Optional[float] = None,
        stop_override: Optional[float] = None,
        take_override: Optional[float] = None,
    ):
        if price <= 0:
            return

        if size_override is not None:
            size = float(size_override)
        else:
            notional = self.balance * self.allocation_pct
            if notional <= 0:
                return
            size = notional / float(price)

        if size <= 0:
            return

        self.position = side
        self.entry_price = float(price)
        self.position_size = size
        self.opened_at = self._ts(timestamp)

        if stop_override is not None:
            self.stop_price = float(stop_override)
        elif side == "LONG":
            self.stop_price = price * (1 - self.stop_loss_pct)
        else:
            self.stop_price = price * (1 + self.stop_loss_pct)

        if take_override is not None:
            self.take_price = float(take_override)
        elif side == "LONG":
            self.take_price = price * (1 + self.take_profit_pct)
        else:
            self.take_price = price * (1 - self.take_profit_pct)

        print(
            f"OPEN {side} @ {price:.2f} "
            f"size={self.position_size:.6f} "
            f"SL={self.stop_price:.2f} TP={self.take_price:.2f}"
        )
        self.save_data()

    def close(self, price: float, reason: str = "signal", timestamp=None):
        if self.position is None:
            return

        gross_pnl = self.unrealized_pnl(price)
        # Taker fee charged on both entry and exit notionals.
        fee = (
            self.entry_price * self.position_size * self.fee_pct
            + float(price) * self.position_size * self.fee_pct
        )
        net_pnl = gross_pnl - fee
        self.balance += net_pnl

        trade = {
            "timestamp": self._ts(timestamp),
            "opened_at": self.opened_at,
            "side": self.position,
            "entry": self.entry_price,
            "exit": float(price),
            "size": self.position_size,
            "gross_profit": gross_pnl,
            "fee": fee,
            "profit": net_pnl,
            "reason": reason,
        }
        self.trade_log.append(trade)
        self._append_equity(self.balance, realized=True, timestamp=timestamp)

        print(
            f"CLOSE {self.position} @ {price:.2f} "
            f"pnl={net_pnl:+.2f} (gross {gross_pnl:+.2f}, fee {fee:.2f}) "
            f"reason={reason} balance={self.balance:.2f}"
        )

        self.position = None
        self.entry_price = 0.0
        self.position_size = 0.0
        self.stop_price = 0.0
        self.take_price = 0.0
        self.opened_at = None
        self._cooldown_remaining = self.entry_cooldown_bars
        self.save_data()

    # ------------------------------------------------------------------ API
    def _entry_blocked_by_cooldown(self) -> bool:
        if self.position is not None:
            return False  # Cooldown only applies when FLAT.
        return self._cooldown_remaining > 0

    def on_signal(
        self,
        signal: str,
        price: float,
        timestamp=None,
        *,
        size_override: Optional[float] = None,
        stop_override: Optional[float] = None,
        take_override: Optional[float] = None,
    ):
        """Called by the bot / backtester when the strategy emits a signal.

        The optional *_override kwargs let an ATR-sizing layer specify an
        exact position size and SL/TP levels instead of the default pct-of-
        balance sizing and pct stop/take distances.
        """
        kw = dict(
            timestamp=timestamp,
            size_override=size_override,
            stop_override=stop_override,
            take_override=take_override,
        )
        if signal == "BUY":
            if self.position == "LONG":
                return
            if self.position == "SHORT":
                # Reversal: close the short. Cooldown begins; we do NOT open
                # the long on the same bar. This prevents the strategy from
                # flip-flopping on a single wobble.
                self.close(price, reason="reverse", timestamp=timestamp)
                return
            if self._entry_blocked_by_cooldown():
                self.skipped_by_cooldown += 1
                return
            self._open("LONG", price, **kw)
        elif signal == "SELL":
            if self.position == "SHORT":
                return
            if self.position == "LONG":
                self.close(price, reason="reverse", timestamp=timestamp)
                return
            if self._entry_blocked_by_cooldown():
                self.skipped_by_cooldown += 1
                return
            self._open("SHORT", price, **kw)
        # HOLD: no-op

    def on_tick(self, price: float, timestamp=None):
        """Called every loop iteration. Enforces SL/TP, ticks the cooldown,
        and records mark-to-market equity."""
        price = float(price)

        if self.position == "LONG":
            if price <= self.stop_price:
                self.close(price, reason="stop_loss", timestamp=timestamp)
            elif price >= self.take_price:
                self.close(price, reason="take_profit", timestamp=timestamp)
        elif self.position == "SHORT":
            if price >= self.stop_price:
                self.close(price, reason="stop_loss", timestamp=timestamp)
            elif price <= self.take_price:
                self.close(price, reason="take_profit", timestamp=timestamp)

        # Cooldown decrements once per tick while FLAT.
        if self.position is None and self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        self._append_equity(
            self.mark_to_market(price),
            realized=False,
            timestamp=timestamp,
        )
        self.save_data()

    # -------------------------------------------------------------- logging
    def status(self, current_price: float):
        print(
            f"Balance: {self.balance:.2f} "
            f"| MTM: {self.mark_to_market(current_price):.2f} "
            f"| Position: {self.position or 'FLAT'} "
            f"| Price: {current_price}"
        )
