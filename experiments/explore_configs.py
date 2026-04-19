"""
Experiment driver: multi-market sweep → Sharpe-rank → walk-forward validation.

This is the exact loop a serious human would run, coded up so the numbers
are reproducible. It intentionally uses everything we just built end-to-end:

  - `history.fetch_history` for cached OHLCV
  - `backtest.replay_on_df` + `apply_full_indicators` for per-config backtests
  - `walkforward.walk_forward` for out-of-sample robustness

Philosophy
----------
  1. Optimise for `trade_sharpe`, not raw return. High-return + low-Sharpe
     is the classic overfit signature: one big win and a lot of noise.
  2. Require at least MIN_TRADES. Fewer than that and even the "good"
     configs are within noise.
  3. Confirm on walk-forward: the backtest is in-sample by definition;
     only WF gives us out-of-sample evidence.
  4. Across markets: require a config to work on both the 1h and 4h
     samples before we'd consider it as a new baseline. A strategy that
     only works on one timeframe is probably curve-fit to that regime.

Run
---
    python -m experiments.explore_configs            # reuses cached sweep
    python -m experiments.explore_configs --fresh    # force full re-run
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, replace
from itertools import product
from typing import Any

import pandas as pd

import history as _history_mod
from backtest import Params, apply_full_indicators, replay_on_df
from utils import format_data
from walkforward import walk_forward

_real_fetch_history = _history_mod.fetch_history


def _cache_first_fetch_history(
    symbol: str,
    timeframe: str,
    bars: int,
    use_cache: bool = True,
):
    """Cache-first override of `history.fetch_history`.

    The real function always hits the network to freshen the cache with
    any bars newer than the latest cached one. That makes one flaky call
    enough to crash a 30-minute experiment that already has all the data
    it needs. For the experiment driver we don't care about the very
    latest 1–2 bars — we just need `bars` recent samples to replay.

    Behaviour:
      * If the on-disk cache already has >= `bars` entries, slice off the
        last `bars` without touching the network.
      * Otherwise, fall back to the real fetch-and-cache path.
    """
    if use_cache:
        cached = _history_mod._dedupe_sorted(
            _history_mod._load_cache(_history_mod._cache_path(symbol, timeframe))
        )
        if len(cached) >= bars:
            return format_data(cached[-bars:])
    return _real_fetch_history(symbol, timeframe, bars, use_cache=use_cache)


# Patch both the history module itself and the already-imported reference
# in backtest (which did `from history import fetch_history` at import
# time, so it caches the original function object). Everyone — including
# backtest.fetch_data and walkforward.walk_forward — now goes through
# the cache-first path.
_history_mod.fetch_history = _cache_first_fetch_history
import backtest as _backtest_mod  # noqa: E402
_backtest_mod.fetch_history = _cache_first_fetch_history

HERE = os.path.dirname(__file__)
SWEEP_CACHE = os.path.join(HERE, "last_sweep.json")
REPORT_JSON = os.path.join(HERE, "last_run.json")


@contextlib.contextmanager
def _silenced():
    """PaperTrader spams OPEN/CLOSE prints — kill them during backtests so
    the progress output stays readable. We still capture results via return
    values, not stdout."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ------------------------------------------------------------------ config

# Each market is one (symbol, timeframe, bars, wf_train, wf_test) experiment.
# WF window sizes are chosen to give ~15 windows — enough that the mean
# test return is a meaningful statistic, not a lottery ticket.
MARKETS: list[dict[str, Any]] = [
    {
        "id": "BTC-4h",
        "symbol": "BTC/USDT",
        "timeframe": "4h",
        "bars": 10000,       # ~4.5 years back to 2021 — 2022 bear, 2024 halving, 2025 top
        "wf_train": 2000,    # ~333 days
        "wf_test": 500,      # ~83 days  -> ~16 windows
    },
    {
        "id": "ETH-4h",
        "symbol": "ETH/USDT",
        "timeframe": "4h",
        "bars": 10000,       # matched to BTC so cross-market comparison is apples-to-apples
        "wf_train": 2000,
        "wf_test": 500,
    },
    # Keep the 1h data as a sanity-check market — it's a different regime to 4h
    # and has 8+ years of history. Using 20k bars ≈ 2.3 years.
    {
        "id": "BTC-1h",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "bars": 20000,
        "wf_train": 4000,
        "wf_test": 1000,     # -> ~16 windows
    },
]

