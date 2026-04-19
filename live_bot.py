"""
Threaded live-bot manager.

Usage pattern (from dashboard.py):
    from live_bot import LIVE

    LIVE.start(params)     # begin ticking with the given Params
    LIVE.status()          # current state dict
    LIVE.stop()            # gracefully halt, returns final status

One instance per process (`LIVE` at module level). The background thread
fetches OHLCV, runs the strategy, calls PaperTrader.on_signal/on_tick, and
persists state to data.json so the existing /data endpoint keeps working.

Not suitable for actual money — this is a paper-trading supervisor.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import replace
from typing import Optional

from backtest import Params, _atr_overrides, apply_full_indicators
from exchange import get_exchange
from paper_trader import DEFAULT_DATA_FILE, PaperTrader
from strategies import get_strategy
from utils import format_data


class LiveBotManager:
    """Supervises a single live paper-trading loop."""

    def __init__(self, tick_seconds: int = 60, warmup_bars: int = 300):
        self.tick_seconds = tick_seconds
        self.warmup_bars = warmup_bars

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._params: Optional[Params] = None
        self._trader: Optional[PaperTrader] = None
        self._started_at: Optional[float] = None
        self._last_tick_at: Optional[float] = None
        self._last_signal: str = "HOLD"
        self._last_price: Optional[float] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------ public API
    def start(self, params: Params) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Live bot already running. Stop it first.")
            # Fresh trader = fresh data.json. Any previous live session is
            # overwritten. Save-and-close logic happens on stop() instead.
            self._params = params
            self._trader = PaperTrader(
                initial_balance=params.initial_balance,
                allocation_pct=params.allocation_pct,
                stop_loss_pct=params.stop_loss_pct,
                take_profit_pct=params.take_profit_pct,
                entry_cooldown_bars=params.entry_cooldown_bars,
                fee_pct=params.fee_pct,
                data_file=DEFAULT_DATA_FILE,
            )
            self._stop_event.clear()
            self._started_at = time.time()
            self._last_tick_at = None
            self._last_signal = "HOLD"
            self._last_price = None
            self._last_error = None

            self._thread = threading.Thread(
                target=self._run, name="live-bot", daemon=True
            )
            self._thread.start()
        return self.status()

    def stop(self, snapshot: bool = True) -> dict:
        self._stop_event.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5)
        with self._lock:
            status = self._status_unlocked()
            # Persist a snapshot of the stopped run if requested. The caller
            # (dashboard.py) is responsible for uploading this to runs.py.
            if snapshot and self._trader is not None:
                status["_final_data"] = self._trader_data()
                status["_final_params"] = replace(self._params) if self._params else None
            self._thread = None
        return status

    def status(self) -> dict:
        with self._lock:
            return self._status_unlocked()

    # ------------------------------------------------------------- internal
    def _status_unlocked(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "started_at": self._started_at,
            "last_tick_at": self._last_tick_at,
            "last_signal": self._last_signal,
            "last_price": self._last_price,
            "last_error": self._last_error,
            "params": (
                {k: v for k, v in self._params.__dict__.items()}
                if self._params
                else None
            ),
            "balance": self._trader.balance if self._trader else None,
            "position": self._trader.position if self._trader else None,
        }

    def _trader_data(self) -> dict:
        """Snapshot of the trader's current state, matching data.json shape."""
        t = self._trader
        assert t is not None
        return {
            "initial_balance": t.initial_balance,
            "balance": t.balance,
            "position": t.position,
            "entry_price": t.entry_price,
            "position_size": t.position_size,
            "stop_price": t.stop_price,
            "take_price": t.take_price,
            "trades": list(t.trade_log),
            "equity_history": list(t.equity_history),
            "updated_at": None,  # paper_trader refreshes this on save
        }

    def _run(self) -> None:
        assert self._params is not None and self._trader is not None
        params = self._params
        strategy = get_strategy(params.strategy)
        exchange = get_exchange()

        # Initial back-fill so indicators have warm-up history before we
        # actually start trading.
        while not self._stop_event.is_set():
            try:
                bars = exchange.fetch_ohlcv(
                    params.symbol, params.timeframe, limit=self.warmup_bars
                )
                df = format_data(bars)
                df = apply_full_indicators(df, params)
                signal = strategy.generate_signal(df, params)
                price = float(df["close"].iloc[-1])
                last_bar = df.iloc[-1]

                with self._lock:
                    self._last_tick_at = time.time()
                    self._last_signal = signal
                    self._last_price = price
                    self._last_error = None

                overrides = _atr_overrides(
                    signal, price, last_bar, self._trader, params
                )
                self._trader.on_signal(signal, price, **overrides)
                self._trader.on_tick(price)
            except Exception as e:
                with self._lock:
                    self._last_error = (
                        f"{type(e).__name__}: {e}\n"
                        + traceback.format_exc(limit=2)
                    )

            # Sleep in small slices so stop() is responsive.
            deadline = time.time() + self.tick_seconds
            while time.time() < deadline:
                if self._stop_event.wait(timeout=0.5):
                    return


LIVE = LiveBotManager()
