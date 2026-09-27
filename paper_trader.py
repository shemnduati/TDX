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

Every tick the bot calls `on_tick`, which:
  1. Checks stop / take-profit using the bar's high and low when provided
     (backtests); otherwise the single `mark_price` (typically close) is used
     for both.
  2. Appends a mark-to-market point at `mark_price`.
  3. Persists to disk (unless a deferred save is active, used by the backtester).
"""
import json
import os
import random
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

_INTRABAR_POLICIES = frozenset({"stop_first", "take_first", "random"})

import pandas as pd

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
        *,
        slippage_pct: float = 0.0,
        slippage_atr_mult: float = 0.0,
        half_spread_bps: float = 0.0,
        intrabar_sl_tp_policy: str = "stop_first",
        intrabar_random_seed: Optional[int] = 42,
        use_trailing_stop: bool = False,
        trailing_stop_pct: float = 0.015,
        max_consecutive_losses: int = 0,
        max_daily_loss_pct: float = 0.0,
        enable_funding: bool = False,
        funding_rate_bps: float = 0.0,
        funding_interval_hours: int = 8,
        verbose: bool = True,
    ):
        pol = intrabar_sl_tp_policy.strip().lower()
        if pol not in _INTRABAR_POLICIES:
            raise ValueError(
                f"intrabar_sl_tp_policy must be one of {sorted(_INTRABAR_POLICIES)}, "
                f"got {intrabar_sl_tp_policy!r}"
            )

        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.allocation_pct = float(allocation_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.take_profit_pct = float(take_profit_pct)
        self.entry_cooldown_bars = int(entry_cooldown_bars)
        self.fee_pct = float(fee_pct)  # per-side taker fee (e.g. 0.001 = 0.1%)
        self.data_file = data_file or DEFAULT_DATA_FILE
        self.slippage_pct = float(slippage_pct)
        self.slippage_atr_mult = float(slippage_atr_mult)
        self.half_spread_bps = max(0.0, float(half_spread_bps))
        self.intrabar_sl_tp_policy = pol
        self.verbose = bool(verbose)
        self.use_trailing_stop = bool(use_trailing_stop)
        self.trailing_stop_pct = float(trailing_stop_pct)
        self.max_consecutive_losses = int(max_consecutive_losses)
        self.max_daily_loss_pct = float(max_daily_loss_pct)
        self.enable_funding = bool(enable_funding)
        self.funding_rate_bps = float(funding_rate_bps)
        self.funding_interval_hours = max(1, int(funding_interval_hours))
        self._intrabar_rng = (
            random.Random(intrabar_random_seed)
            if intrabar_random_seed is not None
            else random.SystemRandom()
        )

        self.position: Optional[str] = None   # "LONG" | "SHORT" | None
        self.entry_price: float = 0.0
        self.position_size: float = 0.0       # units of base asset
        self.stop_price: float = 0.0
        self.take_price: float = 0.0
        self.opened_at: Optional[str] = None
        self._trail_extreme: float = 0.0  # best high (long) / best low (short)

        # Cooldown only counts while FLAT; each on_tick() while FLAT decrements it.
        self._cooldown_remaining: int = 0
        self.skipped_by_cooldown: int = 0
        self.skipped_by_circuit: int = 0
        self._consec_losses: int = 0
        self._trading_halted: bool = False
        self._utc_date: Optional[str] = None
        self._day_start_balance: float = float(initial_balance)
        self.cumulative_funding: float = 0.0
        self.funding_log: list[dict] = []
        self._last_funding_ts: Optional[pd.Timestamp] = None

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

    def _roll_utc_day(self, timestamp) -> None:
        """Track UTC day for daily loss; reset circuit halt on a new day."""
        if timestamp is None:
            return
        t = pd.Timestamp(timestamp)
        if t.tz is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        d = t.strftime("%Y-%m-%d")
        if d != self._utc_date:
            self._utc_date = d
            self._day_start_balance = self.balance
            self._trading_halted = False

    @staticmethod
    def _as_utc_timestamp(timestamp) -> Optional[pd.Timestamp]:
        if timestamp is None:
            return None
        t = pd.Timestamp(timestamp)
        if t.tz is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return t

    def _apply_funding_until(self, timestamp, mark_price: float) -> None:
        """Apply periodic funding accrual for open positions up to timestamp."""
        if (
            not self.enable_funding
            or self.position is None
            or self.position_size <= 0
        ):
            return
        ts = self._as_utc_timestamp(timestamp)
        if ts is None:
            return
        if self._last_funding_ts is None:
            self._last_funding_ts = ts
            return
        interval = pd.Timedelta(hours=int(self.funding_interval_hours))
        if interval <= pd.Timedelta(0):
            return
        elapsed = ts - self._last_funding_ts
        n = int(elapsed // interval)
        if n <= 0:
            return
        self._last_funding_ts = self._last_funding_ts + (n * interval)
        if self.funding_rate_bps == 0.0:
            return
        notional = abs(float(mark_price) * float(self.position_size))
        if notional <= 0:
            return
        rate = float(self.funding_rate_bps) / 10_000.0
        # Positive funding_rate_bps means longs pay, shorts receive.
        sign = -1.0 if self.position == "LONG" else 1.0
        delta = sign * rate * notional * float(n)
        self.balance += delta
        self.cumulative_funding += delta
        self.funding_log.append(
            {
                "timestamp": self._ts(timestamp),
                "position": self.position,
                "intervals": int(n),
                "rate_bps": float(self.funding_rate_bps),
                "notional": float(notional),
                "amount": float(delta),
            }
        )

    def _fractional_slippage(
        self, ref_price: float, atr: Optional[float]
    ) -> float:
        """Combined fractional adverse slip for one fill (proportional + bps + ATR)."""
        base = float(self.slippage_pct) + self.half_spread_bps / 10_000.0
        amt = float(self.slippage_atr_mult)
        rp = float(ref_price)
        if amt > 0.0 and atr is not None and float(atr) > 0 and rp > 0:
            base += amt * (float(atr) / rp)
        return base if base > 0 else 0.0

    def _entry_fill(
        self,
        raw: float,
        side: str,
        *,
        ref_price: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> float:
        rp = float(ref_price) if ref_price is not None else float(raw)
        s = self._fractional_slippage(rp, atr)
        if s <= 0:
            return float(raw)
        if side == "LONG":
            return float(raw) * (1.0 + s)
        return float(raw) * (1.0 - s)

    def _exit_fill(
        self,
        raw: float,
        position_side: str,
        *,
        ref_price: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> float:
        rp = float(ref_price) if ref_price is not None else float(raw)
        s = self._fractional_slippage(rp, atr)
        if s <= 0:
            return float(raw)
        if position_side == "LONG":
            return float(raw) * (1.0 - s)
        return float(raw) * (1.0 + s)

    def _resolve_intrabar_stop_before_take(self) -> bool:
        """True ⇒ stop-loss level is presumed to execute before take-profit when
        both are touched inside the same bar."""
        pol = self.intrabar_sl_tp_policy
        if pol == "stop_first":
            return True
        if pol == "take_first":
            return False
        return float(self._intrabar_rng.random()) < 0.5

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
            self.equity_history = self._compress_equity_history(
                self.equity_history, MAX_EQUITY_POINTS
            )

    @staticmethod
    def _compress_equity_history(points: list[dict], max_points: int) -> list[dict]:
        """Downsample across the full curve (not just tail clipping).

        Keeping only the latest points can silently erase the historical peak and
        understate drawdown. Uniform sampling preserves the overall curve shape.
        """
        n = len(points)
        if n <= max_points or max_points <= 2:
            return points[-max_points:]
        # Include first and last points and sample evenly between.
        keep = {0, n - 1}
        span = n - 1
        for i in range(1, max_points - 1):
            idx = int(round(i * span / (max_points - 1)))
            keep.add(max(0, min(idx, n - 1)))
        return [points[i] for i in sorted(keep)]

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
                "slippage_pct": self.slippage_pct,
                "slippage_atr_mult": self.slippage_atr_mult,
                "half_spread_bps": self.half_spread_bps,
                "intrabar_sl_tp_policy": self.intrabar_sl_tp_policy,
                "enable_funding": self.enable_funding,
                "funding_rate_bps": self.funding_rate_bps,
                "funding_interval_hours": self.funding_interval_hours,
                "trading_halted": self._trading_halted,
            },
            "cooldown_remaining": self._cooldown_remaining,
            "cumulative_funding": self.cumulative_funding,
            "funding_events": self.funding_log,
        }
        self._persist_json(data)

    def _persist_json(self, data: dict) -> None:
        """Write JSON atomically so concurrent readers never see a partial file."""
        target = self.data_file
        if target in (os.devnull, "/dev/null", "nul"):
            with open(target, "w") as f:
                json.dump(data, f, indent=4)
            return
        directory = os.path.dirname(os.path.abspath(target)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # --------------------------------------------------------- position mgmt
    def _open(
        self,
        side: str,
        price: float,
        timestamp=None,
        *,
        atr: Optional[float] = None,
        size_override: Optional[float] = None,
        stop_override: Optional[float] = None,
        take_override: Optional[float] = None,
    ):
        if price <= 0:
            return

        entry = self._entry_fill(
            float(price),
            side,
            ref_price=float(price),
            atr=atr,
        )

        if size_override is not None:
            size = float(size_override)
        else:
            notional = self.balance * self.allocation_pct
            if notional <= 0:
                return
            size = notional / entry

        if size <= 0:
            return

        self.position = side
        self.entry_price = float(entry)
        self.position_size = size
        self.opened_at = self._ts(timestamp)
        self._trail_extreme = float(entry)
        self._last_funding_ts = self._as_utc_timestamp(timestamp)

        if stop_override is not None:
            self.stop_price = float(stop_override)
        elif side == "LONG":
            self.stop_price = entry * (1 - self.stop_loss_pct)
        else:
            self.stop_price = entry * (1 + self.stop_loss_pct)

        if take_override is not None:
            self.take_price = float(take_override)
        elif side == "LONG":
            self.take_price = entry * (1 + self.take_profit_pct)
        else:
            self.take_price = entry * (1 - self.take_profit_pct)

        if self.verbose:
            print(
                f"OPEN {side} @ {self.entry_price:.2f} "
                f"size={self.position_size:.6f} "
                f"SL={self.stop_price:.2f} TP={self.take_price:.2f}"
            )
        self.save_data()

    def close(
        self,
        price: float,
        reason: str = "signal",
        timestamp=None,
        *,
        atr: Optional[float] = None,
        ref_price: Optional[float] = None,
    ):
        if self.position is None:
            return

        self._roll_utc_day(timestamp)
        pos = self.position
        rp = float(ref_price) if ref_price is not None else float(price)
        self._apply_funding_until(timestamp, mark_price=rp)
        fill = self._exit_fill(
            float(price), pos, ref_price=rp, atr=atr
        )
        gross_pnl = (fill - self.entry_price) * self.position_size
        if pos == "SHORT":
            gross_pnl = (self.entry_price - fill) * self.position_size
        # Taker fee charged on both entry and exit notionals.
        fee = (
            self.entry_price * self.position_size * self.fee_pct
            + float(fill) * self.position_size * self.fee_pct
        )
        net_pnl = gross_pnl - fee
        self.balance += net_pnl
        if net_pnl < 0:
            self._consec_losses += 1
            if (
                self.max_consecutive_losses > 0
                and self._consec_losses >= self.max_consecutive_losses
            ):
                self._trading_halted = True
        else:
            self._consec_losses = 0
        if self.max_daily_loss_pct > 0 and self._day_start_balance > 0:
            if self.balance < self._day_start_balance * (
                1.0 - self.max_daily_loss_pct
            ):
                self._trading_halted = True

        trade = {
            "timestamp": self._ts(timestamp),
            "opened_at": self.opened_at,
            "side": self.position,
            "entry": self.entry_price,
            "exit": float(fill),
            "size": self.position_size,
            "gross_profit": gross_pnl,
            "fee": fee,
            "profit": net_pnl,
            "reason": reason,
        }
        self.trade_log.append(trade)
        self._append_equity(self.balance, realized=True, timestamp=timestamp)

        if self.verbose:
            print(
                f"CLOSE {pos} @ {fill:.2f} "
                f"pnl={net_pnl:+.2f} (gross {gross_pnl:+.2f}, fee {fee:.2f}) "
                f"reason={reason} balance={self.balance:.2f}"
            )

        self.position = None
        self.entry_price = 0.0
        self.position_size = 0.0
        self.stop_price = 0.0
        self.take_price = 0.0
        self.opened_at = None
        self._trail_extreme = 0.0
        self._last_funding_ts = None
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
        atr: Optional[float] = None,
        size_override: Optional[float] = None,
        stop_override: Optional[float] = None,
        take_override: Optional[float] = None,
    ):
        """Called by the bot / backtester when the strategy emits a signal.

        The optional *_override kwargs let an ATR-sizing layer specify an
        exact position size and SL/TP levels instead of the default pct-of-
        balance sizing and pct stop/take distances.
        """
        self._roll_utc_day(timestamp)
        kw = dict(
            timestamp=timestamp,
            atr=atr,
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
                self.close(
                    price,
                    reason="reverse",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(price),
                )
                return
            if self._entry_blocked_by_cooldown():
                self.skipped_by_cooldown += 1
                return
            if self._trading_halted:
                self.skipped_by_circuit += 1
                return
            self._open("LONG", price, **kw)
        elif signal == "SELL":
            if self.position == "SHORT":
                return
            if self.position == "LONG":
                self.close(
                    price,
                    reason="reverse",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(price),
                )
                return
            if self._entry_blocked_by_cooldown():
                self.skipped_by_cooldown += 1
                return
            if self._trading_halted:
                self.skipped_by_circuit += 1
                return
            self._open("SHORT", price, **kw)
        # HOLD: no-op

    def on_tick(
        self,
        mark_price: float,
        timestamp=None,
        *,
        high: Optional[float] = None,
        low: Optional[float] = None,
        atr: Optional[float] = None,
    ):
        """Enforces SL/TP (optionally on intrabar high/low), ticks the cooldown,
        and records mark-to-market at `mark_price` (e.g. bar close)."""
        self._roll_utc_day(timestamp)
        self._apply_funding_until(timestamp, mark_price=mark_price)
        mark_price = float(mark_price)
        hi = float(high) if high is not None else mark_price
        lo = float(low) if low is not None else mark_price

        if (
            self.position is not None
            and self.use_trailing_stop
            and self.trailing_stop_pct > 0.0
        ):
            t = self.trailing_stop_pct
            if self.position == "LONG":
                self._trail_extreme = max(self._trail_extreme, hi)
                trail_stop = self._trail_extreme * (1.0 - t)
                self.stop_price = max(self.stop_price, trail_stop)
            else:
                self._trail_extreme = min(self._trail_extreme, lo)
                trail_stop = self._trail_extreme * (1.0 + t)
                self.stop_price = min(self.stop_price, trail_stop)

        if self.position == "LONG":
            hit_stop = lo <= self.stop_price
            hit_take = hi >= self.take_price
            if hit_stop and hit_take:
                if self._resolve_intrabar_stop_before_take():
                    self.close(
                        self.stop_price,
                        reason="stop_loss",
                        timestamp=timestamp,
                        atr=atr,
                        ref_price=float(self.stop_price),
                    )
                else:
                    self.close(
                        self.take_price,
                        reason="take_profit",
                        timestamp=timestamp,
                        atr=atr,
                        ref_price=float(self.take_price),
                    )
            elif hit_stop:
                self.close(
                    self.stop_price,
                    reason="stop_loss",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(self.stop_price),
                )
            elif hit_take:
                self.close(
                    self.take_price,
                    reason="take_profit",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(self.take_price),
                )
        elif self.position == "SHORT":
            hit_stop = hi >= self.stop_price
            hit_take = lo <= self.take_price
            if hit_stop and hit_take:
                if self._resolve_intrabar_stop_before_take():
                    self.close(
                        self.stop_price,
                        reason="stop_loss",
                        timestamp=timestamp,
                        atr=atr,
                        ref_price=float(self.stop_price),
                    )
                else:
                    self.close(
                        self.take_price,
                        reason="take_profit",
                        timestamp=timestamp,
                        atr=atr,
                        ref_price=float(self.take_price),
                    )
            elif hit_stop:
                self.close(
                    self.stop_price,
                    reason="stop_loss",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(self.stop_price),
                )
            elif hit_take:
                self.close(
                    self.take_price,
                    reason="take_profit",
                    timestamp=timestamp,
                    atr=atr,
                    ref_price=float(self.take_price),
                )

        # Cooldown decrements once per tick while FLAT.
        if self.position is None and self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        self._append_equity(
            self.mark_to_market(mark_price),
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
