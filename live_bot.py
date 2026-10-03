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

import pandas as pd

from backtest import Params, _atr_overrides, _bar_atr, apply_full_indicators
from exchange import get_exchange
from history import TF_MS, trim_incomplete_last_row
from microstructure import apply_spread_entry_gate, fetch_spread_bps
from paper_trader import DEFAULT_DATA_FILE, PaperTrader
from strategies import get_strategy
from utils import format_data


def _seconds_until_next_bar_close(tf_ms: int) -> float:
    """Sleep duration until the current in-progress candle closes (+ small buffer)."""
    now_ms = int(time.time() * 1000)
    current_open = (now_ms // tf_ms) * tf_ms
    next_close_ms = current_open + tf_ms
    return max(0.05, (next_close_ms - now_ms) / 1000.0 + 0.05)


def _ts_key(ts) -> pd.Timestamp:
    return pd.Timestamp(ts)


def run_exchange_paper_step(
    params: Params,
    strategy,
    exchange,
    trader: PaperTrader,
    *,
    ohlcv_limit: int = 300,
    last_processed_closed_ts: object | None = None,
    last_reported_signal: str = "HOLD",
) -> tuple[str, float, float | None, pd.Timestamp, float | None, bool]:
    """Fetch OHLCV, run strategy on the last *closed* row set, then fill at the
    open of the in-progress bar and evaluate SL/TP on that bar's range.

    If `last_processed_closed_ts` matches the current newest closed-candle
    time, skips ``generate_signal`` and ``on_signal`` (avoids re-arming
    the same bar when the loop wakes more than once before the next close);
    still runs ``on_tick`` so stops / cooldown / mark-to-market advance.

    Returns (
        signal,
        mark_price,
        rsi_on_last_closed_bar | None,
        newest_closed_ts,
        spread_bps | None,
        spread_blocked,
    ).
    """
    if params.timeframe not in TF_MS:
        raise ValueError(f"Unsupported timeframe: {params.timeframe}")
    now_ms = int(time.time() * 1000)

    bars = exchange.fetch_ohlcv(
        params.symbol, params.timeframe, limit=ohlcv_limit
    )
    df = format_data(bars)
    df = apply_full_indicators(df, params)
    n_full = len(df)
    closed_df = trim_incomplete_last_row(df, params.timeframe, now_ms=now_ms)
    forming = df.iloc[-1] if len(closed_df) < n_full else None

    if len(closed_df) < 1:
        raise ValueError("No closed OHLCV rows after trimming incomplete bar")

    newest_closed_ts = _ts_key(closed_df.iloc[-1]["timestamp"])
    same_closed_bar = (
        last_processed_closed_ts is not None
        and _ts_key(last_processed_closed_ts) == newest_closed_ts
    )

    if forming is not None:
        f_ts = forming["timestamp"]
        f_hi = float(forming["high"])
        f_lo = float(forming["low"])
        f_cl = float(forming["close"])
    else:
        f_ts = closed_df.iloc[-1]["timestamp"]
        c = float(closed_df.iloc[-1]["close"])
        f_hi = f_lo = f_cl = c

    tick_bar = forming if forming is not None else closed_df.iloc[-1]
    atr_tick_bar = _bar_atr(tick_bar)

    if same_closed_bar:
        trader.on_tick(
            f_cl, timestamp=f_ts, high=f_hi, low=f_lo, atr=atr_tick_bar
        )
        return (
            last_reported_signal,
            f_cl,
            None,
            newest_closed_ts,
            None,
            False,
        )

    signal = strategy.generate_signal(closed_df, params)
    spread_bps: float | None = None
    spread_blocked = False
    if params.max_spread_bps > 0 and signal in ("BUY", "SELL"):
        spread_bps = fetch_spread_bps(exchange, params.symbol)
        signal, spread_blocked = apply_spread_entry_gate(
            signal,
            spread_bps,
            params.max_spread_bps,
            position=trader.position,
        )
    last_bar = closed_df.iloc[-1]
    rsi_out: float | None = None
    if "rsi" in closed_df.columns and not closed_df["rsi"].empty:
        v = last_bar.get("rsi")
        if v is not None and not pd.isna(v):
            rsi_out = float(v)
    if forming is not None:
        price = float(forming["open"])
        ts = forming["timestamp"]
    else:
        # All rows are complete (stale snapshot); avoid same-bar lookahead.
        price = float(closed_df.iloc[-1]["close"])
        ts = closed_df.iloc[-1]["timestamp"]

    overrides = _atr_overrides(signal, price, last_bar, trader, params)
    slip_atr = _bar_atr(last_bar)
    trader.on_signal(signal, price, timestamp=ts, atr=slip_atr, **overrides)
    trader.on_tick(
        f_cl, timestamp=f_ts, high=f_hi, low=f_lo, atr=atr_tick_bar
    )
    return signal, f_cl, rsi_out, newest_closed_ts, spread_bps, spread_blocked


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
        self._last_spread_bps: Optional[float] = None
        self._last_spread_blocked: bool = False

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
                slippage_pct=params.slippage_pct,
                slippage_atr_mult=params.slippage_atr_mult,
                half_spread_bps=params.half_spread_bps,
                intrabar_sl_tp_policy=params.intrabar_sl_tp_policy,
                intrabar_random_seed=params.intrabar_random_seed,
                use_trailing_stop=params.use_trailing_stop,
                trailing_stop_pct=params.trailing_stop_pct,
                max_consecutive_losses=params.max_consecutive_losses,
                max_daily_loss_pct=params.max_daily_loss_pct,
                enable_funding=params.enable_funding,
                funding_rate_bps=params.funding_rate_bps,
                funding_interval_hours=params.funding_interval_hours,
            )
            self._stop_event.clear()
            self._started_at = time.time()
            self._last_tick_at = None
            self._last_signal = "HOLD"
            self._last_price = None
            self._last_error = None
            self._last_spread_bps = None
            self._last_spread_blocked = False

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
            "last_spread_bps": self._last_spread_bps,
            "last_spread_blocked": self._last_spread_blocked,
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
        if params.timeframe not in TF_MS:
            with self._lock:
                self._last_error = f"Unsupported timeframe: {params.timeframe}"
            return

        tf_ms = TF_MS[params.timeframe]
        last_closed_ts: object | None = None
        # Initial back-fill so indicators have warm-up history before we
        # actually start trading.
        while not self._stop_event.is_set():
            try:
                signal, mtm, _, out_ts, spread_bps, spread_blocked = (
                    run_exchange_paper_step(
                        params,
                        strategy,
                        exchange,
                        self._trader,
                        ohlcv_limit=self.warmup_bars,
                        last_processed_closed_ts=last_closed_ts,
                        last_reported_signal=self._last_signal,
                    )
                )
                last_closed_ts = out_ts
                with self._lock:
                    self._last_tick_at = time.time()
                    self._last_signal = signal
                    self._last_price = mtm
                    self._last_error = None
                    self._last_spread_bps = spread_bps
                    self._last_spread_blocked = spread_blocked
            except Exception as e:
                with self._lock:
                    self._last_error = (
                        f"{type(e).__name__}: {e}\n"
                        + traceback.format_exc(limit=2)
                    )

            # Align with candle closes, but keep a minimum tick for low timeframes.
            sleep_s = max(
                self.tick_seconds, _seconds_until_next_bar_close(tf_ms)
            )
            deadline = time.time() + sleep_s
            while time.time() < deadline:
                if self._stop_event.wait(timeout=0.5):
                    return


LIVE = LiveBotManager()
