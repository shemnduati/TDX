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

Output:
    - Per-window table (train/test returns, trades)
    - Aggregated summary (mean, median, stdev, % positive test windows)
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from statistics import mean, median, stdev
from typing import Optional

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


def walk_forward(
    params: Params,
    train_bars: int,
    test_bars: int,
    step: Optional[int] = None,
) -> dict:
    step = step or test_bars
    df = fetch_data(params)
    df = apply_full_indicators(df, params)

    total = len(df)
    warmup = get_strategy(params.strategy).warmup_bars(params)

    windows = []
    start = 0
    while start + train_bars + test_bars <= total:
        train_start = start
        train_end = start + train_bars
        test_start = train_end
        test_end = test_start + test_bars

        effective_train_start = max(train_start, warmup)
        if effective_train_start >= train_end:
            start += step
            continue

        train = replay_on_df(
            df, params, start=effective_train_start, end=train_end
        )
        test = replay_on_df(df, params, start=test_start, end=test_end)

        windows.append(
            {
                "i": len(windows),
                "train_ret": train.get("return_pct", 0.0),
                "test_ret": test.get("return_pct", 0.0),
                "train_n": train.get("trades", 0),
                "test_n": test.get("trades", 0),
                "test_wr": test.get("win_rate", 0.0),
            }
        )
        start += step

    if not windows:
        raise ValueError(
            f"Not enough bars to walk-forward: have {total}, "
            f"need {train_bars + test_bars}. Use --bars to fetch more."
        )

    test_rets = [w["test_ret"] for w in windows]
    positive = sum(1 for r in test_rets if r > 0)

    return {
        "windows": windows,
        "n_windows": len(windows),
        "mean_test_ret": mean(test_rets),
        "median_test_ret": median(test_rets),
        "stdev_test_ret": stdev(test_rets) if len(test_rets) > 1 else 0.0,
        "positive_rate": positive / len(windows) * 100,
        "total_test_trades": sum(w["test_n"] for w in windows),
        "total_train_trades": sum(w["train_n"] for w in windows),
        "total_bars": total,
    }


def _parse_args() -> tuple[Params, int, int, Optional[int]]:
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
    a = p.parse_args()
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
    return params, a.train_bars, a.test_bars, a.step


def main():
    params, train_bars, test_bars, step = _parse_args()
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

    r = walk_forward(params, train_bars, test_bars, step)

    print(f"\nFetched {r['total_bars']} bars total.")
    print(f"{r['n_windows']} walk-forward windows.\n")

    headers = ["i", "train_ret", "test_ret", "train_n", "test_n", "test_wr"]
    print(" ".join(f"{h:>10}" for h in headers))
    print("-" * (len(headers) * 11))
    for w in r["windows"]:
        print(
            " ".join(
                f"{w[h]:>10.2f}" if isinstance(w[h], float) else f"{w[h]:>10}"
                for h in headers
            )
        )

    print("\n=== Walk-forward summary ===")
    summary_rows = [
        ("windows", r["n_windows"]),
        ("mean test return %", r["mean_test_ret"]),
        ("median test return %", r["median_test_ret"]),
        ("stdev test return %", r["stdev_test_ret"]),
        ("positive windows %", r["positive_rate"]),
        ("total test trades", r["total_test_trades"]),
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


if __name__ == "__main__":
    main()
