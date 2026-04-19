"""
Replay the live strategy over historical OHLCV and write `backtest.json`.

Run:
    python backtest.py                              # use config.py defaults
    python backtest.py --timeframe 1h               # override timeframe
    python backtest.py --timeframe 4h --stop 0.03 --take 0.06 --fee 0.001

The output file has the same schema as `data.json`, so the existing
dashboard can render backtest results by hitting `/backtest` instead of
`/data`. A toggle in the React header switches between them.

Public API (used by `sweep.py`):
    fetch_data(params)      -> DataFrame
    apply_full_indicators(df, params) -> DataFrame
    replay_on_df(df, params, start=None, end=None, data_file=None, verbose=False)
        -> dict summary
    run(params, verbose=True) -> dict summary        # fetches + replays
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import (
    SYMBOL,
    TIMEFRAME,
    BACKTEST_BARS,
    STRATEGY,
    EMA_SHORT,
    EMA_LONG,
    EMA_TREND,
    RSI_PERIOD,
    RSI_BUY_MAX,
    RSI_SELL_MIN,
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    DONCHIAN_PERIOD,
    SWEEP_LOOKBACK,
    SWEEP_ADX_PERIOD,
    SWEEP_ADX_MAX,
    SWEEP_VOLUME_MULT,
    SWEEP_VOLUME_LOOKBACK,
    INITIAL_BALANCE,
    TRADE_ALLOCATION_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    ENTRY_COOLDOWN_BARS,
    FEE_PCT,
    USE_ATR_SIZING,
    ATR_PERIOD,
    ATR_RISK_PCT,
    ATR_STOP_MULT,
    ATR_TP_MULT,
    USE_HTF_CONFIRM,
    HTF_TIMEFRAME,
    HTF_EMA_PERIOD,
    USE_ADX_FILTER,
    FILTER_ADX_PERIOD,
    ADX_MIN,
    ADX_MAX,
    USE_VOLUME_FILTER,
    VOL_MA_PERIOD,
    VOL_MULT,
    USE_ATR_FILTER,
    ATR_MIN_PCT,
    USE_MACD_CONFIRM,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
)
from history import fetch_history
from paper_trader import PaperTrader
from strategies import (
    attach_filter_indicators,
    attach_htf_trend,
    filter_warmup_bars,
    get_strategy,
    list_strategies,
)

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "backtest.json"
)


@dataclass
class Params:
    symbol: str = SYMBOL
    timeframe: str = TIMEFRAME
    bars: int = BACKTEST_BARS
    strategy: str = STRATEGY
    ema_short: int = EMA_SHORT
    ema_long: int = EMA_LONG
    ema_trend: int = EMA_TREND
    rsi_period: int = RSI_PERIOD
    rsi_buy_max: float = RSI_BUY_MAX
    rsi_sell_min: float = RSI_SELL_MIN
    rsi_oversold: float = RSI_OVERSOLD
    rsi_overbought: float = RSI_OVERBOUGHT
    donchian_period: int = DONCHIAN_PERIOD
    sweep_lookback: int = SWEEP_LOOKBACK
    sweep_adx_period: int = SWEEP_ADX_PERIOD
    sweep_adx_max: float = SWEEP_ADX_MAX
    sweep_volume_mult: float = SWEEP_VOLUME_MULT
    sweep_volume_lookback: int = SWEEP_VOLUME_LOOKBACK
    initial_balance: float = INITIAL_BALANCE
    allocation_pct: float = TRADE_ALLOCATION_PCT
    stop_loss_pct: float = STOP_LOSS_PCT
    take_profit_pct: float = TAKE_PROFIT_PCT
    entry_cooldown_bars: int = ENTRY_COOLDOWN_BARS
    fee_pct: float = FEE_PCT
    # ATR-based sizing (optional). When use_atr_sizing is True, SL/TP and
    # position size are derived from ATR instead of fixed percentages.
    use_atr_sizing: bool = USE_ATR_SIZING
    atr_period: int = ATR_PERIOD
    atr_risk_pct: float = ATR_RISK_PCT
    atr_stop_mult: float = ATR_STOP_MULT
    atr_tp_mult: float = ATR_TP_MULT
    # --- Generic filters (see strategies.filters_pass for the gate logic) ---
    # Each is off by default; flip one on to see whether it improves WF score.
    use_htf_confirm: bool = USE_HTF_CONFIRM
    htf_timeframe: str = HTF_TIMEFRAME
    htf_ema_period: int = HTF_EMA_PERIOD
    use_adx_filter: bool = USE_ADX_FILTER
    filter_adx_period: int = FILTER_ADX_PERIOD
    adx_min: float = ADX_MIN
    adx_max: float = ADX_MAX
    use_volume_filter: bool = USE_VOLUME_FILTER
    vol_ma_period: int = VOL_MA_PERIOD
    vol_mult: float = VOL_MULT
    use_atr_filter: bool = USE_ATR_FILTER
    atr_min_pct: float = ATR_MIN_PCT
    use_macd_confirm: bool = USE_MACD_CONFIRM
    macd_fast: int = MACD_FAST
    macd_slow: int = MACD_SLOW
    macd_signal: int = MACD_SIGNAL


# ---------------------------------------------------------------------- CLI ---
def _parse_args() -> Params:
    p = argparse.ArgumentParser(description="Backtest a strategy.")
    p.add_argument("--symbol", default=SYMBOL)
    p.add_argument("--timeframe", default=TIMEFRAME,
                   help="e.g. 5m, 15m, 1h, 4h, 1d")
    p.add_argument("--bars", type=int, default=BACKTEST_BARS)
    p.add_argument("--strategy", default=STRATEGY,
                   choices=list_strategies(),
                   help=f"Strategy name. Available: {list_strategies()}")
    p.add_argument("--ema-short", type=int, default=EMA_SHORT)
    p.add_argument("--ema-long", type=int, default=EMA_LONG)
    p.add_argument("--trend", type=int, default=EMA_TREND,
                   help="EMA trend filter period (0 to disable)")
    p.add_argument("--rsi-buy-max", type=float, default=RSI_BUY_MAX)
    p.add_argument("--rsi-sell-min", type=float, default=RSI_SELL_MIN)
    p.add_argument("--rsi-oversold", type=float, default=RSI_OVERSOLD)
    p.add_argument("--rsi-overbought", type=float, default=RSI_OVERBOUGHT)
    p.add_argument("--donchian-period", type=int, default=DONCHIAN_PERIOD)
    p.add_argument("--sweep-lookback", type=int, default=SWEEP_LOOKBACK,
                   help="liquidity_sweep: N-bar swing high/low to fade")
    p.add_argument("--sweep-adx-period", type=int, default=SWEEP_ADX_PERIOD)
    p.add_argument("--sweep-adx-max", type=float, default=SWEEP_ADX_MAX,
                   help="liquidity_sweep: skip when ADX >= this (0 disables)")
    p.add_argument("--sweep-volume-mult", type=float,
                   default=SWEEP_VOLUME_MULT,
                   help="liquidity_sweep: required vol multiple over median")
    p.add_argument("--sweep-volume-lookback", type=int,
                   default=SWEEP_VOLUME_LOOKBACK)
    p.add_argument("--stop", type=float, default=STOP_LOSS_PCT)
    p.add_argument("--take", type=float, default=TAKE_PROFIT_PCT)
    p.add_argument("--cooldown", type=int, default=ENTRY_COOLDOWN_BARS)
    p.add_argument("--allocation", type=float, default=TRADE_ALLOCATION_PCT)
    p.add_argument("--balance", type=float, default=INITIAL_BALANCE)
    p.add_argument("--fee", type=float, default=FEE_PCT,
                   help="Per-side taker fee, e.g. 0.001 = 0.1%%")
    p.add_argument("--atr-sizing", action="store_true",
                   help="Enable ATR-based position sizing + SL/TP")
    p.add_argument("--atr-period", type=int, default=ATR_PERIOD)
    p.add_argument("--atr-risk", type=float, default=ATR_RISK_PCT,
                   help="Fraction of balance risked per trade (0.01 = 1%%)")
    p.add_argument("--atr-stop-mult", type=float, default=ATR_STOP_MULT)
    p.add_argument("--atr-tp-mult", type=float, default=ATR_TP_MULT)
    # --- Generic filter toggles --------------------------------------------
    p.add_argument("--htf-confirm", action="store_true",
                   default=USE_HTF_CONFIRM,
                   help="Gate signals on higher-timeframe EMA trend")
    p.add_argument("--htf", default=HTF_TIMEFRAME,
                   help="Higher timeframe for HTF confirm (e.g. 1d)")
    p.add_argument("--htf-ema", type=int, default=HTF_EMA_PERIOD,
                   help="EMA period on the higher timeframe")
    p.add_argument("--adx-filter", action="store_true",
                   default=USE_ADX_FILTER,
                   help="Require ADX to be in [adx_min, adx_max] range")
    p.add_argument("--adx-min", type=float, default=ADX_MIN,
                   help="ADX filter: require ADX > this (0 disables)")
    p.add_argument("--adx-max", type=float, default=ADX_MAX,
                   help="ADX filter: require ADX < this (0 disables)")
    p.add_argument("--vol-filter", action="store_true",
                   default=USE_VOLUME_FILTER,
                   help="Require signal-bar volume >= vol_mult × rolling median")
    p.add_argument("--vol-mult", type=float, default=VOL_MULT)
    p.add_argument("--atr-filter", action="store_true",
                   default=USE_ATR_FILTER,
                   help="Require ATR / close >= atr_min_pct")
    p.add_argument("--atr-min-pct", type=float, default=ATR_MIN_PCT)
    p.add_argument("--macd-confirm", action="store_true",
                   default=USE_MACD_CONFIRM,
                   help="Require MACD histogram agrees with signal direction")
    p.add_argument("--profile", default=None,
                   help="Name of a saved profile to apply (overrides all "
                        "other CLI flags). See profiles/ and profiles.py.")
    a = p.parse_args()
    params = Params(
        symbol=a.symbol,
        timeframe=a.timeframe,
        bars=a.bars,
        strategy=a.strategy,
        ema_short=a.ema_short,
        ema_long=a.ema_long,
        ema_trend=a.trend,
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
        initial_balance=a.balance,
        allocation_pct=a.allocation,
        stop_loss_pct=a.stop,
        take_profit_pct=a.take,
        entry_cooldown_bars=a.cooldown,
        fee_pct=a.fee,
        use_atr_sizing=a.atr_sizing,
        atr_period=a.atr_period,
        atr_risk_pct=a.atr_risk,
        atr_stop_mult=a.atr_stop_mult,
        atr_tp_mult=a.atr_tp_mult,
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
    if a.profile:
        # Lazy import so --help doesn't pay the profiles.py parse cost,
        # and we avoid any circular-import surprises during normal use
        # (profiles.py imports Params from this module).
        from profiles import apply_profile
        params = apply_profile(params, a.profile)
    return params


# ------------------------------------------------------------------- fetch ---
def fetch_data(params: Params, use_cache: bool = True) -> pd.DataFrame:
    return fetch_history(
        params.symbol, params.timeframe, params.bars, use_cache=use_cache
    )


def _apply_atr(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Compute ATR using Wilder's smoothing of the True Range."""
    df = df.copy()
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    return df


