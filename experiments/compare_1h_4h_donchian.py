"""One-off comparison: user Donchian config on 1h vs 4h + fee sanity check."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest import (  # noqa: E402
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)


def backtest(params: Params, *, include_trades: bool = False) -> dict:
    df = fetch_data(params)
    df = apply_full_indicators(df, params)
    return replay_on_df(
        df,
        params,
        data_file=str(ROOT / "backtest.json"),
        verbose=False,
        include_trades=include_trades,
    )


def user_like(**overrides) -> Params:
    """Match dashboard: Donchian 20, compression, HTF+vol, no ADX, ATR sizing."""
    base = Params(
        strategy="donchian_breakout",
        symbol="BTC/USDT",
        bars=100_000,
        donchian_period=20,
        use_donchian_compression=True,
        donchian_compression_lookback=20,
        donchian_compression_max_range_atr=1.0,
        use_donchian_rsi=False,
        use_atr_sizing=True,
        atr_period=10,
        atr_risk_pct=0.01,
        atr_stop_mult=1.8,
        atr_tp_mult=3.0,
        use_htf_confirm=True,
        htf_timeframe="1d",
        htf_ema_period=50,
        use_adx_filter=False,
        use_volume_filter=True,
        vol_mult=1.3,
        vol_ma_period=20,
        entry_cooldown_bars=3,
        fee_pct=0.001,
        use_trailing_stop=True,
        trailing_stop_pct=0.015,
        initial_balance=1000.0,
    )
    return replace(base, **overrides)


def tightened(**overrides) -> Params:
    """Prior chat bundle: fewer trades, ADX + longer channel."""
    return user_like(
        donchian_period=40,
        donchian_compression_max_range_atr=0.75,
        vol_mult=1.5,
        entry_cooldown_bars=8,
        use_donchian_rsi=True,
        use_adx_filter=True,
        adx_min=20.0,
        adx_max=0.0,
        use_trailing_stop=False,
        **overrides,
    )


def repo_btc_4h(**overrides) -> Params:
    """filter_ablation B3-don40-btc4h style."""
    return Params(
        strategy="donchian_breakout",
        symbol="BTC/USDT",
        timeframe="4h",
        bars=100_000,
        donchian_period=40,
        ema_trend=0,
        use_atr_sizing=True,
        atr_stop_mult=2.0,
        atr_tp_mult=3.0,
        use_adx_filter=True,
        adx_min=20.0,
        fee_pct=0.001,
        initial_balance=1000.0,
        **overrides,
    )


SCENARIOS = [
    ("1h_user_ui", user_like(timeframe="1h")),
    ("1h_tightened", tightened(timeframe="1h")),
    ("4h_user_filters", user_like(timeframe="4h")),
    ("4h_tightened", tightened(timeframe="4h")),
    ("4h_repo_don40_adx", repo_btc_4h()),
    ("4h_repo_htf_vol", repo_btc_4h(
        use_htf_confirm=True,
        use_volume_filter=True,
        vol_mult=1.3,
    )),
]


def fee_sanity(trades: list, fee_pct: float) -> dict:
    """Recompute fees from notionals; compare to logged fee field."""
    recomputed = 0.0
    logged = 0.0
    notionals = []
    for t in trades:
        ep = float(t.get("entry") or t["entry_price"])
        xp = float(t.get("exit") or t["exit_price"])
        sz = float(t["size"])
        logged += float(t.get("fee", 0.0))
        f = (ep * sz + xp * sz) * fee_pct
        recomputed += f
        notionals.append(ep * sz)
    n = len(trades)
    avg_notional = sum(notionals) / n if n else 0.0
    round_trip_pct = 2 * fee_pct * 100
    return {
        "trades": n,
        "fees_logged": round(logged, 2),
        "fees_recomputed": round(recomputed, 2),
        "avg_notional_usd": round(avg_notional, 2),
        "fee_per_trade_avg": round(logged / n, 4) if n else 0.0,
        "round_trip_fee_pct": round_trip_pct,
        "implied_fee_drag_on_notional_pct": round(
            (logged / sum(notionals) * 100) if notionals else 0.0, 4
        ),
    }


def main() -> None:
    rows = []
    for label, params in SCENARIOS:
        print(f"Running {label} ({params.timeframe})...", flush=True)
        summary = backtest(params, include_trades=(label == "1h_user_ui"))
        row = {
            "label": label,
            "timeframe": params.timeframe,
            "trades": summary.get("trades", 0),
            "win_rate": round(summary.get("win_rate", 0), 2),
            "return_pct": round(summary.get("return_pct", 0), 2),
            "gross_pnl": round(summary.get("gross_pnl", 0), 2),
            "fees_paid": round(summary.get("fees_paid", 0), 2),
            "total_pnl": round(summary.get("total_pnl", 0), 2),
            "balance": round(summary.get("balance", 0), 2),
            "max_dd_pct": round(summary.get("max_drawdown_pct", 0), 2),
            "bars": summary.get("bars"),
            "skipped_cooldown": summary.get("skipped_by_cooldown", 0),
        }
        rows.append(row)
        print(json.dumps(row, indent=2), flush=True)

    out_path = ROOT / "experiments" / "compare_1h_4h_results.json"
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)

    # Fee sanity on full 1h user run (needs include_trades in run())
    ui = next(p for lab, p in SCENARIOS if lab == "1h_user_ui")
    full = backtest(ui, include_trades=True)
    trades = full.get("trades_detail") or []
    sanity = fee_sanity(trades, ui.fee_pct)
    sanity["gross_pnl"] = full.get("gross_pnl")
    sanity["net_pnl"] = full.get("total_pnl")
    print("\nFee sanity (1h_user_ui):", json.dumps(sanity, indent=2), flush=True)

    # Alternate fee assumptions
    for fee_label, fee in [("spot_0.1pct", 0.001), ("bnb_0.075pct", 0.00075), ("futures_taker_0.04pct", 0.0004)]:
        p = replace(ui, fee_pct=fee)
        s = backtest(p)
        print(
            f"1h_user_ui @ {fee_label}: net={s.get('total_pnl'):.2f} "
            f"fees={s.get('fees_paid'):.2f} trades={s.get('trades')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