# One grid per strategy. Wider than the first pass — more ATR multipliers,
# extra EMA trend windows (100 in addition to 0/200), narrower RSI grid
# (we already know the sensitivity is low there).
STRATEGY_GRIDS: dict[str, dict[str, list[Any]]] = {
    "ema_crossover": {
        "ema_short": [12, 20],
        "ema_long": [26, 50],
        "ema_trend": [0, 100, 200],
        "use_atr_sizing": [False, True],
        # Filter toggles — flipped independently so we can see each one's
        # marginal contribution in the cross-market leaderboard. Keep the
        # grid lean; add more toggles only if the cheap ones don't help.
        "use_htf_confirm": [False, True],
        "use_adx_filter": [False, True],
    },
    "rsi_mean_reversion": {
        "rsi_oversold": [25, 30],
        "rsi_overbought": [70, 75],
        "ema_trend": [0, 100, 200],
        "use_atr_sizing": [False, True],
        # MR wants range-bound regimes — ADX<max is the natural filter.
        "use_adx_filter": [False, True],
        "use_htf_confirm": [False, True],
    },
    "donchian_breakout": {
        "donchian_period": [20, 40, 55],
        "ema_trend": [0, 100, 200],
        "use_atr_sizing": [False, True],
        "atr_stop_mult": [2.0, 2.5, 3.0],
        # Breakouts need participation and volatility to work.
        "use_volume_filter": [False, True],
        "use_htf_confirm": [False, True],
    },
    "liquidity_sweep": {
        "sweep_lookback": [20, 40],
        "sweep_adx_max": [20.0, 25.0],
        "sweep_volume_mult": [1.3, 1.7],
        "use_atr_sizing": [True],  # ATR sizing is mandatory for this one
        "use_htf_confirm": [False, True],
    },
}

# Per-strategy presets for filter sub-knobs: when a toggle like
# `use_adx_filter` flips on, these supply the sensible companion values so
# we don't have to blow up the grid width.
STRATEGY_FILTER_PRESETS: dict[str, dict[str, Any]] = {
    "ema_crossover": {
        "adx_min": 20.0,          # trend strategy: require ADX > 20
        "adx_max": 0.0,
        "htf_timeframe": "1d",
        "htf_ema_period": 50,
    },
    "rsi_mean_reversion": {
        "adx_min": 0.0,
        "adx_max": 20.0,          # MR: require ADX < 20 (ranging)
        "htf_timeframe": "1d",
        "htf_ema_period": 50,
    },
    "donchian_breakout": {
        "vol_mult": 1.3,
        "htf_timeframe": "1d",
        "htf_ema_period": 50,
    },
    "liquidity_sweep": {
        "htf_timeframe": "1d",
        "htf_ema_period": 50,
    },
}

MIN_TRADES = 20
WF_TOP_K = 20        # how many top-by-Sharpe candidates to walk-forward per market.
                     # Big enough that the WF ranking doesn't depend on Sharpe picking
                     # the right few — we let WF do the selection instead.
CROSS_MKT_TOP = 8    # final cross-market leaderboard size

# WF score used to rank walk-forward results. Effectively a per-window
# Sharpe ratio — positive mean and low stdev both help, and the
# positive_rate multiplier penalises configs that only work when the
# lucky window shows up.
WF_SCORE_EPS = 1e-6


def wf_score(mean_test: float, stdev_test: float, positive_rate: float) -> float:
    """Combined OOS score: Sharpe-of-windows × consistency.

    Returns 0 when WF mean is negative — there's no 'good' version of a
    losing strategy, no matter how low its variance is.
    """
    if mean_test <= 0:
        return 0.0
    sharpe_windows = mean_test / (stdev_test + WF_SCORE_EPS)
    consistency = max(0.0, (positive_rate - 50) / 50)  # 0..1, scoring >50% wins
    return sharpe_windows * (0.3 + 0.7 * consistency)


# ------------------------------------------------------------- core loop


def _run_backtest(df: pd.DataFrame, params: Params) -> dict:
    tmp = os.path.join(tempfile.gettempdir(), "tdx_explore_bt.json")
    with _silenced():
        df2 = apply_full_indicators(df.copy(), params)
        summary = replay_on_df(df2, params, data_file=tmp, verbose=False)
    return {"summary": summary, "params": asdict(params)}


def _combos(grid: dict[str, list[Any]]) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, c)) for c in product(*[grid[k] for k in keys])]


