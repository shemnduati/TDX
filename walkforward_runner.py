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
    OUTPUT_FILE,
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)
from strategies import get_strategy
from walkforward import (
    _choose_final_oos_params,
    _build_stability_matrix,
    _cartesian_candidates,
    _default_tuning_matrix,
    _mc_trade_resample,
    _normalize_train_engine,
    _param_key,
    _search_space_cartesian,
    resolve_train_engine,
    select_best_train_config,
)


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
        opt_matrix: Optional[dict[str, list[Any]]] = None,
        mc_sims: int = 2000,
        train_engine: str = "grid",
        optuna_trials: int = 64,
        optuna_seed: int = 42,
    ) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("A walk-forward is already running.")
            if train_bars <= 0 or test_bars <= 0:
                raise ValueError("train_bars and test_bars must be > 0")
            if step is not None and step <= 0:
                raise ValueError("step must be > 0")
            requested_engine = _normalize_train_engine(train_engine)
            eng, fallback_reason = resolve_train_engine(requested_engine)
            ot = int(optuna_trials)
            if ot < 1:
                raise ValueError("optuna_trials must be >= 1")

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
                    "n_candidates": 0,
                    "tuned_keys": [],
                    "mc_sims": int(mc_sims),
                    "train_engine": eng,
                    "requested_engine": requested_engine,
                    "fallback_reason": fallback_reason,
                    "optuna_trials_requested": ot if eng == "optuna" else None,
                    "optuna_trials_effective": None,
                    "optuna_seed": int(optuna_seed) if eng == "optuna" else None,
                    "search_space_size": None,
                }
            )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(
                    params,
                    train_bars,
                    test_bars,
                    step or test_bars,
                    opt_matrix or {},
                    int(mc_sims),
                    eng,
                    ot,
                    int(optuna_seed),
                ),
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
        opt_matrix: dict[str, list[Any]],
        mc_sims: int,
        train_engine: str,
        optuna_trials: int,
        optuna_seed: int,
    ) -> None:
        try:
            df_raw = fetch_data(params)
            total = len(df_raw)
            warmup = get_strategy(params.strategy).warmup_bars(params)
            holdout_start = int(total * 0.75)
            dev_end = holdout_start
            matrix = opt_matrix or _default_tuning_matrix(params)
            candidates = _cartesian_candidates(params, matrix)
            tuned_keys = sorted(list(matrix.keys()))
            space_n = _search_space_cartesian(matrix) if matrix else 1
            opt_budget = (
                max(1, min(int(optuna_trials), space_n))
                if train_engine == "optuna"
                else None
            )
            ind_cache: dict[tuple, Any] = {}
            all_test_trade_returns: list[float] = []

            # Pre-compute the list of windows so we know `total` up-front and
            # the UI can draw an accurate progress bar.
            windows_plan: list[tuple[int, int, int, int]] = []
            start = 0
            while start + train_bars + test_bars <= dev_end:
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
                    f"Not enough bars to walk-forward after reserving final 25% OOS: "
                    f"have dev={dev_end}, need {train_bars + test_bars}. Increase bars."
                )

            with self._lock:
                self._state["total"] = len(windows_plan)
                self._state["total_bars"] = total
                self._state["dev_end_bar"] = dev_end
                self._state["holdout_start_bar"] = holdout_start
                self._state["holdout_bars"] = max(0, total - holdout_start)
                self._state["n_candidates"] = len(candidates)
                self._state["tuned_keys"] = tuned_keys
                self._state["search_space_size"] = space_n if matrix else 1
                if train_engine == "optuna":
                    self._state["optuna_trials_effective"] = opt_budget

            for i, (ts, te, xs, xe) in enumerate(windows_plan):
                if self._stop_event.is_set():
                    break

                with self._lock:
                    self._state["current"] = {"i": i, "of": len(windows_plan)}

                best_params, best_train, best_score = select_best_train_config(
                    df_raw,
                    base=params,
                    matrix=matrix,
                    candidates=candidates,
                    ind_cache=ind_cache,
                    eff_train_start=ts,
                    train_end=te,
                    train_engine=train_engine,
                    optuna_trials=optuna_trials,
                    optuna_seed=optuna_seed,
                    stop_checker=lambda: self._stop_event.is_set(),
                )

                if self._stop_event.is_set():
                    break
                best_key = _param_key(best_params)
                if best_key not in ind_cache:
                    ind_cache[best_key] = apply_full_indicators(df_raw, best_params)
                test = replay_on_df(
                    ind_cache[best_key],
                    best_params,
                    start=xs,
                    end=xe,
                    verbose=False,
                    include_trades=True,
                )
                train = best_train or {}
                all_test_trade_returns.extend(test.get("trade_returns", []))

                window = {
                    "i": i,
                    "train_start": ts,
                    "train_end": te,
                    "test_start": xs,
                    "test_end": xe,
                    "train_ret": train.get("return_pct", 0.0),
                    "test_ret": test.get("return_pct", 0.0),
                    "train_n": train.get("trades", 0),
                    "test_n": test.get("trades", 0),
                    "test_wr": test.get("win_rate", 0.0),
                    "test_mdd": test.get("max_drawdown_intrabar_pct",
                                         test.get("max_drawdown_pct", 0.0)),
                    "train_score": best_score,
                    "chosen": {k: getattr(best_params, k) for k in tuned_keys},
                    "chosen_key": tuple(
                        (k, getattr(best_params, k)) for k in tuned_keys
                    ),
                }
                with self._lock:
                    self._state["windows"].append(window)
                    self._state["completed"] += 1
                    self._state["current"] = None

            with self._lock:
                summary = _aggregate(self._state["windows"])
                summary["trade_mc"] = _mc_trade_resample(
                    all_test_trade_returns,
                    sims=int(mc_sims),
                    seed=42,
                )
                summary["stability_matrix"] = _build_stability_matrix(
                    self._state["windows"], tuned_keys
                )
                final_params, final_meta = _choose_final_oos_params(
                    params, self._state["windows"]
                )
                final_key = _param_key(final_params)
                if final_key not in ind_cache:
                    ind_cache[final_key] = apply_full_indicators(df_raw, final_params)
                final_oos = replay_on_df(
                    ind_cache[final_key],
                    final_params,
                    start=holdout_start,
                    end=total,
                    data_file=OUTPUT_FILE,
                    verbose=False,
                    include_trades=True,
                )
                summary["final_oos"] = {
                    "start_bar": holdout_start,
                    "end_bar": total,
                    "bars": max(0, total - holdout_start),
                    "policy": final_meta.get("policy"),
                    "selected_windows": final_meta.get("selected_windows", 0),
                    "selected_key": final_meta.get("selected_key"),
                    "chosen": {k: getattr(final_params, k) for k in tuned_keys},
                    "return_pct": float(final_oos.get("return_pct", 0.0)),
                    "trades": int(final_oos.get("trades", 0)),
                    "win_rate": float(final_oos.get("win_rate", 0.0)),
                    "max_drawdown_pct": float(
                        final_oos.get(
                            "max_drawdown_intrabar_pct",
                            final_oos.get("max_drawdown_pct", 0.0),
                        )
                    ),
                    "profit_factor": float(final_oos.get("profit_factor", 0.0)),
                }
                self._state["summary"] = summary

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
        "n_candidates": 0,
        "tuned_keys": [],
        "mc_sims": 2000,
        "train_engine": "grid",
        "optuna_trials_requested": None,
        "optuna_trials_effective": None,
        "optuna_seed": None,
        "search_space_size": None,
        "dev_end_bar": 0,
        "holdout_start_bar": 0,
        "holdout_bars": 0,
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
        "mean_test_mdd_pct": mean([w.get("test_mdd", 0.0) for w in windows]),
        "positive_rate": pos_rate,
        "total_test_trades": sum(w["test_n"] for w in windows),
        "total_train_trades": sum(w["train_n"] for w in windows),
        "unique_selected_configs": len(set(w.get("chosen_key") for w in windows)),
        "selection_transition_rate": (
            (
                sum(
                    1
                    for i in range(1, len(windows))
                    if windows[i].get("chosen_key") != windows[i - 1].get("chosen_key")
                )
                / max(1, len(windows) - 1)
            ) * 100
        ),
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
