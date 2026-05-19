"""
Walk-forward validation for a single config.

Slides a rolling (train, test) window across the fetched history and
reports aggregated TEST-period statistics. A strategy that's robust
should produce mostly positive test windows across different market
regimes. One amazing window + five losers = not robust.

Run (uses config.py + CLI overrides, like backtest.py):
    python walkforward.py                        # defaults
    python walkforward.py --timeframe 4h --bars 3000 \
        --ema-short 20 --ema-long 50 \
        --train-bars 500 --test-bars 200
    python walkforward.py --train-engine optuna --optuna-trials 128 \
        --optuna-seed 42   # optional pip install optuna>=3

Output:
    - Per-window table (train/test returns, trades)
    - Aggregated summary (mean, median, stdev, % positive test windows)
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
from dataclasses import replace
from statistics import mean, median, stdev
from typing import Any, Callable, Optional

from backtest import (
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)
from config import (
    ADX_MAX,
    ADX_MIN,
    ATR_MIN_PCT,
    DONCHIAN_PERIOD,
    EMA_LONG,
    EMA_SHORT,
    EMA_TREND,
    ENTRY_COOLDOWN_BARS,
    FEE_PCT,
    HTF_EMA_PERIOD,
    HTF_TIMEFRAME,
    RSI_BUY_MAX,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    RSI_SELL_MIN,
    STOP_LOSS_PCT,
    STRATEGY,
    SWEEP_ADX_MAX,
    SWEEP_ADX_PERIOD,
    SWEEP_LOOKBACK,
    SWEEP_VOLUME_LOOKBACK,
    SWEEP_VOLUME_MULT,
    TAKE_PROFIT_PCT,
    TRADE_ALLOCATION_PCT,
    USE_ADX_FILTER,
    USE_ATR_FILTER,
    USE_HTF_CONFIRM,
    USE_MACD_CONFIRM,
    USE_VOLUME_FILTER,
    VOL_MULT,
)
from strategies import get_strategy, list_strategies


def _param_key(params: Params) -> tuple:
    return tuple(sorted(params.__dict__.items()))


def _cartesian_candidates(base: Params, matrix: dict[str, list]) -> list[Params]:
    if not matrix:
        return [base]
    keys = list(matrix.keys())
    vals = [matrix[k] for k in keys]
    out: list[Params] = []
    seen: set[tuple] = set()
    for combo in itertools.product(*vals):
        p = replace(base, **{k: v for k, v in zip(keys, combo)})
        key = _param_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _i(v: int, k: float, lo: int = 1) -> int:
    return max(lo, int(round(v * k)))


def _default_tuning_matrix(params: Params) -> dict[str, list]:
    """Compact, strategy-aware candidate set for true WFO.

    Keep this intentionally small to avoid brute-force overfitting in each train
    window while still testing local robustness around the baseline profile.
    """
    s = params.strategy
    if s == "ema_crossover":
        return {
            "ema_short": sorted({params.ema_short, _i(params.ema_short, 0.8), _i(params.ema_short, 1.2)}),
            "ema_long": sorted({params.ema_long, _i(params.ema_long, 0.85), _i(params.ema_long, 1.15)}),
            "ema_trend": sorted({params.ema_trend, _i(params.ema_trend, 0.85), _i(params.ema_trend, 1.15)}),
        }
    if s == "rsi_mean_reversion":
        return {
            "rsi_oversold": sorted({params.rsi_oversold, max(5.0, params.rsi_oversold - 5.0), min(45.0, params.rsi_oversold + 5.0)}),
            "rsi_overbought": sorted({params.rsi_overbought, max(55.0, params.rsi_overbought - 5.0), min(95.0, params.rsi_overbought + 5.0)}),
            "mr_regime_adx_max": sorted({params.mr_regime_adx_max, 20.0, 25.0}) if params.mr_regime_adx_max > 0 else [0.0, 20.0, 25.0],
        }
    if s == "donchian_breakout":
        return {
            "donchian_period": sorted({params.donchian_period, _i(params.donchian_period, 0.75), _i(params.donchian_period, 1.25)}),
            "ema_trend": sorted({params.ema_trend, _i(params.ema_trend, 0.85), _i(params.ema_trend, 1.15)}),
            "breakout_atr_mult": sorted({params.breakout_atr_mult, max(0.2, params.breakout_atr_mult - 0.2), params.breakout_atr_mult + 0.2}),
        }
    if s == "intraday_donchian":
        return {
            "donchian_period": sorted({params.donchian_period, _i(params.donchian_period, 0.8), _i(params.donchian_period, 1.2)}),
            "atr_ma_period": sorted({params.atr_ma_period, _i(params.atr_ma_period, 0.8), _i(params.atr_ma_period, 1.2)}),
            "breakout_atr_mult": sorted({params.breakout_atr_mult, max(0.2, params.breakout_atr_mult - 0.2), params.breakout_atr_mult + 0.2}),
        }
    if s == "liquidity_sweep":
        return {
            "sweep_lookback": sorted({params.sweep_lookback, _i(params.sweep_lookback, 0.8), _i(params.sweep_lookback, 1.2)}),
            "sweep_adx_max": sorted({params.sweep_adx_max, 20.0, 25.0, 30.0}),
            "sweep_volume_mult": sorted({params.sweep_volume_mult, max(1.1, params.sweep_volume_mult - 0.2), params.sweep_volume_mult + 0.2}),
        }
    return {}


def _normalize_train_engine(name: str) -> str:
    n = name.strip().lower()
    if n not in {"grid", "optuna"}:
        raise ValueError(f"train_engine must be 'grid' or 'optuna', got {name!r}")
    return n


def _search_space_cartesian(matrix: dict[str, list[Any]]) -> int:
    prod = 1
    for _k in sorted(matrix.keys()):
        prod *= max(1, len(matrix[_k]))
    return prod if matrix else 1


def _replay_train_selection(
    df_raw,
    ind_cache: dict[tuple, Any],
    cand: Params,
    eff_train_start: int,
    train_end: int,
) -> tuple[dict, float]:
    """Train-period replay only — must never see test-range indices."""
    key = _param_key(cand)
    if key not in ind_cache:
        ind_cache[key] = apply_full_indicators(df_raw, cand)
    train = replay_on_df(
        ind_cache[key],
        cand,
        start=eff_train_start,
        end=train_end,
        verbose=False,
    )
    return train, float(_train_objective(train))


def select_best_train_config(
    df_raw,
    *,
    base: Params,
    matrix: dict[str, list[Any]],
    candidates: list[Params],
    ind_cache: dict[tuple, Any],
    eff_train_start: int,
    train_end: int,
    train_engine: str,
    optuna_trials: int,
    optuna_seed: int,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> tuple[Params, Optional[dict], float]:
    """Pick hyperparameters using only the train slice [eff_train_start, train_end).

    Out-of-sample safeguard: no test indices or test replay are used here.
    """
    engine = _normalize_train_engine(train_engine)
    if not matrix:
        train, score = _replay_train_selection(
            df_raw, ind_cache, base, eff_train_start, train_end
        )
        return base, train, score
    if engine == "grid":
        best_params = base
        best_train: Optional[dict] = None
        best_score = float("-inf")
        for cand in candidates:
            if stop_checker and stop_checker():
                break
            train, score = _replay_train_selection(
                df_raw, ind_cache, cand, eff_train_start, train_end
            )
            if score > best_score:
                best_score = score
                best_train = train
                best_params = cand
        return best_params, best_train, best_score

    try:
        import optuna
    except ImportError as e:
        raise ImportError(
            "train_engine='optuna' requires optional dependency 'optuna'. "
            "Install: pip install optuna>=3"
        ) from e
    from optuna.samplers import TPESampler

    space_n = _search_space_cartesian(matrix)
    nt = max(1, min(int(optuna_trials), space_n))

    tuned = sorted(matrix.keys())
    holder: dict[str, Any] = {
        "params": None,
        "train": None,
        "score": float("-inf"),
    }

    def suggest_candidate(trial: Any) -> Params:
        kw: dict[str, Any] = {}
        for tk in tuned:
            choices = matrix[tk]
            if not choices:
                continue
            if len(choices) == 1:
                kw[tk] = choices[0]
            else:
                kw[tk] = trial.suggest_categorical(str(tk), list(choices))
        return replace(base, **kw)

    def objective(trial: Any) -> float:
        cand = suggest_candidate(trial)
        train, score = _replay_train_selection(
            df_raw, ind_cache, cand, eff_train_start, train_end
        )
        if score > holder["score"]:
            holder["score"] = score
            holder["train"] = train
            holder["params"] = cand
        return score

    def stop_cb(study: Any, _trial: Any) -> None:
        if stop_checker and stop_checker():
            study.stop()

    sampler = TPESampler(seed=int(optuna_seed))
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=nt, callbacks=[stop_cb], show_progress_bar=False)

    if holder["params"] is None:
        train, score = _replay_train_selection(
            df_raw, ind_cache, base, eff_train_start, train_end
        )
        return base, train, score
    return holder["params"], holder["train"], float(holder["score"])


def _choose_final_oos_params(
    base: Params, windows: list[dict]
) -> tuple[Params, dict[str, Any]]:
    """Freeze a single config for final OOS replay using only DEV-window history."""
    stats: dict[tuple, dict[str, float]] = {}
    for w in windows:
        ck = w.get("chosen_key")
        if not isinstance(ck, tuple) or not ck:
            continue
        if ck not in stats:
            stats[ck] = {"n": 0.0, "sum_test_ret": 0.0}
        stats[ck]["n"] += 1.0
        stats[ck]["sum_test_ret"] += float(w.get("test_ret", 0.0))
    if not stats:
        return base, {
            "policy": "baseline_fallback_no_windows",
            "selected_windows": 0,
        }

    best_key = max(
        stats.keys(),
        key=lambda k: (
            stats[k]["n"],
            stats[k]["sum_test_ret"],
            str(k),
        ),
    )
    overrides = {
        str(k): v
        for k, v in best_key
        if isinstance(k, str)
    }
    picked = replace(base, **overrides)
    return picked, {
        "policy": "mode_selected_config",
        "selected_windows": int(stats[best_key]["n"]),
        "selected_key": list(best_key),
    }


def _train_objective(summary: dict) -> float:
    """Robust objective for train-window model selection.

    Prioritizes risk-adjusted consistency over raw return.
    """
    ret = float(summary.get("return_pct", 0.0))
    mdd = float(summary.get("max_drawdown_intrabar_pct",
                            summary.get("max_drawdown_pct", 0.0)))
    pf = min(float(summary.get("profit_factor", 0.0)), 3.0)
    sortino = float(summary.get("annualized_sortino", 0.0))
    trades = float(summary.get("trades", 0))
    # Require some sample size; tiny train windows can otherwise "win" by luck.
    trade_penalty = 0.0 if trades >= 5 else (5.0 - trades) * 0.2
    # Weighted blend; units are percentages/ratios but this behaves robustly.
    return (0.35 * ret) + (1.8 * sortino) + (2.0 * (pf - 1.0)) - (0.45 * mdd) - trade_penalty


def _max_dd_from_returns(returns: list[float]) -> float:
    """Drawdown % from a return path where each step is additive to equity."""
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        eq *= max(1e-9, 1.0 + float(r))
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return mdd


def _mc_trade_resample(
    trade_returns: list[float], sims: int = 2000, seed: Optional[int] = 42
) -> dict:
    """Bootstrap trade returns to estimate return/DD uncertainty."""
    if len(trade_returns) < 2 or sims <= 0:
        return {
            "n_trades": len(trade_returns),
            "sims": 0,
            "ret_mean_pct": 0.0,
            "ret_p05_pct": 0.0,
            "ret_p50_pct": 0.0,
            "ret_p95_pct": 0.0,
            "mdd_mean_pct": 0.0,
            "mdd_p95_pct": 0.0,
        }
    rng = random.Random(seed)
    n = len(trade_returns)
    ret_out: list[float] = []
    dd_out: list[float] = []
    for _ in range(sims):
        sample = [trade_returns[rng.randrange(n)] for _ in range(n)]
        total = 1.0
        for r in sample:
            total *= max(1e-9, 1.0 + float(r))
        ret_out.append((total - 1.0) * 100.0)
        dd_out.append(_max_dd_from_returns(sample))
    ret_out.sort()
    dd_out.sort()

    def pct(arr: list[float], p: float) -> float:
        if not arr:
            return 0.0
        i = min(len(arr) - 1, max(0, int(round((len(arr) - 1) * p))))
        return float(arr[i])

    return {
        "n_trades": n,
        "sims": sims,
        "ret_mean_pct": round(mean(ret_out), 3),
        "ret_p05_pct": round(pct(ret_out, 0.05), 3),
        "ret_p50_pct": round(pct(ret_out, 0.50), 3),
        "ret_p95_pct": round(pct(ret_out, 0.95), 3),
        "mdd_mean_pct": round(mean(dd_out), 3),
        "mdd_p95_pct": round(pct(dd_out, 0.95), 3),
    }


def _build_stability_matrix(
    windows: list[dict], tuned_keys: list[str]
) -> dict[str, Any]:
    """Aggregate per-window choices into heatmap-ready cells.

    Uses the first two tuned keys as (x, y). If only one key is tuned, y mirrors x.
    """
    if not windows or not tuned_keys:
        return {
            "x_key": None,
            "y_key": None,
            "cells": [],
        }
    x_key = tuned_keys[0]
    y_key = tuned_keys[1] if len(tuned_keys) > 1 else tuned_keys[0]
    buckets: dict[tuple[Any, Any], dict[str, float]] = {}
    for w in windows:
        chosen = w.get("chosen") or {}
        x = chosen.get(x_key)
        y = chosen.get(y_key)
        if x is None or y is None:
            continue
        k = (x, y)
        if k not in buckets:
            buckets[k] = {
                "n": 0.0,
                "sum_test_ret": 0.0,
                "sum_test_mdd": 0.0,
                "sum_train_score": 0.0,
                "wins": 0.0,
            }
        b = buckets[k]
        tr = float(w.get("test_ret", 0.0))
        b["n"] += 1.0
        b["sum_test_ret"] += tr
        b["sum_test_mdd"] += float(w.get("test_mdd", 0.0))
        b["sum_train_score"] += float(w.get("train_score", 0.0))
        if tr > 0:
            b["wins"] += 1.0
    cells = []
    for (x, y), b in buckets.items():
        n = max(1.0, b["n"])
        cells.append(
            {
                "x": x,
                "y": y,
                "n_windows": int(b["n"]),
                "mean_test_ret": b["sum_test_ret"] / n,
                "mean_test_mdd": b["sum_test_mdd"] / n,
                "mean_train_score": b["sum_train_score"] / n,
                "positive_rate": (b["wins"] / n) * 100.0,
            }
        )
    cells.sort(key=lambda c: (c["x"], c["y"]))
    return {
        "x_key": x_key,
        "y_key": y_key,
        "cells": cells,
    }


def walkforward_report_payload(st: dict) -> dict:
    """Build a JSON-serializable archive of a walk-forward job (dashboard / CLI).

    Normalises `chosen_key` tuples into [[param, value], ...] lists.
    """
    from datetime import datetime, timezone

    raw_windows = list(st.get("windows") or [])
    windows_out: list[dict] = []
    for w in raw_windows:
        ww = dict(w)
        ck = ww.get("chosen_key")
        if isinstance(ck, tuple):
            ww["chosen_key"] = [
                [pair[0], pair[1]] if isinstance(pair, tuple) else pair
                for pair in ck
            ]
        windows_out.append(ww)

    summary = st.get("summary")
    summary_out = dict(summary) if isinstance(summary, dict) else summary

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "job": {
            "running": bool(st.get("running")),
            "completed": int(st.get("completed", 0)),
            "total": int(st.get("total", 0)),
            "error": st.get("error"),
            "started_at": st.get("started_at"),
            "finished_at": st.get("finished_at"),
            "train_bars": st.get("train_bars"),
            "test_bars": st.get("test_bars"),
            "step": st.get("step"),
            "total_bars": st.get("total_bars"),
            "n_candidates": st.get("n_candidates"),
            "train_engine": st.get("train_engine"),
            "optuna_trials_requested": st.get("optuna_trials_requested"),
            "optuna_trials_effective": st.get("optuna_trials_effective"),
            "optuna_seed": st.get("optuna_seed"),
            "search_space_size": st.get("search_space_size"),
            "dev_end_bar": st.get("dev_end_bar"),
            "holdout_start_bar": st.get("holdout_start_bar"),
            "holdout_bars": st.get("holdout_bars"),
            "tuned_keys": list(st.get("tuned_keys") or []),
            "mc_sims": st.get("mc_sims"),
            "params": st.get("params"),
        },
        "summary": summary_out,
        "windows": windows_out,
    }


def _wf_state_from_cli_result(
    params: Params,
    train_bars: int,
    test_bars: int,
    step: Optional[int],
    mc_sims: int,
    r: dict,
) -> dict:
    """Match `WalkforwardJob.status()` layout after a synchronous walk_forward."""
    pos_rate = r["positive_rate"]
    mean_ret = r["mean_test_ret"]
    verdict = (
        "ROBUST"
        if pos_rate >= 60 and mean_ret > 0
        else "WEAK"
        if mean_ret > 0
        else "NOT_VIABLE"
    )
    summary = {
        "n_windows": r["n_windows"],
        "mean_test_ret": r["mean_test_ret"],
        "median_test_ret": r["median_test_ret"],
        "stdev_test_ret": r["stdev_test_ret"],
        "mean_test_mdd_pct": r.get("mean_test_mdd_pct", 0.0),
        "positive_rate": pos_rate,
        "total_test_trades": r["total_test_trades"],
        "total_train_trades": r["total_train_trades"],
        "unique_selected_configs": r.get("unique_selected_configs", 0),
        "selection_transition_rate": r.get("selection_transition_rate", 0.0),
        "verdict": verdict,
        "trade_mc": r.get("trade_mc", {}),
        "final_oos": r.get("final_oos"),
        "stability_matrix": _build_stability_matrix(
            r["windows"], r.get("tuned_keys", [])
        ),
    }
    return {
        "running": False,
        "completed": r["n_windows"],
        "total": r["n_windows"],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "train_bars": train_bars,
        "test_bars": test_bars,
        "step": step or test_bars,
        "total_bars": r["total_bars"],
        "params": {
            "strategy": params.strategy,
            "symbol": params.symbol,
            "timeframe": params.timeframe,
            "bars": params.bars,
        },
        "n_candidates": r.get("n_candidates", 0),
        "train_engine": r.get("train_engine", "grid"),
        "optuna_trials_requested": r.get("optuna_trials_requested"),
        "optuna_trials_effective": r.get("optuna_trials_effective"),
        "optuna_seed": r.get("optuna_seed"),
        "search_space_size": r.get("search_space_size"),
        "dev_end_bar": r.get("dev_end_bar"),
        "holdout_start_bar": r.get("holdout_start_bar"),
        "holdout_bars": r.get("holdout_bars"),
        "tuned_keys": list(r.get("tuned_keys") or []),
        "mc_sims": int(mc_sims),
        "windows": r["windows"],
        "summary": summary,
    }


def _write_walkforward_windows_csv(
    path: str,
    *,
    params: Params,
    train_bars: int,
    test_bars: int,
    step: int,
    total_bars: int,
    n_candidates: int,
    tuned_keys: list[str],
    windows: list[dict],
    train_engine: str = "grid",
    optuna_trials_requested: Optional[int] = None,
    optuna_trials_effective: Optional[int] = None,
    optuna_seed: Optional[int] = None,
    search_space_size: Optional[int] = None,
) -> None:
    """CSV rows mirror GET /walkforward/windows.csv from the dashboard."""
    tuned = list(tuned_keys)
    meta_fields = [
        "strategy",
        "symbol",
        "timeframe",
        "bars_fetch",
        "train_bars",
        "test_bars",
        "step",
        "total_bars",
        "n_candidates",
        "train_engine",
        "optuna_trials_requested",
        "optuna_trials_effective",
        "optuna_seed",
        "search_space_size",
    ]
    window_fields = [
        "i",
        "train_ret",
        "test_ret",
        "train_n",
        "test_n",
        "test_wr",
        "test_mdd",
        "train_score",
    ]
    chosen_cols = [f"chosen_{k}" for k in tuned]
    fieldnames = meta_fields + window_fields + chosen_cols
    meta_row = {
        "strategy": params.strategy,
        "symbol": params.symbol,
        "timeframe": params.timeframe,
        "bars_fetch": params.bars,
        "train_bars": train_bars,
        "test_bars": test_bars,
        "step": step,
        "total_bars": total_bars,
        "n_candidates": n_candidates,
        "train_engine": train_engine,
        "optuna_trials_requested": optuna_trials_requested if optuna_trials_requested is not None else "",
        "optuna_trials_effective": optuna_trials_effective if optuna_trials_effective is not None else "",
        "optuna_seed": optuna_seed if optuna_seed is not None else "",
        "search_space_size": search_space_size if search_space_size is not None else "",
    }
    with open(path, "w", newline="", encoding="utf-8") as fp:
        wr = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        wr.writeheader()
        for win in windows:
            chosen = win.get("chosen") or {}
            if not isinstance(chosen, dict):
                chosen = {}
            row = {**meta_row}
            row["i"] = win.get("i")
            row["train_ret"] = win.get("train_ret")
            row["test_ret"] = win.get("test_ret")
            row["train_n"] = win.get("train_n")
            row["test_n"] = win.get("test_n")
            row["test_wr"] = win.get("test_wr")
            row["test_mdd"] = win.get("test_mdd")
            row["train_score"] = win.get("train_score")
            for k in tuned:
                v = chosen.get(k, "")
                if isinstance(v, bool):
                    v = str(v).lower()
                row[f"chosen_{k}"] = v
            wr.writerow(row)


def _coerce_like(value: str, template):
    if isinstance(template, bool):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(template, int) and not isinstance(template, bool):
        return int(value)
    if isinstance(template, float):
        return float(value)
    return value


def _parse_opt_clauses(params: Params, clauses: list[str]) -> dict[str, list]:
    """Parse repeatable --opt clauses: key=v1,v2,v3."""
    if not clauses:
        return {}
    matrix: dict[str, list] = {}
    allowed = params.__dict__
    for clause in clauses:
        if "=" not in clause:
            raise ValueError(
                f"Invalid --opt {clause!r}; expected key=v1,v2,..."
            )
        key, raw_vals = clause.split("=", 1)
        key = key.strip()
        if key not in allowed:
            raise ValueError(
                f"Unknown --opt key {key!r}. Allowed params are from Params."
            )
        vals = [v.strip() for v in raw_vals.split(",") if v.strip() != ""]
        if not vals:
            raise ValueError(f"--opt {key}=... must include at least one value.")
        template = allowed[key]
        parsed = [_coerce_like(v, template) for v in vals]
        # De-dup while preserving order.
        dedup = list(dict.fromkeys(parsed))
        matrix[key] = dedup
    return matrix


def walk_forward(
    params: Params,
    train_bars: int,
    test_bars: int,
    step: Optional[int] = None,
    *,
    opt_matrix: Optional[dict[str, list]] = None,
    mc_sims: int = 2000,
    train_engine: str = "grid",
    optuna_trials: int = 64,
    optuna_seed: int = 42,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> dict:
    step = step or test_bars
    df_raw = fetch_data(params)
    ind_cache: dict[tuple, Any] = {}
    matrix = opt_matrix or _default_tuning_matrix(params)
    candidates = _cartesian_candidates(params, matrix)
    tuned_keys = sorted(list(matrix.keys()))
    eng = _normalize_train_engine(train_engine)
    space_n = _search_space_cartesian(matrix) if matrix else 1
    optuna_budget = (
        max(1, min(int(optuna_trials), space_n)) if eng == "optuna" else None
    )

    total = len(df_raw)
    warmup = get_strategy(params.strategy).warmup_bars(params)
    holdout_start = int(total * 0.75)
    dev_end = holdout_start

    windows = []
    all_test_trade_returns: list[float] = []
    start = 0
    while start + train_bars + test_bars <= dev_end:
        train_start = start
        train_end = start + train_bars
        test_start = train_end
        test_end = test_start + test_bars

        effective_train_start = max(train_start, warmup)
        if effective_train_start >= train_end:
            start += step
            continue

        best_params, best_train, best_score = select_best_train_config(
            df_raw,
            base=params,
            matrix=matrix,
            candidates=candidates,
            ind_cache=ind_cache,
            eff_train_start=effective_train_start,
            train_end=train_end,
            train_engine=eng,
            optuna_trials=int(optuna_trials),
            optuna_seed=int(optuna_seed),
            stop_checker=stop_checker,
        )

        best_key = _param_key(best_params)
        if best_key not in ind_cache:
            ind_cache[best_key] = apply_full_indicators(df_raw, best_params)
        test = replay_on_df(
            ind_cache[best_key],
            best_params,
            start=test_start,
            end=test_end,
            verbose=False,
            include_trades=True,
        )
        train = best_train or {}
        all_test_trade_returns.extend(test.get("trade_returns", []))

        windows.append(
            {
                "i": len(windows),
                "train_start": effective_train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "train_ret": train.get("return_pct", 0.0),
                "test_ret": test.get("return_pct", 0.0),
                "train_n": train.get("trades", 0),
                "test_n": test.get("trades", 0),
                "test_wr": test.get("win_rate", 0.0),
                "train_score": best_score,
                "test_mdd": test.get("max_drawdown_intrabar_pct",
                                     test.get("max_drawdown_pct", 0.0)),
                "chosen": {k: getattr(best_params, k) for k in tuned_keys},
                "chosen_key": tuple((k, getattr(best_params, k)) for k in tuned_keys),
            }
        )
        start += step

    if not windows:
        raise ValueError(
            f"Not enough bars to walk-forward after reserving final 25% OOS: "
            f"have dev={dev_end}, need {train_bars + test_bars}. Use --bars to fetch more."
        )

    final_params, final_meta = _choose_final_oos_params(params, windows)
    final_key = _param_key(final_params)
    if final_key not in ind_cache:
        ind_cache[final_key] = apply_full_indicators(df_raw, final_params)
    final_oos = replay_on_df(
        ind_cache[final_key],
        final_params,
        start=holdout_start,
        end=total,
        verbose=False,
        include_trades=True,
    )

    test_rets = [w["test_ret"] for w in windows]
    positive = sum(1 for r in test_rets if r > 0)
    selection_keys = [w.get("chosen_key") for w in windows]
    transitions = sum(
        1 for i in range(1, len(selection_keys))
        if selection_keys[i] != selection_keys[i - 1]
    )

    return {
        "windows": windows,
        "n_windows": len(windows),
        "mean_test_ret": mean(test_rets),
        "median_test_ret": median(test_rets),
        "stdev_test_ret": stdev(test_rets) if len(test_rets) > 1 else 0.0,
        "positive_rate": positive / len(windows) * 100,
        "total_test_trades": sum(w["test_n"] for w in windows),
        "total_train_trades": sum(w["train_n"] for w in windows),
        "mean_test_mdd_pct": mean([w["test_mdd"] for w in windows]),
        "selection_transitions": transitions,
        "selection_transition_rate": (
            (transitions / max(1, len(windows) - 1)) * 100
        ),
        "unique_selected_configs": len(set(selection_keys)),
        "tuned_keys": tuned_keys,
        "n_candidates": len(candidates),
        "train_engine": eng,
        "optuna_trials_requested": int(optuna_trials) if eng == "optuna" else None,
        "optuna_trials_effective": optuna_budget,
        "optuna_seed": int(optuna_seed) if eng == "optuna" else None,
        "search_space_size": space_n if matrix else 1,
        "trade_mc": _mc_trade_resample(
            all_test_trade_returns, sims=int(mc_sims), seed=42
        ),
        "dev_end_bar": dev_end,
        "holdout_start_bar": holdout_start,
        "holdout_bars": max(0, total - holdout_start),
        "final_oos": {
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
        },
        "total_bars": total,
    }


def _parse_args() -> tuple[
    Params,
    int,
    int,
    Optional[int],
    dict[str, list],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    int,
    str,
    int,
    int,
]:
    p = argparse.ArgumentParser(description="Walk-forward validation.")
    # Strategy / risk
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--bars", type=int, default=3000,
                   help="Total bars to fetch. 3000 4h bars ~= 500 days.")
    p.add_argument("--strategy", default=STRATEGY,
                   choices=list_strategies(),
                   help=f"Strategy name. Available: {list_strategies()}")
    p.add_argument("--ema-short", type=int, default=EMA_SHORT)
    p.add_argument("--ema-long", type=int, default=EMA_LONG)
    p.add_argument("--trend", type=int, default=EMA_TREND)
    p.add_argument("--rsi-buy-max", type=float, default=RSI_BUY_MAX)
    p.add_argument("--rsi-sell-min", type=float, default=RSI_SELL_MIN)
    p.add_argument("--rsi-oversold", type=float, default=RSI_OVERSOLD)
    p.add_argument("--rsi-overbought", type=float, default=RSI_OVERBOUGHT)
    p.add_argument("--donchian-period", type=int, default=DONCHIAN_PERIOD)
    p.add_argument("--sweep-lookback", type=int, default=SWEEP_LOOKBACK)
    p.add_argument("--sweep-adx-period", type=int, default=SWEEP_ADX_PERIOD)
    p.add_argument("--sweep-adx-max", type=float, default=SWEEP_ADX_MAX)
    p.add_argument("--sweep-volume-mult", type=float,
                   default=SWEEP_VOLUME_MULT)
    p.add_argument("--sweep-volume-lookback", type=int,
                   default=SWEEP_VOLUME_LOOKBACK)
    p.add_argument("--stop", type=float, default=STOP_LOSS_PCT)
    p.add_argument("--take", type=float, default=TAKE_PROFIT_PCT)
    p.add_argument("--cooldown", type=int, default=ENTRY_COOLDOWN_BARS)
    p.add_argument("--allocation", type=float, default=TRADE_ALLOCATION_PCT)
    p.add_argument("--fee", type=float, default=FEE_PCT)
    # Generic filter toggles — use them to test whether a filter adds edge
    # without touching config.py.
    p.add_argument("--htf-confirm", action="store_true",
                   default=USE_HTF_CONFIRM)
    p.add_argument("--htf", default=HTF_TIMEFRAME)
    p.add_argument("--htf-ema", type=int, default=HTF_EMA_PERIOD)
    p.add_argument("--adx-filter", action="store_true",
                   default=USE_ADX_FILTER)
    p.add_argument("--adx-min", type=float, default=ADX_MIN)
    p.add_argument("--adx-max", type=float, default=ADX_MAX)
    p.add_argument("--vol-filter", action="store_true",
                   default=USE_VOLUME_FILTER)
    p.add_argument("--vol-mult", type=float, default=VOL_MULT)
    p.add_argument("--atr-filter", action="store_true",
                   default=USE_ATR_FILTER)
    p.add_argument("--atr-min-pct", type=float, default=ATR_MIN_PCT)
    p.add_argument("--macd-confirm", action="store_true",
                   default=USE_MACD_CONFIRM)
    # Walk-forward
    p.add_argument("--train-bars", type=int, default=500)
    p.add_argument("--test-bars", type=int, default=200)
    p.add_argument("--step", type=int, default=None,
                   help="Bars to advance between windows. Default = test-bars.")
    p.add_argument(
        "--opt",
        action="append",
        default=[],
        help=(
            "Train-window optimization grid clause key=v1,v2,... "
            "(repeatable). Example: --opt ema_short=10,12,14 "
            "--opt ema_long=40,50,60. If omitted, strategy-aware defaults are used."
        ),
    )
    p.add_argument(
        "--stability-out",
        default=None,
        help=(
            "Optional path to write stability/selection diagnostics JSON. "
            "If relative, it is resolved from the current working directory."
        ),
    )
    p.add_argument(
        "--stability-csv-out",
        default=None,
        help=(
            "Optional path to write heatmap-cell CSV "
            "(x_key,y_key,x,y,n_windows,mean_test_ret,...)"
        ),
    )
    p.add_argument(
        "--windows-csv-out",
        default=None,
        help=(
            "Optional path to write per-window diagnostics CSV "
            "(job meta + metrics + chosen_* columns)."
        ),
    )
    p.add_argument(
        "--report-out",
        default=None,
        help=(
            "Optional path for consolidated walk-forward JSON (job meta + summary "
            "+ windows); same schema as GET /walkforward/report.json."
        ),
    )
    p.add_argument(
        "--mc-sims",
        type=int,
        default=2000,
        help="Monte Carlo bootstrap simulation count for trade-order robustness.",
    )
    p.add_argument(
        "--train-engine",
        choices=["grid", "optuna"],
        default="grid",
        dest="train_engine",
        help=(
            "Train-window model selection: exhaustive grid vs Bayesian (Optuna TPE). "
            "Optuna is optional; pip install optuna>=3."
        ),
    )
    p.add_argument(
        "--optuna-trials",
        type=int,
        default=64,
        dest="optuna_trials",
        help="Optuna trials per train window (capped to grid search-space size).",
    )
    p.add_argument(
        "--optuna-seed",
        type=int,
        default=42,
        dest="optuna_seed",
        help="RNG seed for Optuna's TPESampler (reproducibility).",
    )
    a = p.parse_args()
    if int(a.optuna_trials) < 1:
        p.error("--optuna-trials must be >= 1")

    params = replace(
        Params(),
        symbol=a.symbol,
        timeframe=a.timeframe,
        bars=a.bars,
        strategy=a.strategy,
        ema_short=a.ema_short,
        ema_long=a.ema_long,
        ema_trend=a.trend,
        rsi_period=RSI_PERIOD,
        rsi_buy_max=a.rsi_buy_max,
        rsi_sell_min=a.rsi_sell_min,
        rsi_oversold=a.rsi_oversold,
        rsi_overbought=a.rsi_overbought,
        donchian_period=a.donchian_period,
        sweep_lookback=a.sweep_lookback,
        sweep_adx_period=a.sweep_adx_period,
        sweep_adx_max=a.sweep_adx_max,
        sweep_volume_mult=a.sweep_volume_mult,
        sweep_volume_lookback=a.sweep_volume_lookback,
        allocation_pct=a.allocation,
        stop_loss_pct=a.stop,
        take_profit_pct=a.take,
        entry_cooldown_bars=a.cooldown,
        fee_pct=a.fee,
        use_htf_confirm=a.htf_confirm,
        htf_timeframe=a.htf,
        htf_ema_period=a.htf_ema,
        use_adx_filter=a.adx_filter,
        adx_min=a.adx_min,
        adx_max=a.adx_max,
        use_volume_filter=a.vol_filter,
        vol_mult=a.vol_mult,
        use_atr_filter=a.atr_filter,
        atr_min_pct=a.atr_min_pct,
        use_macd_confirm=a.macd_confirm,
    )
    opt_matrix = _parse_opt_clauses(params, a.opt)
    return (
        params,
        a.train_bars,
        a.test_bars,
        a.step,
        opt_matrix,
        a.stability_out,
        a.stability_csv_out,
        a.windows_csv_out,
        a.report_out,
        a.mc_sims,
        a.train_engine,
        int(a.optuna_trials),
        int(a.optuna_seed),
    )


def main():
    (
        params,
        train_bars,
        test_bars,
        step,
        opt_matrix,
        stability_out,
        stability_csv_out,
        windows_csv_out,
        report_out,
        mc_sims,
        train_engine,
        optuna_trials,
        optuna_seed,
    ) = _parse_args()
    if params.strategy == "rsi_mean_reversion":
        extra = f"RSI {params.rsi_oversold:.0f}/{params.rsi_overbought:.0f} "
    elif params.strategy == "donchian_breakout":
        extra = f"Donchian {params.donchian_period} "
    elif params.strategy == "liquidity_sweep":
        extra = (
            f"Sweep {params.sweep_lookback} "
            f"ADX<{params.sweep_adx_max:.0f} "
            f"vol×{params.sweep_volume_mult:.1f} "
        )
    else:
        extra = f"EMA {params.ema_short}/{params.ema_long} "
    print(
        f"Config: [{params.strategy}] {params.symbol} {params.timeframe} "
        f"{extra}trend={params.ema_trend} "
        f"SL={params.stop_loss_pct*100:.1f}% "
        f"TP={params.take_profit_pct*100:.1f}% fee={params.fee_pct*100:.2f}%"
    )
    print(
        f"Walk-forward: train={train_bars} bars, test={test_bars} bars, "
        f"step={step or test_bars}"
    )

    r = walk_forward(
        params,
        train_bars,
        test_bars,
        step,
        opt_matrix=opt_matrix,
        mc_sims=mc_sims,
        train_engine=train_engine,
        optuna_trials=optuna_trials,
        optuna_seed=optuna_seed,
    )
    if opt_matrix:
        tuned_keys = ", ".join(opt_matrix.keys())
        print(f"WFO tuning grid: user-defined over [{tuned_keys}]")
    else:
        tuned_keys = ", ".join(r["tuned_keys"]) if r["tuned_keys"] else "(none)"
        eng_l = str(r.get("train_engine", "grid"))
        if eng_l == "optuna":
            print(
                f"WFO train selection [optuna]: strategy-aware over "
                f"[{tuned_keys}]; Cartesian space={r.get('search_space_size')}, "
                f"trials/window≤{r.get('optuna_trials_effective')} "
                f"(seed={r.get('optuna_seed')})"
            )
        else:
            print(
                f"WFO train selection [grid]: strategy-aware over "
                f"[{tuned_keys}] with {r['n_candidates']} candidates/window"
            )

    print(f"\nFetched {r['total_bars']} bars total.")
    print(f"{r['n_windows']} walk-forward windows.\n")

    headers = [
        "i", "train_ret", "test_ret", "train_n", "test_n",
        "test_wr", "test_mdd", "train_score"
    ]
    print(" ".join(f"{h:>10}" for h in headers))
    print("-" * (len(headers) * 11))
    for w in r["windows"]:
        print(
            " ".join(
                f"{w[h]:>10.2f}" if isinstance(w[h], float) else f"{w[h]:>10}"
                for h in headers
            )
        )
        if w.get("chosen"):
            chosen = ", ".join(f"{k}={v}" for k, v in w["chosen"].items())
            print(f"{'':>10} chosen -> {chosen}")

    print("\n=== Walk-forward summary ===")
    summary_rows = [
        ("windows", r["n_windows"]),
        ("mean test return %", r["mean_test_ret"]),
        ("median test return %", r["median_test_ret"]),
        ("stdev test return %", r["stdev_test_ret"]),
        ("mean test MDD %", r["mean_test_mdd_pct"]),
        ("positive windows %", r["positive_rate"]),
        ("total test trades", r["total_test_trades"]),
        ("unique selected cfgs", r["unique_selected_configs"]),
        ("selection changes %", r["selection_transition_rate"]),
        ("final OOS return %", (r.get("final_oos") or {}).get("return_pct", 0.0)),
        ("final OOS trades", (r.get("final_oos") or {}).get("trades", 0)),
    ]
    for k, v in summary_rows:
        if isinstance(v, float):
            print(f"  {k:<22} {v:>10.2f}")
        else:
            print(f"  {k:<22} {v:>10}")

    verdict = (
        "ROBUST" if r["positive_rate"] >= 60 and r["mean_test_ret"] > 0
        else "WEAK" if r["mean_test_ret"] > 0
        else "NOT VIABLE"
    )
    print(f"\n  verdict               {verdict:>10}")
    mc = r.get("trade_mc", {})
    if mc and mc.get("sims", 0) > 0:
        print("\n=== Monte Carlo (trade bootstrap) ===")
        print(f"  trades                  {mc.get('n_trades', 0):>10}")
        print(f"  simulations             {mc.get('sims', 0):>10}")
        print(f"  return p05 / p50 / p95  "
              f"{mc.get('ret_p05_pct', 0.0):>6.2f} / "
              f"{mc.get('ret_p50_pct', 0.0):>6.2f} / "
              f"{mc.get('ret_p95_pct', 0.0):>6.2f}")
        print(f"  mdd mean / p95          "
              f"{mc.get('mdd_mean_pct', 0.0):>6.2f} / "
              f"{mc.get('mdd_p95_pct', 0.0):>6.2f}")

    if stability_out:
        payload = {
            "meta": {
                "strategy": params.strategy,
                "symbol": params.symbol,
                "timeframe": params.timeframe,
                "train_bars": train_bars,
                "test_bars": test_bars,
                "step": step or test_bars,
                "n_candidates": r.get("n_candidates", 0),
                "train_engine": r.get("train_engine", "grid"),
                "optuna_trials_requested": r.get("optuna_trials_requested"),
                "optuna_trials_effective": r.get("optuna_trials_effective"),
                "optuna_seed": r.get("optuna_seed"),
                "search_space_size": r.get("search_space_size"),
                "tuned_keys": r.get("tuned_keys", []),
            },
            "summary": {
                "n_windows": r["n_windows"],
                "mean_test_ret": r["mean_test_ret"],
                "median_test_ret": r["median_test_ret"],
                "stdev_test_ret": r["stdev_test_ret"],
                "mean_test_mdd_pct": r.get("mean_test_mdd_pct", 0.0),
                "positive_rate": r["positive_rate"],
                "unique_selected_configs": r.get("unique_selected_configs", 0),
                "selection_transition_rate": r.get("selection_transition_rate", 0.0),
                "trade_mc": r.get("trade_mc", {}),
                "final_oos": r.get("final_oos"),
            },
            "windows": [
                {
                    "i": w["i"],
                    "train_ret": w["train_ret"],
                    "test_ret": w["test_ret"],
                    "train_n": w["train_n"],
                    "test_n": w["test_n"],
                    "test_wr": w["test_wr"],
                    "test_mdd": w.get("test_mdd", 0.0),
                    "train_score": w.get("train_score", 0.0),
                    "chosen": w.get("chosen", {}),
                }
                for w in r["windows"]
            ],
        }
        with open(stability_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\nWrote stability diagnostics -> {stability_out}")
    if stability_csv_out:
        matrix = _build_stability_matrix(r.get("windows", []), r.get("tuned_keys", []))
        fieldnames = [
            "x_key",
            "y_key",
            "x",
            "y",
            "n_windows",
            "mean_test_ret",
            "mean_test_mdd",
            "mean_train_score",
            "positive_rate",
        ]
        with open(stability_csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for cell in matrix.get("cells", []):
                w.writerow(
                    {
                        "x_key": matrix.get("x_key"),
                        "y_key": matrix.get("y_key"),
                        "x": cell.get("x"),
                        "y": cell.get("y"),
                        "n_windows": cell.get("n_windows"),
                        "mean_test_ret": round(float(cell.get("mean_test_ret", 0.0)), 6),
                        "mean_test_mdd": round(float(cell.get("mean_test_mdd", 0.0)), 6),
                        "mean_train_score": round(float(cell.get("mean_train_score", 0.0)), 6),
                        "positive_rate": round(float(cell.get("positive_rate", 0.0)), 6),
                    }
                )
        print(f"Wrote stability heatmap CSV -> {stability_csv_out}")
    if windows_csv_out:
        _write_walkforward_windows_csv(
            windows_csv_out,
            params=params,
            train_bars=train_bars,
            test_bars=test_bars,
            step=step or test_bars,
            total_bars=r["total_bars"],
            n_candidates=r.get("n_candidates", 0),
            tuned_keys=list(r.get("tuned_keys", [])),
            windows=r.get("windows", []),
            train_engine=str(r.get("train_engine", "grid")),
            optuna_trials_requested=r.get("optuna_trials_requested"),
            optuna_trials_effective=r.get("optuna_trials_effective"),
            optuna_seed=r.get("optuna_seed"),
            search_space_size=r.get("search_space_size"),
        )
        print(f"Wrote windows diagnostics CSV -> {windows_csv_out}")
    if report_out:
        wf_st = _wf_state_from_cli_result(
            params, train_bars, test_bars, step, mc_sims, r
        )
        with open(report_out, "w", encoding="utf-8") as fp:
            json.dump(walkforward_report_payload(wf_st), fp, indent=2)
        print(f"\nWrote full walk-forward JSON report -> {report_out}")


if __name__ == "__main__":
    main()