def _label(strategy: str, overrides: dict) -> str:
    bits = []
    for k, v in overrides.items():
        if k == "atr_stop_mult" and not overrides.get("use_atr_sizing"):
            continue  # dead knob when ATR sizing is off
        bits.append(f"{k}={v}")
    return f"{strategy} · {' · '.join(bits)}"


def _apply_filter_presets(strategy: str, overrides: dict) -> dict:
    """Merge companion values for whichever filter toggles are on.

    Keeps the grid small: the user flips ONE boolean, and this function
    injects the knobs the strategy typically wants alongside it.
    """
    presets = STRATEGY_FILTER_PRESETS.get(strategy, {})
    extras: dict[str, Any] = {}
    if overrides.get("use_adx_filter"):
        for k in ("adx_min", "adx_max"):
            if k in presets:
                extras[k] = presets[k]
    if overrides.get("use_htf_confirm"):
        for k in ("htf_timeframe", "htf_ema_period"):
            if k in presets:
                extras[k] = presets[k]
    if overrides.get("use_volume_filter") and "vol_mult" in presets:
        extras["vol_mult"] = presets["vol_mult"]
    return extras


def run_sweep_for_market(market: dict) -> list[dict]:
    df = _cache_first_fetch_history(
        market["symbol"], market["timeframe"], market["bars"]
    )
    print(
        f"[sweep] market={market['id']} {market['symbol']} {market['timeframe']} "
        f"bars={len(df)}  {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}"
    )

    base = replace(
        Params(),
        symbol=market["symbol"],
        timeframe=market["timeframe"],
        bars=market["bars"],
        initial_balance=1000.0,
        fee_pct=0.001,
    )

    results: list[dict] = []
    for strategy, grid in STRATEGY_GRIDS.items():
        combos = _combos(grid)
        print(f"  [{strategy}] {len(combos)} configs")
        t0 = time.time()
        for i, overrides in enumerate(combos, 1):
            extras = _apply_filter_presets(strategy, overrides)
            params = replace(base, strategy=strategy, **overrides, **extras)
            out = _run_backtest(df, params)
            out["label"] = _label(strategy, overrides)
            out["strategy"] = strategy
            out["overrides"] = overrides
            out["market"] = market["id"]
            results.append(out)
            if i % 10 == 0 or i == len(combos):
                print(f"    {i}/{len(combos)} in {time.time()-t0:.1f}s")
    return results


def run_all_sweeps() -> dict[str, list[dict]]:
    per_market: dict[str, list[dict]] = {}
    for market in MARKETS:
        per_market[market["id"]] = run_sweep_for_market(market)
        print()
    return per_market


# ------------------------------------------------------------- reporting


def _rank_row(r: dict) -> dict:
    s = r["summary"]
    return {
        "market": r["market"],
        "label": r["label"],
        "strategy": r["strategy"],
        "trades": s.get("trades", 0),
        "return_pct": s.get("return_pct", 0.0),
        "sharpe": s.get("trade_sharpe", 0.0),
        "pf": s.get("profit_factor", 0.0),
        "max_dd": s.get("max_drawdown_pct", 0.0),
        "win_rate": s.get("win_rate", 0.0),
    }


def _print_leaderboard(rows: list[dict], title: str, top: int) -> None:
    print(f"=== {title} ===\n")
    hdr = (f"{'market':<8} {'strat':<20} {'trades':>6} {'ret%':>7} "
           f"{'sharpe':>7} {'pf':>6} {'maxdd%':>7} {'wr%':>6}  label")
    print(hdr)
    print("-" * len(hdr))
    for r in rows[:top]:
        print(
            f"{r['market']:<8} {r['strategy']:<20} {r['trades']:>6} "
            f"{r['return_pct']:>7.2f} {r['sharpe']:>7.3f} "
            f"{r['pf']:>6.2f} {r['max_dd']:>7.2f} {r['win_rate']:>6.1f}  "
            f"{r['label']}"
        )
    print()


def rank_per_market(per_market: dict[str, list[dict]]) -> dict[str, list[dict]]:
    ranked: dict[str, list[dict]] = {}
    for mkt_id, results in per_market.items():
        rows = [_rank_row(r) for r in results]
        qualified = [r for r in rows if r["trades"] >= MIN_TRADES]
        rejected = len(rows) - len(qualified)
        qualified.sort(key=lambda r: r["sharpe"], reverse=True)
        _print_leaderboard(
            qualified,
            f"{mkt_id} top 10 by trade_sharpe "
            f"(trades >= {MIN_TRADES}, dropped {rejected} low-activity)",
            top=10,
        )
        ranked[mkt_id] = qualified
    return ranked


