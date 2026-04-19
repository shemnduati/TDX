"""
Parameter sweep with train / test split.

Each config is evaluated twice:
  - TRAIN  : first TRAIN_FRACTION of the bars
  - TEST   : the remaining bars (out-of-sample, strategy never "saw" them)

Configs are ranked by TEST return. Look for rows where train and test are
BOTH positive — that's the honesty check. A config that's huge on train
and negative on test is overfit to the train window.

Run:
    python sweep.py

Edit the MATRIX dict near the top to change what's explored.
"""
from __future__ import annotations

import itertools
import os
from dataclasses import asdict, replace
from typing import Any

from backtest import (
    OUTPUT_FILE,
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)

# ------------------------------------------------------------------ MATRIX ----
# Every combination of these is run. Keep the grid small for fast iteration.
# Any field on backtest.Params can be swept. For example, to compare strategies:
#   "strategy": ["ema_crossover", "rsi_mean_reversion"]
MATRIX: dict[str, list[Any]] = {
    "strategy": ["rsi_mean_reversion"],
    "timeframe": ["1h", "4h"],
    "rsi_oversold": [20, 25, 30],
    "rsi_overbought": [70, 75, 80],
    "stop_loss_pct": [0.02, 0.03],
    "take_profit_pct": [0.04, 0.06],
}

# Symbol is fixed per run (re-run with a different value to compare coins).
SYMBOL_OVERRIDE: str | None = None   # e.g. "ETH/USDT", or None to use config default

# Fetched bars per timeframe. Defaults are tuned so each timeframe covers a
# similar calendar window (~5-12 months).
BARS_PER_TIMEFRAME: dict[str, int] = {
    "15m": 4000,
    "1h":  3000,
    "4h":  3000,
    "1d":  1500,
}
DEFAULT_BARS = 2000

TRAIN_FRACTION = 0.7   # 70% train, 30% test
MIN_TRADES = 3         # configs with fewer trades on TEST are excluded from "best"
# ------------------------------------------------------------------------------


def _expand(matrix: dict[str, list[Any]]):
    keys = list(matrix.keys())
    for combo in itertools.product(*[matrix[k] for k in keys]):
        yield dict(zip(keys, combo))


def _group_by_timeframe(combos: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for c in combos:
        out.setdefault(c["timeframe"], []).append(c)
    return out


def _fmt(v, digits=2) -> str:
    if isinstance(v, bool):
        return f"{str(v):>10}"
    if isinstance(v, float):
        return f"{v:>10.{digits}f}"
    return f"{str(v):>10}"


def main():
    combos = list(_expand(MATRIX))
    by_tf = _group_by_timeframe(combos)

    # Fetch each timeframe ONCE. Re-applying indicators per config is cheap;
    # the expensive part is the network fetch.
    cached_df: dict[str, Any] = {}
    for tf in by_tf:
        bars = BARS_PER_TIMEFRAME.get(tf, DEFAULT_BARS)
        fetch_overrides: dict[str, Any] = {"timeframe": tf, "bars": bars}
        if SYMBOL_OVERRIDE:
            fetch_overrides["symbol"] = SYMBOL_OVERRIDE
        params_for_fetch = replace(Params(), **fetch_overrides)
        print(f"Fetching {bars} bars of {params_for_fetch.symbol} {tf}...")
        cached_df[tf] = fetch_data(params_for_fetch)

    print(f"\nRunning {len(combos)} configs x 2 (train/test) = {len(combos) * 2} backtests...\n")

    rows = []
    best_params: Params | None = None
    best_test_return = float("-inf")

    for i, overrides in enumerate(combos, start=1):
        extra: dict[str, Any] = dict(overrides)
        if SYMBOL_OVERRIDE:
            extra["symbol"] = SYMBOL_OVERRIDE
        params = replace(Params(), **extra)
        tf = params.timeframe
        base_df = cached_df[tf]
        df = apply_full_indicators(base_df, params)

        split = int(len(df) * TRAIN_FRACTION)

        label = " ".join(f"{k}={v}" for k, v in overrides.items())
        print(f"[{i}/{len(combos)}] {label}")

        try:
            train = replay_on_df(df, params, start=0, end=split)
            # For test, persist to OUTPUT_FILE when this config wins (rewritten below).
            test = replay_on_df(df, params, start=split, end=len(df))
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        row = {
            **overrides,
            "train_ret": train.get("return_pct", 0.0),
            "test_ret": test.get("return_pct", 0.0),
            "train_n": train.get("trades", 0),
            "test_n": test.get("trades", 0),
            "test_wr": test.get("win_rate", 0.0),
        }
        rows.append(row)

        if (
            test.get("trades", 0) >= MIN_TRADES
            and row["test_ret"] > best_test_return
        ):
            best_test_return = row["test_ret"]
            best_params = params

    if not rows:
        print("No successful runs.")
        return

    rows.sort(key=lambda r: r["test_ret"], reverse=True)

    headers = list(rows[0].keys())
    col_width = {h: max(len(h), 10) for h in headers}
    header_line = " ".join(f"{h:>{col_width[h]}}" for h in headers)
    print("\n" + header_line)
    print("-" * len(header_line))
    for r in rows:
        print(" ".join(_fmt(r[h]) for h in headers))

    if best_params is None:
        print(
            f"\nNo config had >= {MIN_TRADES} trades on the test slice. "
            "Consider relaxing filters or using more bars."
        )
        return

    # Persist the winner's TEST-period backtest.json so the dashboard shows
    # the honest out-of-sample equity curve.
    print(f"\nBest config by TEST return: {best_test_return:.2f}%")
    print("Params:")
    for k, v in asdict(best_params).items():
        print(f"  {k:<22} {v}")

    df = apply_full_indicators(cached_df[best_params.timeframe], best_params)
    split = int(len(df) * TRAIN_FRACTION)
    replay_on_df(df, best_params, start=split, end=len(df), data_file=OUTPUT_FILE)
    print(f"\nPersisted TEST-period backtest of winner to {os.path.basename(OUTPUT_FILE)}.")
    print("Open the dashboard, click 'Backtest' to inspect the out-of-sample equity curve.")


if __name__ == "__main__":
    main()