def apply_full_indicators(df: pd.DataFrame, params: Params) -> pd.DataFrame:
    df = get_strategy(params.strategy).apply_indicators(df, params)
    # ATR is strategy-agnostic: always compute it when ATR sizing is on so
    # the replay / live loop can pick it off each bar.
    if params.use_atr_sizing:
        df = _apply_atr(df, params.atr_period)

    # Generic filter indicators — only computed when the matching toggle is on
    # so there's zero cost for strategies that don't use them. See
    # strategies.filters_pass for the gate logic.
    df = attach_filter_indicators(df, params)

    if params.use_htf_confirm:
        # HTF bars: fetch enough to give the HTF EMA time to warm up, which
        # means covering the same calendar span as the LTF request plus a
        # cushion. `fetch_history` is cached on disk so repeated calls are
        # cheap.
        htf_bars = max(params.htf_ema_period * 5, _htf_bars_for(params))
        htf_df = fetch_history(
            params.symbol, params.htf_timeframe, htf_bars, use_cache=True
        )
        df = attach_htf_trend(df, htf_df, params.htf_ema_period)
    return df


def _htf_bars_for(params: Params) -> int:
    """Rough estimate of how many HTF bars cover the LTF sample window."""
    from history import TF_MS
    ltf_ms = TF_MS.get(params.timeframe, 60 * 60_000)
    htf_ms = TF_MS.get(params.htf_timeframe, 24 * 60 * 60_000)
    if htf_ms <= 0:
        return params.bars
    return max(50, (params.bars * ltf_ms) // htf_ms + 10)


# ------------------------------------------------------------------ summary --
def _max_drawdown_pct(equity_history: list[dict]) -> float:
    """Peak-to-trough % drawdown measured on the MTM equity curve."""
    peak = float("-inf")
    max_dd = 0.0
    for point in equity_history:
        bal = float(point.get("balance", 0.0))
        if bal > peak:
            peak = bal
        if peak > 0:
            dd = (peak - bal) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _profit_factor(trades: list[dict]) -> float:
    """Sum(wins) / |sum(losses)|. Returns +inf if no losses, 0 if no wins."""
    gross_win = sum(t["profit"] for t in trades if t["profit"] > 0)
    gross_loss = -sum(t["profit"] for t in trades if t["profit"] < 0)
    if gross_loss <= 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _trade_sharpe(trades: list[dict], initial: float) -> float:
    """Per-trade Sharpe: mean(trade_return_pct) / stdev(trade_return_pct).

    Not annualised — think of it as a "consistency of trades" score where
    >1 means the mean is bigger than the noise. Use alongside profit factor.
    """
    if len(trades) < 2 or initial <= 0:
        return 0.0
    returns = [t["profit"] / initial for t in trades]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if var <= 0:
        return 0.0
    return mean / (var ** 0.5)


def _summary(trader: PaperTrader, params: Params, start: int, end: int) -> dict:
    trades = trader.trade_log
    if not trades:
        return {
            "trades": 0,
            "balance": trader.balance,
            "return_pct": 0.0,
            "profit_factor": 0.0,
            "trade_sharpe": 0.0,
            "max_drawdown_pct": _max_drawdown_pct(trader.equity_history),
            "timeframe": params.timeframe,
            "bars": end - start,
        }
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    total = sum(t["profit"] for t in trades)
    gross = sum(t.get("gross_profit", t["profit"]) for t in trades)
    fees = sum(t.get("fee", 0.0) for t in trades)
    pf = _profit_factor(trades)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades)) * 100,
        "gross_pnl": gross,
        "fees_paid": fees,
        "total_pnl": total,
        "balance": trader.balance,
        "return_pct": (total / trader.initial_balance) * 100,
        # JSON can't serialize inf; clamp to a large sentinel.
        "profit_factor": 999.0 if pf == float("inf") else round(pf, 3),
        "trade_sharpe": round(_trade_sharpe(trades, trader.initial_balance), 3),
        "max_drawdown_pct": round(_max_drawdown_pct(trader.equity_history), 3),
        "avg_trade_pnl": round(total / len(trades), 4),
        "reasons": {
            r: sum(1 for t in trades if t["reason"] == r)
            for r in {t["reason"] for t in trades}
        },
        "skipped_by_cooldown": trader.skipped_by_cooldown,
        "timeframe": params.timeframe,
        "bars": end - start,
    }


