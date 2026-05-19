"""
Multi-strategy portfolio backtest on a *single* market slice.

Capital-partitioned sleeves (not simultaneous position netting): each sleeve
runs a full independent `replay_on_df` on the same OHLCV with allocated
capital `weight * base.initial_balance`. Combined balance is the sum of final
sleeve balances; drawdown aggregation is deliberately conservative (`max`
per-sleeve `max_drawdown_pct`).

Run:
    python portfolio.py --bars 1500 \\
        --sleeve ema_crossover:0.5 --sleeve donchian_breakout:0.5

Use `--profile NAME` for risk/strategy scaffolding from `profiles/`.
"""
from __future__ import annotations

import argparse
import os
import json
from contextlib import ExitStack
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Any, Mapping, Optional

import pandas as pd

from backtest import (
    Params,
    _atr_overrides,
    _bar_atr,
    _max_drawdown_pct,
    _summary,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)
from paper_trader import PaperTrader
from strategies import get_strategy, list_strategies

_ALLOWED = frozenset(list_strategies())


@dataclass
class PortfolioRiskConfig:
    max_open_positions: int = 4
    max_correlated_positions: int = 2
    vol_target_atr_pct: float = 0.015
    vol_scale_min: float = 0.25
    vol_scale_max: float = 2.0
    circuit_ema_fast: int = 20
    circuit_ema_slow: int = 60
    circuit_sigma: float = 2.0
    max_positions_per_group: int = 2
    risk_budget_overrides: dict[str, float] = field(default_factory=dict)
    correlation_groups: dict[str, str] = field(default_factory=dict)


def _normalized_budget_overrides(
    strategy_order: list[str],
    base_weights: Mapping[str, float],
    risk_budget_overrides: Mapping[str, float],
) -> dict[str, float]:
    """Normalized per-strategy risk budgets; fallback is base weights."""
    if not risk_budget_overrides:
        return {s: float(base_weights[s]) for s in strategy_order}
    raw: dict[str, float] = {}
    for s in strategy_order:
        v = float(risk_budget_overrides.get(s, 0.0))
        raw[s] = max(0.0, v)
    total = float(sum(raw.values()))
    if total <= 0:
        return {s: float(base_weights[s]) for s in strategy_order}
    return {s: float(v) / total for s, v in raw.items()}


def _vol_scale_from_atr(
    atr: Optional[float],
    price: float,
    *,
    target_atr_pct: float,
    scale_min: float,
    scale_max: float,
) -> float:
    """Scale exposure so realized bar ATR% gravitates to target ATR%."""
    if target_atr_pct <= 0 or price <= 0 or atr is None or atr <= 0:
        return 1.0
    atr_pct = float(atr) / float(price)
    if atr_pct <= 0:
        return 1.0
    raw = float(target_atr_pct) / atr_pct
    return max(float(scale_min), min(float(scale_max), raw))