def _verdict(pos: float, mean: float) -> str:
    if pos >= 60 and mean > 0:
        return "ROBUST"
    if mean > 0:
        return "WEAK"
    return "NOT_VIABLE"


def run_walkforward_per_market(
    ranked: dict[str, list[dict]],
    per_market: dict[str, list[dict]],
) -> list[dict]:
    wf_rows: list[dict] = []
    for market in MARKETS:
        mkt_id = market["id"]
        candidates = ranked[mkt_id][:WF_TOP_K]
        print(f"=== Walk-forward for {mkt_id} "
              f"(train={market['wf_train']}, test={market['wf_test']}, "
              f"{len(candidates)} candidates) ===")
        by_label = {r["label"]: r for r in per_market[mkt_id]}
        t0 = time.time()
        for i, row in enumerate(candidates, 1):
            hit = by_label[row["label"]]
            params = Params(**hit["params"])
            try:
                with _silenced():
                    wf = walk_forward(params, market["wf_train"], market["wf_test"])
            except ValueError as e:
                print(f"  [{i}/{len(candidates)}] skipped ({e}) · {row['label']}")
                continue
            mean = wf["mean_test_ret"]
            pos = wf["positive_rate"]
            stdev = wf["stdev_test_ret"]
            verdict = _verdict(pos, mean)
            score = wf_score(mean, stdev, pos)
            print(
                f"  [{i}/{len(candidates)}] "
                f"score={score:>5.2f}  mean={mean:>6.2f}%  pos={pos:>3.0f}%  "
                f"std={stdev:>5.2f}%  {verdict:<11}  {row['label']}"
            )
            wf_rows.append({
                "market": mkt_id,
                "label": row["label"],
                "strategy": row["strategy"],
                "backtest_sharpe": row["sharpe"],
                "backtest_ret": row["return_pct"],
                "wf_n_windows": wf["n_windows"],
                "wf_mean_test": mean,
                "wf_positive_rate": pos,
                "wf_stdev_test": stdev,
                "wf_score": score,
                "wf_verdict": verdict,
                "params": hit["params"],
            })
        print(f"  ({time.time()-t0:.1f}s)\n")
    return wf_rows


