"""
Regime classification + expectancy helpers.

Phase 3 baseline:
- 3-axis classifier: trend x volatility x microstructure
- per-bar `regime` label for downstream analytics
- strategy x regime expectancy rollups
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from dataclasses import replace


def _wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
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
    p = max(1, int(period))
    return tr.ewm(alpha=1 / p, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    alpha = 1 / max(1, int(period))
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    nan = float("nan")
    safe_atr = atr_w.replace(0, nan)
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / safe_atr
    di_sum = (plus_di + minus_di).replace(0, nan)
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0.0)
    return dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)


def attach_regime_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Attach trend/vol/micro labels and combined regime string to each bar."""
    out = df.copy()
    close = out["close"].astype(float)
    ema_fast = close.ewm(span=50, adjust=False).mean()
    ema_slow = close.ewm(span=200, adjust=False).mean()
    rel = (ema_fast - ema_slow) / close.replace(0, pd.NA)
    out["regime_trend"] = "flat"
    out.loc[rel > 0.0015, "regime_trend"] = "up"
    out.loc[rel < -0.0015, "regime_trend"] = "down"

    atr14 = _wilder_atr(out, 14)
    atr_pct = (atr14 / close.replace(0, pd.NA)).fillna(0.0)
    q1 = float(atr_pct.quantile(0.33))
    q2 = float(atr_pct.quantile(0.66))
    out["regime_vol"] = "mid"
    out.loc[atr_pct <= q1, "regime_vol"] = "low"
    out.loc[atr_pct >= q2, "regime_vol"] = "high"

    adx14 = _adx(out, 14)
    out["regime_micro"] = "balanced"
    out.loc[adx14 >= 28.0, "regime_micro"] = "directional"
    out.loc[adx14 <= 16.0, "regime_micro"] = "choppy"

    out["regime"] = (
        out["regime_trend"].astype(str)
        + "|"
        + out["regime_vol"].astype(str)
        + "|"
        + out["regime_micro"].astype(str)
    )
    return out


def _trade_regime_rows(trades: list[dict], regime_by_ts: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in trades:
        ts = pd.to_datetime(t.get("timestamp"), utc=True, errors="coerce")
        regime = "unknown"
        if ts is not pd.NaT and ts in regime_by_ts.index:
            regime = str(regime_by_ts.loc[ts])
        rows.append(
            {
                "regime": regime,
                "profit": float(t.get("profit", 0.0)),
                "side": str(t.get("side", "")),
            }
        )
    return rows


def strategy_regime_expectancy(
    *,
    base_params,
    strategy_names: list[str],
    df_raw: pd.DataFrame,
    apply_full_indicators_fn,
    replay_on_df_fn,
    include_unknown: bool = False,
) -> dict[str, Any]:
    """Compute strategy x regime expectancy matrix from replayed trades."""
    all_rows: list[dict[str, Any]] = []
    regimes_seen: set[str] = set()
    for strategy in strategy_names:
        p = replace(base_params, strategy=strategy)
        df_ind = apply_full_indicators_fn(df_raw.copy(), p)
        if "regime" not in df_ind.columns:
            df_ind = attach_regime_columns(df_ind)
        regime_by_ts = pd.Series(
            df_ind["regime"].values,
            index=pd.to_datetime(df_ind["timestamp"], utc=True, errors="coerce"),
        )
        summary = replay_on_df_fn(
            df_ind,
            p,
            data_file=os.devnull,
            verbose=False,
            include_trades=True,
        )
        trades = summary.get("trades_detail") or []
        trade_rows = _trade_regime_rows(trades, regime_by_ts)
        if not include_unknown:
            trade_rows = [r for r in trade_rows if r["regime"] != "unknown"]
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in trade_rows:
            buckets.setdefault(r["regime"], []).append(r)
        for regime, vals in buckets.items():
            regimes_seen.add(regime)
            n = len(vals)
            wins = sum(1 for x in vals if x["profit"] > 0)
            total = sum(x["profit"] for x in vals)
            avg = total / n if n else 0.0
            all_rows.append(
                {
                    "strategy": strategy,
                    "regime": regime,
                    "trades": n,
                    "win_rate": (wins / n * 100.0) if n else 0.0,
                    "avg_pnl": avg,
                    "expectancy_pct": (avg / float(base_params.initial_balance) * 100.0)
                    if float(base_params.initial_balance) > 0
                    else 0.0,
                    "total_pnl": total,
                    "return_pct": (total / float(base_params.initial_balance) * 100.0)
                    if float(base_params.initial_balance) > 0
                    else 0.0,
                }
            )
    all_rows.sort(
        key=lambda x: (str(x["strategy"]), -int(x["trades"]), str(x["regime"]))
    )
    return {
        "strategies": sorted(set(strategy_names)),
        "regimes": sorted(regimes_seen),
        "rows": all_rows,
    }
