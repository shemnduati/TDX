"""
Threaded walk-forward runner.

Wraps `walkforward.walk_forward()` in the same background-job pattern the
sweep runner uses: one job at a time per process, progress polled via
`status()`, cancellable via `cancel()`.

Why a runner (and not just a direct call)?
  - Fetching 3000+ bars from the exchange can take 5-10 s on a cold cache,
    and each of N windows runs a backtest after that. Doing this inline
    on a Flask request would time out the proxy.
  - The UI wants live progress ("window 3 of 8, train return 2.1%") so the
    user sees the thing isn't hung.

The runner emits a per-window update into `state["windows"]` as it goes,
plus the same aggregate dict that the CLI prints at the end.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import replace
from statistics import mean, median, stdev
from typing import Any, Optional

from backtest import (
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)
from strategies import get_strategy


class WalkforwardJob:
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
        train_bars: int,
        test_bars: int,
        step: Optional[int] = None,
    ) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("A walk-forward is already running.")
            if train_bars <= 0 or test_bars <= 0:
                raise ValueError("train_bars and test_bars must be > 0")
            if step is not None and step <= 0:
                raise ValueError("step must be > 0")

            params = _merge_params(Params(), base_params)

            self._state = _initial_state()
            self._state.update(
                {
                    "running": True,
                    "started_at": time.time(),
                    "train_bars": train_bars,
                    "test_bars": test_bars,
                    "step": step or test_bars,
                    "params": _params_snapshot(params),
                }
            )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(params, train_bars, test_bars, step or test_bars),
                name="walkforward",
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
            # Shallow-copy collections so the caller can't mutate our state.
            return {
                **self._state,
                "windows": list(self._state["windows"]),
            }

    # --------------------------------------------------------- internals
    def _run(
        self,
        params: Params,
        train_bars: int,
        test_bars: int,
        step: int,
    ) -> None:
        try:
            df = fetch_data(params)
            df = apply_full_indicators(df, params)
            total = len(df)
            warmup = get_strategy(params.strategy).warmup_bars(params)

            # Pre-compute the list of windows so we know `total` up-front and
            # the UI can draw an accurate progress bar.
            windows_plan: list[tuple[int, int, int, int]] = []
            start = 0
            while start + train_bars + test_bars <= total:
                train_start = start
                train_end = start + train_bars
                test_start = train_end
                test_end = test_start + test_bars
                eff_train_start = max(train_start, warmup)
                if eff_train_start < train_end:
                    windows_plan.append(
                        (eff_train_start, train_end, test_start, test_end)
                    )
                start += step

            if not windows_plan:
                raise ValueError(
                    f"Not enough bars to walk-forward: have {total}, "
                    f"need {train_bars + test_bars}. Increase bars."
                )

            with self._lock:
                self._state["total"] = len(windows_plan)
                self._state["total_bars"] = total

            for i, (ts, te, xs, xe) in enumerate(windows_plan):
                if self._stop_event.is_set():
                    break

                with self._lock:
                    self._state["current"] = {"i": i, "of": len(windows_plan)}

                train = replay_on_df(df, params, start=ts, end=te)
                if self._stop_event.is_set():
                    break
                test = replay_on_df(df, params, start=xs, end=xe)

                window = {
                    "i": i,
                    "train_ret": train.get("return_pct", 0.0),
                    "test_ret": test.get("return_pct", 0.0),
                    "train_n": train.get("trades", 0),
                    "test_n": test.get("trades", 0),
                    "test_wr": test.get("win_rate", 0.0),
                    "test_mdd": test.get("max_drawdown_pct", 0.0),
                }
                with self._lock:
                    self._state["windows"].append(window)
                    self._state["completed"] += 1
                    self._state["current"] = None

            with self._lock:
                self._state["summary"] = _aggregate(self._state["windows"])

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


# --------------------------------------------------------------- helpers


def _initial_state() -> dict:
    return {
        "running": False,
        "total": 0,
        "completed": 0,
        "current": None,
        "windows": [],
        "summary": None,
        "error": None,
        "started_at": None,
        "finished_at": None,
        "train_bars": 0,
        "test_bars": 0,
        "step": 0,
        "total_bars": 0,
        "params": {},
    }


def _aggregate(windows: list[dict]) -> dict:
    if not windows:
        return {
            "n_windows": 0,
            "mean_test_ret": 0.0,
            "median_test_ret": 0.0,
            "stdev_test_ret": 0.0,
            "positive_rate": 0.0,
            "total_test_trades": 0,
            "total_train_trades": 0,
            "verdict": "NO_DATA",
        }
    test_rets = [w["test_ret"] for w in windows]
    positive = sum(1 for r in test_rets if r > 0)
    mean_ret = mean(test_rets)
    pos_rate = positive / len(windows) * 100

    verdict = (
        "ROBUST" if pos_rate >= 60 and mean_ret > 0
        else "WEAK" if mean_ret > 0
        else "NOT_VIABLE"
    )
    return {
        "n_windows": len(windows),
        "mean_test_ret": mean_ret,
        "median_test_ret": median(test_rets),
        "stdev_test_ret": stdev(test_rets) if len(test_rets) > 1 else 0.0,
        "positive_rate": pos_rate,
        "total_test_trades": sum(w["test_n"] for w in windows),
        "total_train_trades": sum(w["train_n"] for w in windows),
        "verdict": verdict,
    }


def _merge_params(defaults: Params, overrides: dict) -> Params:
    from sweep_runner import _coerce  # reuse the int/bool coercion table
    allowed = set(defaults.__dict__.keys())
    clean = {
        k: _coerce(k, v) for k, v in (overrides or {}).items() if k in allowed
    }
    return replace(defaults, **clean)


def _params_snapshot(params: Params) -> dict:
    """Tiny snapshot for the status payload — just enough to label the run
    in the UI without dumping every knob."""
    return {
        "strategy": params.strategy,
        "symbol": params.symbol,
        "timeframe": params.timeframe,
        "bars": params.bars,
    }


WALKFORWARD = WalkforwardJob()