def cross_market_report(wf_rows: list[dict]) -> None:
    """Two tables:
    1. Best config *per market*, ranked by WF score (OOS, not in-sample).
    2. Cross-market survivors — same label showing up on >1 market.
    """
    if not wf_rows:
        print("\nNo WF rows to report.")
        return

    # ---- per-market WF leaderboards -----------------------------------
    print("=== Per-market WF ranking (top by wf_score, OOS-first) ===\n")
    grouped: dict[str, list[dict]] = {}
    for r in wf_rows:
        grouped.setdefault(r["market"], []).append(r)
    for mkt_id, rows in grouped.items():
        rows.sort(key=lambda r: r["wf_score"], reverse=True)
        print(f"[{mkt_id}]")
        hdr = (f"  {'strat':<20} {'score':>6} {'wf_mean%':>9} {'wf_pos%':>8} "
               f"{'wf_std%':>8} {'bt_shrp':>8} {'bt_ret%':>8} {'verdict':>11}  label")
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for r in rows[:8]:
            print(
                f"  {r['strategy']:<20} "
                f"{r['wf_score']:>6.2f} "
                f"{r['wf_mean_test']:>9.2f} "
                f"{r['wf_positive_rate']:>8.0f} "
                f"{r['wf_stdev_test']:>8.2f} "
                f"{r['backtest_sharpe']:>8.3f} "
                f"{r['backtest_ret']:>8.2f} "
                f"{r['wf_verdict']:>11}  "
                f"{r['label']}"
            )
        print()

    # ---- cross-market survivors ---------------------------------------
    by_label: dict[str, dict] = {}
    for r in wf_rows:
        d = by_label.setdefault(r["label"], {
            "label": r["label"],
            "strategy": r["strategy"],
            "params": r["params"],
            "markets": [],
            "verdicts": [],
            "wf_mean_tests": [],
            "wf_pos_rates": [],
            "wf_scores": [],
            "bt_sharpes": [],
            "bt_rets": [],
        })
        d["markets"].append(r["market"])
        d["verdicts"].append(r["wf_verdict"])
        d["wf_mean_tests"].append(r["wf_mean_test"])
        d["wf_pos_rates"].append(r["wf_positive_rate"])
        d["wf_scores"].append(r["wf_score"])
        d["bt_sharpes"].append(r["backtest_sharpe"])
        d["bt_rets"].append(r["backtest_ret"])

    multi = [d for d in by_label.values() if len(d["markets"]) > 1]
    if not multi:
        print("=== Cross-market survivors ===\n")
        print("(no config reached the WF stage on more than one market)\n")
        return

    print("=== Cross-market survivors (same label, WF'd on >1 market) ===\n")
    hdr = (f"{'strategy':<20} {'markets':<20} {'verdicts':<25} "
           f"{'min_score':>10} {'avg_score':>10} {'avg_mean%':>10} {'min_pos%':>9}  label")
    print(hdr)
    print("-" * len(hdr))

    def _sort_key(d: dict) -> tuple:
        all_non_losing = all(v != "NOT_VIABLE" for v in d["verdicts"])
        any_robust = any(v == "ROBUST" for v in d["verdicts"])
        return (all_non_losing, any_robust, min(d["wf_scores"]))

    multi.sort(key=_sort_key, reverse=True)
    for d in multi[:CROSS_MKT_TOP]:
        avg_mean = sum(d["wf_mean_tests"]) / len(d["wf_mean_tests"])
        avg_score = sum(d["wf_scores"]) / len(d["wf_scores"])
        min_score = min(d["wf_scores"])
        min_pos = min(d["wf_pos_rates"])
        print(
            f"{d['strategy']:<20} "
            f"{','.join(d['markets']):<20} "
            f"{','.join(d['verdicts']):<25} "
            f"{min_score:>10.2f} {avg_score:>10.2f} "
            f"{avg_mean:>10.2f} {min_pos:>9.0f}  "
            f"{d['label']}"
        )
    print()

    # ---- the one recommendation ---------------------------------------
    winners = [d for d in multi if all(v != "NOT_VIABLE" for v in d["verdicts"])]
    if winners:
        best = winners[0]
        print("=== RECOMMENDED BASELINE ===")
        print(f"  {best['label']}")
        print(f"  Markets: {', '.join(best['markets'])}")
        print(f"  Verdicts: {', '.join(best['verdicts'])}")
        print(f"  Avg WF mean: {sum(best['wf_mean_tests'])/len(best['wf_mean_tests']):.2f}%")
        print(f"  Min WF pos-rate: {min(best['wf_pos_rates']):.0f}%")
        print()
    else:
        print("(no config was non-NOT_VIABLE on every market it was tested on)\n")


# ------------------------------------------------------------------- main


def main(fresh: bool = False) -> None:
    if not fresh and os.path.exists(SWEEP_CACHE):
        with open(SWEEP_CACHE) as f:
            per_market = json.load(f)
        # Guard: if the shape doesn't match the current MARKETS list, re-run.
        expected = {m["id"] for m in MARKETS}
        if set(per_market.keys()) != expected:
            print(f"[sweep] cache markets {set(per_market.keys())} != {expected}; forcing fresh run")
            per_market = run_all_sweeps()
            with open(SWEEP_CACHE, "w") as f:
                json.dump(per_market, f)
        else:
            total = sum(len(v) for v in per_market.values())
            print(f"[sweep] Loaded {total} cached configs across "
                  f"{len(per_market)} markets from {SWEEP_CACHE}")
            print("        (pass --fresh to force a full re-run)\n")
    else:
        per_market = run_all_sweeps()
        with open(SWEEP_CACHE, "w") as f:
            json.dump(per_market, f)
        total = sum(len(v) for v in per_market.values())
        print(f"[sweep] Cached {total} configs -> {SWEEP_CACHE}\n")

    ranked = rank_per_market(per_market)
    wf_rows = run_walkforward_per_market(ranked, per_market)
    cross_market_report(wf_rows)

    with open(REPORT_JSON, "w") as f:
        json.dump({
            "markets": MARKETS,
            "ranked_per_market": ranked,
            "walkforward": wf_rows,
        }, f, indent=2, default=str)
    print(f"Saved detailed report -> {REPORT_JSON}")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    main(fresh=fresh)