# -------------------------------------------------------------- ATR sizing ---
def _atr_overrides(
    signal: str, price: float, last_bar, trader: PaperTrader, params: Params
) -> dict:
    """Translate a signal + current ATR into size / SL / TP overrides.

    Returns an empty dict when ATR sizing is disabled or ATR is missing,
    so the caller can `**overrides` into PaperTrader.on_signal safely and
    fall back to pct-based sizing.
    """
    if not params.use_atr_sizing or signal not in ("BUY", "SELL"):
        return {}
    atr = last_bar.get("atr")
    if atr is None or pd.isna(atr) or atr <= 0 or price <= 0:
        return {}

    stop_dist = params.atr_stop_mult * float(atr)
    take_dist = params.atr_tp_mult * float(atr)
    if stop_dist <= 0:
        return {}

    risk_amount = trader.balance * params.atr_risk_pct
    size = risk_amount / stop_dist
    if size <= 0:
        return {}

    if signal == "BUY":
        stop_override = price - stop_dist
        take_override = price + take_dist
    else:  # SELL
        stop_override = price + stop_dist
        take_override = price - take_dist

    return {
        "size_override": size,
        "stop_override": stop_override,
        "take_override": take_override,
    }


# ------------------------------------------------------------------ replay ---
def replay_on_df(
    df: pd.DataFrame,
    params: Params,
    start: Optional[int] = None,
    end: Optional[int] = None,
    data_file: Optional[str] = None,
    verbose: bool = False,
) -> dict:
    """Replay a preloaded DataFrame (with indicators already applied).

    Only bars in [start, end) are iterated. Indicators are calculated on the
    full df, so EMAs at bar `start` already incorporate the pre-history
    (important for a train/test split where test starts mid-series).
    """
    strategy = get_strategy(params.strategy)

    # Apply indicators if the caller handed us a raw DataFrame. We detect by
    # presence of "rsi" because every strategy computes it; strategies that
    # don't will be easy to adapt later.
    if "rsi" not in df.columns:
        df = apply_full_indicators(df, params)
    elif params.use_atr_sizing and "atr" not in df.columns:
        df = _apply_atr(df, params.atr_period)

    start = start if start is not None else 0
    end = end if end is not None else len(df)
    warmup_min = strategy.warmup_bars(params)
    if params.use_atr_sizing:
        warmup_min = max(warmup_min, params.atr_period + 2)
    start = max(start, warmup_min)
    if start >= end:
        raise ValueError(
            f"Not enough bars for warm-up: start={start}, end={end}, warmup>={warmup_min}"
        )

    trader = PaperTrader(
        initial_balance=params.initial_balance,
        allocation_pct=params.allocation_pct,
        stop_loss_pct=params.stop_loss_pct,
        take_profit_pct=params.take_profit_pct,
        entry_cooldown_bars=params.entry_cooldown_bars,
        fee_pct=params.fee_pct,
        data_file=data_file or OUTPUT_FILE,
    )

    with trader.batch():
        for i in range(start, end):
            window = df.iloc[: i + 1]
            last_bar = window.iloc[-1]
            price = float(last_bar["close"])
            ts = last_bar["timestamp"]
            signal = strategy.generate_signal(window, params)
            overrides = _atr_overrides(signal, price, last_bar, trader, params)
            trader.on_signal(signal, price, timestamp=ts, **overrides)
            trader.on_tick(price, timestamp=ts)

        if trader.position is not None:
            last_price = float(df.iloc[end - 1]["close"])
            last_ts = df.iloc[end - 1]["timestamp"]
            trader.close(last_price, reason="backtest_end", timestamp=last_ts)

    s = _summary(trader, params, start, end)

    if verbose:
        print("\n=== Backtest summary ===")
        for k, v in s.items():
            if isinstance(v, float):
                print(f"  {k:<20} {v:>10.2f}")
            else:
                print(f"  {k:<20} {v}")
        print(f"\nWrote {data_file or OUTPUT_FILE}")

    return s


def run(params: Optional[Params] = None, verbose: bool = True) -> dict:
    p = params or Params()
    if verbose:
        print(f"Fetching {p.bars} bars of {p.symbol} {p.timeframe}...")
    df = fetch_data(p)
    df = apply_full_indicators(df, p)
    return replay_on_df(df, p, verbose=verbose)


if __name__ == "__main__":
    run(_parse_args())