def _entry_allowed(
    signal: str,
    open_sides: list[str],
    *,
    max_open_positions: int,
    max_correlated_positions: int,
    group_name: str,
    open_groups: list[str],
    max_positions_per_group: int,
    circuit_halted: bool,
) -> bool:
    if signal not in ("BUY", "SELL"):
        return True
    if circuit_halted:
        return False
    if max_open_positions >= 0 and len(open_sides) >= max_open_positions:
        return False
    side = "LONG" if signal == "BUY" else "SHORT"
    if (
        max_correlated_positions >= 0
        and sum(1 for s in open_sides if s == side) >= max_correlated_positions
    ):
        return False
    if (
        max_positions_per_group >= 0
        and group_name
        and sum(1 for g in open_groups if g == group_name) >= max_positions_per_group
    ):
        return False
    return True


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Return strictly non-negative weights scaled to sum 1."""
    if not weights:
        raise ValueError("weights must contain at least one strategy")
    bad = sorted(k for k, v in weights.items() if v < 0)
    if bad:
        raise ValueError(f"negative weights unsupported: {bad}")
    s = float(sum(weights.values()))
    if s <= 0:
        raise ValueError("weights must sum to a positive number")
    return {k: float(v) / s for k, v in weights.items()}


def _assert_known_strategies(weights: Mapping[str, float]) -> None:
    unk = sorted(set(weights) - _ALLOWED)
    if unk:
        raise ValueError(
            f"unknown strategies {unk}. Allowed: {sorted(_ALLOWED)}"
        )


def run_allocated_strategy_mix(
    base: Params,
    weights: Mapping[str, float],
    *,
    df: Optional[pd.DataFrame] = None,
    use_cache: bool = True,
    verbose: bool = False,
) -> dict[str, Any]:
    """Replay each strategy on scaled capital and aggregate sleeve balances."""
    nw = normalize_weights(weights)
    _assert_known_strategies(nw)

    df_src = fetch_data(base, use_cache=use_cache) if df is None else df
    master_initial = float(base.initial_balance)

    sleeves: list[dict[str, Any]] = []
    for strat, w in sorted(nw.items()):
        cap = master_initial * w
        sleeve_params = replace(base, strategy=strat, initial_balance=cap)
        summary = replay_on_df(
            df_src.copy(),
            sleeve_params,
            verbose=verbose,
        )
        sleeves.append(
            {
                "strategy": strat,
                "weight": w,
                "allocation": cap,
                "summary": summary,
            }
        )

    combined_balance = float(sum(s["summary"]["balance"] for s in sleeves))
    combined_pnl = combined_balance - master_initial
    combined_return_pct = (
        (combined_pnl / master_initial) * 100.0 if master_initial > 0 else 0.0
    )
    sleeve_dds = [float(s["summary"]["max_drawdown_pct"]) for s in sleeves]
    total_trades = int(sum(int(s["summary"]["trades"]) for s in sleeves))

    return {
        "method": "isolated_capital_slices_same_ohlcv",
        "caveat": (
            "Cross-strategy risk overlap is ignored; DD proxy=max sleeve DD."
        ),
        "symbol": base.symbol,
        "timeframe": base.timeframe,
        "bars": len(df_src),
        "master_initial_balance": master_initial,
        "weights": nw,
        "combined": {
            "balance": combined_balance,
            "total_pnl": combined_pnl,
            "return_pct": combined_return_pct,
            "total_trades": total_trades,
            "max_drawdown_pct_conservative_proxy": (
                max(sleeve_dds) if sleeve_dds else 0.0
            ),
        },
        "sleeves": sleeves,
    }


def run_multi_strategy_portfolio(
    base: Params,
    weights: Mapping[str, float],
    *,
    risk: Optional[PortfolioRiskConfig] = None,
    df: Optional[pd.DataFrame] = None,
    use_cache: bool = True,
    verbose: bool = False,
) -> dict[str, Any]:
    """Single-pass multi-strategy replay with position/risk gating."""
    nw = normalize_weights(weights)
    _assert_known_strategies(nw)
    cfg = risk or PortfolioRiskConfig()
    df_src = fetch_data(base, use_cache=use_cache) if df is None else df
    df_src = df_src.copy()
    master_initial = float(base.initial_balance)

    strategy_order = sorted(nw.keys())
    budget_weights = _normalized_budget_overrides(
        strategy_order, nw, cfg.risk_budget_overrides
    )
    risk_scales = {
        s: (float(budget_weights[s]) / float(nw[s])) if float(nw[s]) > 0 else 1.0
        for s in strategy_order
    }
    group_by_strategy = {
        s: str(cfg.correlation_groups.get(s, s)) for s in strategy_order
    }
    strat_params = {s: replace(base, strategy=s) for s in strategy_order}
    strat_objs = {s: get_strategy(s) for s in strategy_order}
    strat_dfs = {
        s: apply_full_indicators(df_src.copy(), strat_params[s]) for s in strategy_order
    }

    warmup = max(
        1,
        max(strat_objs[s].warmup_bars(strat_params[s]) for s in strategy_order),
    )
    first_i = max(1, warmup)
    if first_i >= len(df_src):
        raise ValueError(
            f"Not enough bars for warm-up: first_i={first_i}, total={len(df_src)}"
        )

    traders: dict[str, PaperTrader] = {}
    for s in strategy_order:
        p = strat_params[s]
        traders[s] = PaperTrader(
            initial_balance=master_initial * nw[s],
            allocation_pct=p.allocation_pct,
            stop_loss_pct=p.stop_loss_pct,
            take_profit_pct=p.take_profit_pct,
            entry_cooldown_bars=p.entry_cooldown_bars,
            fee_pct=p.fee_pct,
            data_file=os.devnull,
            slippage_pct=p.slippage_pct,
            slippage_atr_mult=p.slippage_atr_mult,
            half_spread_bps=p.half_spread_bps,
            intrabar_sl_tp_policy=p.intrabar_sl_tp_policy,
            intrabar_random_seed=p.intrabar_random_seed,
            use_trailing_stop=p.use_trailing_stop,
            trailing_stop_pct=p.trailing_stop_pct,
            max_consecutive_losses=p.max_consecutive_losses,
            max_daily_loss_pct=p.max_daily_loss_pct,
            enable_funding=p.enable_funding,
            funding_rate_bps=p.funding_rate_bps,
            funding_interval_hours=p.funding_interval_hours,
            verbose=verbose,
        )

    skipped_by_risk_limit = 0
    skipped_by_corr_limit = 0
    skipped_by_group_limit = 0
    skipped_by_circuit = 0
    circuit_halted_bars = 0
    circuit_halted = False
    combined_equity_history = [
        {
            "timestamp": str(df_src.iloc[0]["timestamp"]),
            "balance": master_initial,
            "realized": True,
        }
    ]

    with ExitStack() as stack:
        for t in traders.values():
            stack.enter_context(t.batch())

        for i in range(first_i, len(df_src)):
            open_sides = [t.position for t in traders.values() if t.position is not None]
            open_groups = [
                group_by_strategy[s]
                for s in strategy_order
                if traders[s].position is not None
            ]
            for s in strategy_order:
                t = traders[s]
                p = strat_params[s]
                strat_df = strat_dfs[s]
                strat = strat_objs[s]
                window = strat_df.iloc[:i]
                if len(window) < 2:
                    continue
                last_bar = window.iloc[-1]
                entry = strat_df.iloc[i]
                entry_open = float(entry["open"])
                ts = entry["timestamp"]
                hi = float(entry["high"])
                lo = float(entry["low"])
                cl = float(entry["close"])

                signal = strat.generate_signal(window, p)
                atr_sig = _bar_atr(last_bar)
                atr_bar = _bar_atr(entry)
                overrides = _atr_overrides(signal, entry_open, last_bar, t, p)
                vscale = _vol_scale_from_atr(
                    atr_sig,
                    entry_open,
                    target_atr_pct=cfg.vol_target_atr_pct,
                    scale_min=cfg.vol_scale_min,
                    scale_max=cfg.vol_scale_max,
                )
                if "size_override" in overrides:
                    overrides["size_override"] = (
                        float(overrides["size_override"])
                        * float(vscale)
                        * float(risk_scales.get(s, 1.0))
                    )
                elif signal in ("BUY", "SELL") and entry_open > 0:
                    notional = (
                        t.balance
                        * t.allocation_pct
                        * float(vscale)
                        * float(risk_scales.get(s, 1.0))
                    )
                    if notional > 0:
                        overrides["size_override"] = notional / entry_open

                allow = True
                if t.position is None and signal in ("BUY", "SELL"):
                    side = "LONG" if signal == "BUY" else "SHORT"
                    group_name = group_by_strategy[s]
                    allow = _entry_allowed(
                        signal,
                        open_sides,
                        max_open_positions=cfg.max_open_positions,
                        max_correlated_positions=cfg.max_correlated_positions,
                        group_name=group_name,
                        open_groups=open_groups,
                        max_positions_per_group=cfg.max_positions_per_group,
                        circuit_halted=circuit_halted,
                    )
                    if not allow:
                        if circuit_halted:
                            skipped_by_circuit += 1
                        elif (
                            cfg.max_open_positions >= 0
                            and len(open_sides) >= cfg.max_open_positions
                        ):
                            skipped_by_risk_limit += 1
                        elif (
                            cfg.max_correlated_positions >= 0
                            and sum(1 for x in open_sides if x == side)
                            >= cfg.max_correlated_positions
                        ):
                            skipped_by_corr_limit += 1
                        elif (
                            cfg.max_positions_per_group >= 0
                            and group_name
                            and sum(1 for g in open_groups if g == group_name)
                            >= cfg.max_positions_per_group
                        ):
                            skipped_by_group_limit += 1

                if allow:
                    t.on_signal(signal, entry_open, timestamp=ts, atr=atr_sig, **overrides)
                    open_sides = [
                        x.position for x in traders.values() if x.position is not None
                    ]
                    open_groups = [
                        group_by_strategy[k]
                        for k in strategy_order
                        if traders[k].position is not None
                    ]

                t.on_tick(cl, timestamp=ts, high=hi, low=lo, atr=atr_bar)

            cl_master = float(df_src.iloc[i]["close"])
            ts_master = df_src.iloc[i]["timestamp"]
            combined_bal = sum(x.mark_to_market(cl_master) for x in traders.values())
            combined_equity_history.append(
                {
                    "timestamp": str(ts_master),
                    "balance": float(combined_bal),
                    "realized": False,
                }
            )
            s_eq = pd.Series([float(x["balance"]) for x in combined_equity_history])
            if len(s_eq) >= max(cfg.circuit_ema_slow, 5):
                ema_fast = float(
                    s_eq.ewm(span=max(2, cfg.circuit_ema_fast), adjust=False).mean().iloc[-1]
                )
                ema_slow = float(
                    s_eq.ewm(span=max(3, cfg.circuit_ema_slow), adjust=False).mean().iloc[-1]
                )
                std_slow = float(s_eq.tail(cfg.circuit_ema_slow).std(ddof=0))
                circuit_halted = ema_fast < (ema_slow - cfg.circuit_sigma * std_slow)
                if circuit_halted:
                    circuit_halted_bars += 1

        last_row = df_src.iloc[-1]
        last_price = float(last_row["close"])
        last_ts = last_row["timestamp"]
        atr_end = _bar_atr(last_row)
        for t in traders.values():
            if t.position is not None:
                t.close(
                    last_price,
                    reason="portfolio_end",
                    timestamp=last_ts,
                    atr=atr_end,
                    ref_price=last_price,
                )

    sleeves: list[dict[str, Any]] = []
    for s in strategy_order:
        p = strat_params[s]
        t = traders[s]
        summ = _summary(t, p, first_i, len(df_src), include_trades=False)
        sleeves.append(
            {
                "strategy": s,
                "weight": nw[s],
                "allocation": master_initial * nw[s],
                "summary": summ,
            }
        )

    combined_balance = float(sum(s["summary"]["balance"] for s in sleeves))
    combined_pnl = combined_balance - master_initial
    combined_return_pct = (
        (combined_pnl / master_initial) * 100.0 if master_initial > 0 else 0.0
    )
    total_trades = int(sum(int(s["summary"]["trades"]) for s in sleeves))
    sleeve_dds = [float(s["summary"]["max_drawdown_pct"]) for s in sleeves]
    combined_mdd = float(_max_drawdown_pct(combined_equity_history))
    flat_trades: list[dict[str, Any]] = []
    for s in strategy_order:
        for tr in traders[s].trade_log:
            row = dict(tr)
            row["strategy"] = s
            flat_trades.append(row)

    return {
        "method": "shared_market_multi_strategy_runner",
        "symbol": base.symbol,
        "timeframe": base.timeframe,
        "bars": len(df_src),
        "master_initial_balance": master_initial,
        "weights": nw,
        "risk_budget_weights": budget_weights,
        "risk_scales": risk_scales,
        "risk_config": {
            "max_open_positions": cfg.max_open_positions,
            "max_correlated_positions": cfg.max_correlated_positions,
            "vol_target_atr_pct": cfg.vol_target_atr_pct,
            "vol_scale_min": cfg.vol_scale_min,
            "vol_scale_max": cfg.vol_scale_max,
            "circuit_ema_fast": cfg.circuit_ema_fast,
            "circuit_ema_slow": cfg.circuit_ema_slow,
            "circuit_sigma": cfg.circuit_sigma,
            "max_positions_per_group": cfg.max_positions_per_group,
            "risk_budget_overrides": {
                k: float(v) for k, v in cfg.risk_budget_overrides.items()
            },
            "correlation_groups": dict(cfg.correlation_groups),
        },
        "combined": {
            "balance": combined_balance,
            "total_pnl": combined_pnl,
            "return_pct": combined_return_pct,
            "total_trades": total_trades,
            "max_drawdown_pct": combined_mdd,
            "max_drawdown_pct_conservative_proxy": max(sleeve_dds) if sleeve_dds else 0.0,
            "skipped_by_risk_limit": skipped_by_risk_limit,
            "skipped_by_corr_limit": skipped_by_corr_limit,
            "skipped_by_group_limit": skipped_by_group_limit,
            "skipped_by_circuit": skipped_by_circuit,
            "circuit_halted_bars": circuit_halted_bars,
        },
        "initial_balance": master_initial,
        "balance": combined_balance,
        "equity_history": combined_equity_history,
        "trades": flat_trades,
        "sleeves": sleeves,
    }


def _parse_sleeves(clauses: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for c in clauses:
        if ":" not in c:
            raise ValueError(
                f"Invalid --sleeve {c!r}; expected strategy_name:weight"
            )
        name, wstr = c.split(":", 1)
        name = name.strip()
        if name in out:
            raise ValueError(f"duplicate strategy in --sleeve: {name}")
        out[name] = float(wstr.strip())
    return out


def _portfolio_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    base = Params()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default=base.symbol)
    p.add_argument("--timeframe", default=base.timeframe)
    p.add_argument("--bars", type=int, default=base.bars)
    p.add_argument(
        "--balance",
        type=float,
        default=base.initial_balance,
        help="Total account capital split across sleeves by weight.",
    )
    p.add_argument(
        "--profile",
        default=None,
        help="Optional named preset merged into Params (risk + filters only).",
    )
    p.add_argument(
        "--sleeve",
        action="append",
        metavar="NAME:WEIGHT",
        default=[],
        help="strategy:positive-weight (repeatable; auto-normalised to sum 1)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass on-disk OHLC cache for the shared fetch.",
    )
    p.add_argument(
        "--engine",
        choices=["runner", "isolated"],
        default="runner",
        help="runner=single-pass constrained portfolio; isolated=legacy sleeves",
    )
    p.add_argument("--max-open-positions", type=int, default=4)
    p.add_argument("--max-correlated-positions", type=int, default=2)
    p.add_argument("--vol-target-atr-pct", type=float, default=0.015)
    p.add_argument("--vol-scale-min", type=float, default=0.25)
    p.add_argument("--vol-scale-max", type=float, default=2.0)
    p.add_argument("--circuit-ema-fast", type=int, default=20)
    p.add_argument("--circuit-ema-slow", type=int, default=60)
    p.add_argument("--circuit-sigma", type=float, default=2.0)
    p.add_argument("--max-positions-per-group", type=int, default=2)
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit full structured JSON instead of summary text.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    a = _portfolio_cli(argv)
    sleeves = _parse_sleeves(a.sleeve)
    if not sleeves:
        raise SystemExit("Provide one or more --sleeve NAME:WEIGHT clauses.")

    core = Params(
        symbol=a.symbol,
        timeframe=a.timeframe,
        bars=a.bars,
        initial_balance=a.balance,
    )
    if a.profile:
        from profiles import apply_profile

        base = apply_profile(Params(), a.profile)
        base = replace(
            base,
            symbol=core.symbol,
            timeframe=core.timeframe,
            bars=core.bars,
            initial_balance=core.initial_balance,
        )
    else:
        base = core

    if a.engine == "isolated":
        out = run_allocated_strategy_mix(
            base,
            sleeves,
            use_cache=not a.no_cache,
            verbose=a.verbose,
        )
    else:
        out = run_multi_strategy_portfolio(
            base,
            sleeves,
            risk=PortfolioRiskConfig(
                max_open_positions=max(-1, int(a.max_open_positions)),
                max_correlated_positions=max(-1, int(a.max_correlated_positions)),
                vol_target_atr_pct=max(0.0, float(a.vol_target_atr_pct)),
                vol_scale_min=max(0.01, float(a.vol_scale_min)),
                vol_scale_max=max(0.01, float(a.vol_scale_max)),
                circuit_ema_fast=max(2, int(a.circuit_ema_fast)),
                circuit_ema_slow=max(3, int(a.circuit_ema_slow)),
                circuit_sigma=max(0.0, float(a.circuit_sigma)),
                max_positions_per_group=max(-1, int(a.max_positions_per_group)),
                risk_budget_overrides={},
                correlation_groups={},
            ),
            use_cache=not a.no_cache,
            verbose=a.verbose,
        )

    if a.json:
        print(json.dumps(out, indent=2, default=str))
        return

    c = out["combined"]
    print(
        f"{out['symbol']} {out['timeframe']}  bars={out['bars']}  "
        f"{out['method']}"
    )
    print(f"  master capital ${out['master_initial_balance']:,.2f}")
    print(
        f"  combined ${c['balance']:,.2f}  "
        f"return {c['return_pct']:+.3f}%  "
        f"PnL {c['total_pnl']:+,.2f}  "
        f"trades={c['total_trades']}"
    )
    print(
        f"  DD proxy (max sleeve) {c['max_drawdown_pct_conservative_proxy']:.2f}%"
    )
    if "max_drawdown_pct" in c:
        print(f"  portfolio MDD {c['max_drawdown_pct']:.2f}%")
    if "circuit_halted_bars" in c:
        print(
            "  limits "
            f"risk={c.get('skipped_by_risk_limit', 0)} "
            f"corr={c.get('skipped_by_corr_limit', 0)} "
            f"circuit={c.get('skipped_by_circuit', 0)} "
            f"(halted bars={c.get('circuit_halted_bars', 0)})"
        )
    print("  sleeves:")
    for s in out["sleeves"]:
        ss = s["summary"]
        print(
            f"    - {s['strategy']:22} w={s['weight']:.4f} alloc=${s['allocation']:.2f} "
            f"-> bal=${ss['balance']:.2f} ({ss['return_pct']:+.2f}% trades={ss['trades']})"
        )


if __name__ == "__main__":
    main()
