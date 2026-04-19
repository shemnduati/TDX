"""
Threaded sweep runner.

Runs a parameter grid against the backtester in the background and saves
each cell as a regular run (via runs.save_run). The UI polls `status()`
to draw a progress bar and the results table shows up in the History /
Compare tabs like any other run.

Usage (from dashboard.py):
    from sweep_runner import SWEEP

    SWEEP.start(base_params={...}, matrix={"stop_loss_pct": [0.02, 0.03]})
    SWEEP.status()
    SWEEP.cancel()

Only one sweep runs at a time per process. DataFrames for a given
(symbol, timeframe, bars) triplet are cached for the duration of the
sweep so we only hit the exchange once per unique market.
"""
from __future__ import annotations

import itertools
import json
import os
import tempfile
import threading
import time
import traceback
from dataclasses import replace
from typing import Any, Optional

import runs as runs_store
from backtest import (
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)


class SweepJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state: dict = _initial_state()

    # ------------------------------------------------------------ public API
    def start(
        self,
        *,
        base_params: dict,
        matrix: dict[str, list[Any]],
        label_prefix: str = "sweep",
    ) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("A sweep is already running.")
            if not matrix:
                raise ValueError("matrix must contain at least one param.")
            for k, v in matrix.items():
                if not isinstance(v, list) or not v:
                    raise ValueError(
                        f"matrix[{k!r}] must be a non-empty list of values."
                    )

            keys = list(matrix.keys())
            combos = list(itertools.product(*[matrix[k] for k in keys]))
            total = len(combos)
            if total > 200:
                raise ValueError(
                    f"Refusing to run sweep of {total} configs; split it up."
                )

            self._state = _initial_state()
            self._state.update(
                {
                    "running": True,
                    "total": total,
                    "started_at": time.time(),
                    "label_prefix": label_prefix,
                }
            )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(base_params, keys, combos, label_prefix),
                name="sweep",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def cancel(self) -> dict:
        self._stop_event.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=10)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            # Shallow-copy so the caller can't mutate our state.
            return {**self._state, "results": list(self._state["results"])}

    # ----------------------------------------------------------- internals
    def _run(
        self,
        base: dict,
        keys: list[str],
        combos: list[tuple],
        prefix: str,
    ) -> None:
        try:
            base_params = _merge_params(Params(), base)
            df_cache: dict[tuple, Any] = {}
            tmp_file = os.path.join(
                tempfile.gettempdir(), "tdx_sweep_backtest.json"
            )

            for combo in combos:
                if self._stop_event.is_set():
                    break

                overrides = {k: _coerce(k, v) for k, v in zip(keys, combo)}
                params = replace(base_params, **overrides)

                pretty = " · ".join(f"{k}={overrides[k]}" for k in keys)
                label = f"{prefix}: {pretty}"

                with self._lock:
                    self._state["current"] = overrides

                cache_key = (params.symbol, params.timeframe, params.bars)
                if cache_key not in df_cache:
                    df_cache[cache_key] = fetch_data(params)
                df = apply_full_indicators(df_cache[cache_key], params)

                summary = replay_on_df(
                    df, params, data_file=tmp_file, verbose=False
                )
                with open(tmp_file) as f:
                    data = json.load(f)

                meta = runs_store.save_run(
                    kind="backtest",
                    params=params,
                    data=data,
                    summary=summary,
                    label=label,
                )

                with self._lock:
                    self._state["completed"] += 1
                    self._state["results"].append(meta)
                    self._state["current"] = None

        except Exception as e:
            with self._lock:
                self._state["error"] = (
                    f"{type(e).__name__}: {e}\n"
                    + traceback.format_exc(limit=3)
                )
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["finished_at"] = time.time()
                self._state["current"] = None


# ------------------------------------------------------------------ helpers


def _initial_state() -> dict:
    return {
        "running": False,
        "total": 0,
        "completed": 0,
        "current": None,
        "results": [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "label_prefix": None,
    }


_INT_FIELDS = {
    "bars",
    "ema_short",
    "ema_long",
    "ema_trend",
    "rsi_period",
    "donchian_period",
    "sweep_lookback",
    "sweep_adx_period",
    "sweep_volume_lookback",
    "entry_cooldown_bars",
    "atr_period",
    "htf_ema_period",
    "filter_adx_period",
    "vol_ma_period",
    "macd_fast",
    "macd_slow",
    "macd_signal",
}

_BOOL_FIELDS = {
    "use_atr_sizing",
    "use_htf_confirm",
    "use_adx_filter",
    "use_volume_filter",
    "use_atr_filter",
    "use_macd_confirm",
}


def _coerce(key: str, value: Any) -> Any:
    if key in _INT_FIELDS:
        return int(value)
    if key in _BOOL_FIELDS:
        return bool(value)
    return value


def _merge_params(defaults: Params, overrides: dict) -> Params:
    allowed = set(defaults.__dict__.keys())
    clean = {
        k: _coerce(k, v) for k, v in (overrides or {}).items() if k in allowed
    }
    return replace(defaults, **clean)


SWEEP = SweepJob()
