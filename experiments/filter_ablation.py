"""
Filter-ablation experiment.

Hypothesis (from previous sweep + walk-forward run):
    The generic filters in `strategies.filters_pass` — HTF trend confirmation,
    ADX regime filter, volume filter — should add *robustness* (lower OOS
    stdev, higher positive-window rate) on top of our already-ROBUST
    baselines, without destroying trade count.

Method:
    1. Take the confirmed ROBUST (or near-ROBUST) baselines from the last
       explore_configs run as "controls".
    2. For each baseline, build a small list of variants that flip one
       filter on at a time (HTF50, HTF100, ADX, Volume, HTF+ADX combined).
    3. Walk-forward every (baseline × variant × market) on the same WF
       train/test windows used by the main experiment.
    4. Report the *delta* from control, per filter. A filter is useful if
       it improves WF mean / positive_rate / score without collapsing
       trade count.

Caveats we're explicitly guarding against:
    - Each new filter is a new overfit surface. We keep sub-knob values
      fixed at defaults from STRATEGY_FILTER_PRESETS rather than sweeping
      them — no point adding 10 new knobs for 6 baselines × 16 windows.
    - HTF fetching requires 1d cache for BTC and ETH; run
      `_prefetch_1d.py` (or let `fetch_history` do it) before running.
    - RSI on BTC-1h is tested because ADX_max (range filter) is the
      textbook fix for its high-variance OOS failure mode.

Run:
    python -m experiments.filter_ablation
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
from dataclasses import asdict, replace
from typing import Any

import pandas as pd  # noqa: F401 -- used indirectly via walk_forward

# Patch history module so we never touch the network for data we already
# have cached. Same approach as explore_configs.py.
import history as _history_mod
_real_fetch_history = _history_mod.fetch_history


def _cache_first_fetch_history(symbol, timeframe, bars, use_cache=True):
    if use_cache:
        cached = _history_mod._dedupe_sorted(
            _history_mod._load_cache(_history_mod._cache_path(symbol, timeframe))
        )
        if len(cached) >= bars:
            from utils import format_data
            return format_data(cached[-bars:])
    return _real_fetch_history(symbol, timeframe, bars, use_cache=use_cache)


_history_mod.fetch_history = _cache_first_fetch_history
import backtest as _backtest_mod  # noqa: E402
_backtest_mod.fetch_history = _cache_first_fetch_history

from backtest import Params  # noqa: E402
from walkforward import walk_forward  # noqa: E402


HERE = os.path.dirname(__file__)
REPORT_JSON = os.path.join(HERE, "filter_ablation.json")


@contextlib.contextmanager
def _silenced():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ----------------------------------------------------------- definitions ---

# Each market uses the same WF train/test sizes as the main experiment so
# the numbers are directly comparable.
MARKETS: dict[str, dict] = {
    "BTC-4h": {"symbol": "BTC/USDT", "timeframe": "4h", "bars": 10000,
               "wf_train": 2000, "wf_test": 500},
    "ETH-4h": {"symbol": "ETH/USDT", "timeframe": "4h", "bars": 10000,
               "wf_train": 2000, "wf_test": 500},
    "BTC-1h": {"symbol": "BTC/USDT", "timeframe": "1h", "bars": 20000,
               "wf_train": 4000, "wf_test": 1000},
}


# Baselines: the ROBUST / near-ROBUST configs we want to strengthen.
# Each entry: label, base params (without filter overrides), markets to test.
BASELINES: list[dict] = [
    {
        "id": "B1-ema-12-50-cross-market",
        "notes": "Cross-market ROBUST on BTC-4h AND ETH-4h",
        "strategy": "ema_crossover",
        "overrides": {
            "ema_short": 12, "ema_long": 50, "ema_trend": 100,
            "use_atr_sizing": True,
        },
        "markets": ["BTC-4h", "ETH-4h"],
    },
    {
        "id": "B2-ema-20-50-btc4h",
        "notes": "Best ema_crossover on BTC-4h (WF score 0.20)",
        "strategy": "ema_crossover",
        "overrides": {
            "ema_short": 20, "ema_long": 50, "ema_trend": 100,
            "use_atr_sizing": True,
        },
        "markets": ["BTC-4h", "ETH-4h"],
    },
    {
        "id": "B3-don40-btc4h",
        "notes": "Best donchian on BTC-4h (WF score 0.20)",
        "strategy": "donchian_breakout",
        "overrides": {
            "donchian_period": 40, "ema_trend": 0,
            "use_atr_sizing": True, "atr_stop_mult": 2.0,
        },
        "markets": ["BTC-4h", "ETH-4h"],
    },
    {
        "id": "B4-don20-eth4h-100",
        "notes": "Best donchian on ETH-4h (WF score 0.43)",
        "strategy": "donchian_breakout",
        "overrides": {
            "donchian_period": 20, "ema_trend": 100,
            "use_atr_sizing": True, "atr_stop_mult": 2.0,
        },
        "markets": ["ETH-4h", "BTC-4h"],
    },
    {
        "id": "B5-don20-eth4h-200",
        "notes": "2nd-best donchian on ETH-4h (WF score 0.39, pos 81%)",
        "strategy": "donchian_breakout",
        "overrides": {
            "donchian_period": 20, "ema_trend": 200,
            "use_atr_sizing": True, "atr_stop_mult": 2.0,
        },
        "markets": ["ETH-4h", "BTC-4h"],
    },
    {
        "id": "B6-rsi-btc1h-rescue",
        "notes": "RSI on BTC-1h failed WF (44% pos). Test if ADX_max rescues.",
        "strategy": "rsi_mean_reversion",
        "overrides": {
            "rsi_oversold": 25, "rsi_overbought": 70, "ema_trend": 200,
            "use_atr_sizing": False,
        },
        "markets": ["BTC-1h"],
    },
]


def _variants_for(strategy: str) -> dict[str, dict[str, Any]]:
    """Return the filter-variant overrides to test for a given strategy.

    We keep sub-knob values fixed at sensible defaults from the main
    experiment's STRATEGY_FILTER_PRESETS. The point is to ask "does this
    filter class help at all?", not to tune thresholds.
    """
    common: dict[str, dict[str, Any]] = {
        "V0-control":           {},
        "V1-htf1d-ema50":       {"use_htf_confirm": True, "htf_timeframe": "1d",
                                  "htf_ema_period": 50},
        "V2-htf1d-ema100":      {"use_htf_confirm": True, "htf_timeframe": "1d",
                                  "htf_ema_period": 100},
    }

    if strategy == "ema_crossover":
        return {
            **common,
            "V3-adx-min20":     {"use_adx_filter": True, "adx_min": 20.0,
                                  "adx_max": 0.0, "filter_adx_period": 14},
            "V5-htf50+adx20":   {"use_htf_confirm": True, "htf_timeframe": "1d",
                                  "htf_ema_period": 50,
                                  "use_adx_filter": True, "adx_min": 20.0,
                                  "adx_max": 0.0, "filter_adx_period": 14},
        }

    if strategy == "rsi_mean_reversion":
        return {
            **common,
            "V3-adx-max25":     {"use_adx_filter": True, "adx_min": 0.0,
                                  "adx_max": 25.0, "filter_adx_period": 14},
            "V5-htf50+adxmax":  {"use_htf_confirm": True, "htf_timeframe": "1d",
                                  "htf_ema_period": 50,
                                  "use_adx_filter": True, "adx_min": 0.0,
                                  "adx_max": 25.0, "filter_adx_period": 14},
        }

    if strategy == "donchian_breakout":
        return {
            **common,
            "V3-adx-min20":     {"use_adx_filter": True, "adx_min": 20.0,
                                  "adx_max": 0.0, "filter_adx_period": 14},
            "V4-vol-1.3x":      {"use_volume_filter": True, "vol_mult": 1.3,
                                  "vol_ma_period": 20},
            "V5-htf50+vol":     {"use_htf_confirm": True, "htf_timeframe": "1d",
                                  "htf_ema_period": 50,
                                  "use_volume_filter": True, "vol_mult": 1.3,
                                  "vol_ma_period": 20},
        }

    return common


# ------------------------------------------------------------ core loop ---


def _verdict(pos: float, mean: float) -> str:
    if pos >= 60 and mean > 0:
        return "ROBUST"
    if mean > 0:
        return "WEAK"
    return "NOT_VIABLE"


def _wf_score(mean: float, stdev: float, pos: float) -> float:
    if mean <= 0:
        return 0.0
    eps = 1e-6
    sharpe_windows = mean / (stdev + eps)
    consistency = max(0.0, (pos - 50) / 50)
    return sharpe_windows * (0.3 + 0.7 * consistency)


def _build_params(baseline: dict, market: dict, variant_overrides: dict) -> Params:
    return replace(
        Params(),
        symbol=market["symbol"],
        timeframe=market["timeframe"],
        bars=market["bars"],
        strategy=baseline["strategy"],
        initial_balance=1000.0,
        fee_pct=0.001,
        **baseline["overrides"],
        **variant_overrides,
    )


def run() -> list[dict]:
    rows: list[dict] = []
    total_jobs = sum(
        len(b["markets"]) * len(_variants_for(b["strategy"])) for b in BASELINES
    )
    job_i = 0
    t_start = time.time()

    for baseline in BASELINES:
        variants = _variants_for(baseline["strategy"])
        print(f"\n### {baseline['id']} "
              f"({baseline['strategy']}) — {baseline['notes']}")
        for mkt_id in baseline["markets"]:
            mkt = MARKETS[mkt_id]
            print(f"  [{mkt_id}]")
            hdr = (f"    {'variant':<22} {'trades':>6} {'wf_mean%':>9} "
                   f"{'wf_pos%':>8} {'wf_std%':>8} {'score':>6}  verdict")
            print(hdr)
            print("    " + "-" * (len(hdr) - 4))
            for vname, vover in variants.items():
                job_i += 1
                params = _build_params(baseline, mkt, vover)
                try:
                    with _silenced():
                        wf = walk_forward(params, mkt["wf_train"], mkt["wf_test"])
                except Exception as e:
                    print(f"    {vname:<22} SKIP: {e}")
                    continue
                mean = wf["mean_test_ret"]
                pos = wf["positive_rate"]
                stdev = wf["stdev_test_ret"]
                trades = sum(w.get("test_n", 0) for w in wf.get("windows", []))
                score = _wf_score(mean, stdev, pos)
                verdict = _verdict(pos, mean)
                elapsed = time.time() - t_start
                eta = (elapsed / job_i) * (total_jobs - job_i)
                print(
                    f"    {vname:<22} {trades:>6} {mean:>9.2f} "
                    f"{pos:>8.0f} {stdev:>8.2f} {score:>6.2f}  {verdict}"
                    f"    [{job_i}/{total_jobs}, eta {eta:.0f}s]"
                )
                rows.append({
                    "baseline": baseline["id"],
                    "strategy": baseline["strategy"],
                    "market": mkt_id,
                    "variant": vname,
                    "trades": trades,
                    "wf_mean": mean,
                    "wf_pos": pos,
                    "wf_stdev": stdev,
                    "wf_score": score,
                    "verdict": verdict,
                    "params": asdict(params),
                })
    return rows


# ------------------------------------------------------------ reporting ---


def _delta(x: float, ref: float) -> str:
    d = x - ref
    return f"{d:+.2f}" if d != 0 else "0.00"


def print_deltas(rows: list[dict]) -> None:
    """For each (baseline, market), print control vs each variant's delta."""
    print("\n\n=== DELTA TABLE (variant vs control per baseline/market) ===\n")
    # Group by (baseline, market)
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["baseline"], r["market"]), []).append(r)

    for (bid, mkt), items in groups.items():
        ctrl = next((r for r in items if r["variant"] == "V0-control"), None)
        if not ctrl:
            continue
        print(f"--- {bid}   on {mkt} ---")
        print(f"    control: trades={ctrl['trades']:>3}  "
              f"mean={ctrl['wf_mean']:+.2f}%  pos={ctrl['wf_pos']:.0f}%  "
              f"std={ctrl['wf_stdev']:.2f}%  score={ctrl['wf_score']:.2f}  "
              f"{ctrl['verdict']}")
        hdr = (f"    {'variant':<22} {'d_trades':>8} {'d_mean%':>8} "
               f"{'d_pos%':>7} {'d_std%':>7} {'d_score':>8}  verdict")
        print(hdr)
        print("    " + "-" * (len(hdr) - 4))
        for r in items:
            if r["variant"] == "V0-control":
                continue
            dt = r["trades"] - ctrl["trades"]
            dm = r["wf_mean"] - ctrl["wf_mean"]
            dp = r["wf_pos"] - ctrl["wf_pos"]
            ds = r["wf_stdev"] - ctrl["wf_stdev"]
            dsc = r["wf_score"] - ctrl["wf_score"]
            print(
                f"    {r['variant']:<22} {dt:>+8d} {dm:>+8.2f} "
                f"{dp:>+7.0f} {ds:>+7.2f} {dsc:>+8.2f}  {r['verdict']}"
            )
        print()


def pick_winners(rows: list[dict]) -> None:
    """Highlight variants that both (a) are ROBUST and (b) beat control."""
    print("=== PROMOTIONS (variants that turn WEAK/NOT_VIABLE -> ROBUST "
          "OR improve ROBUST score) ===\n")
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["baseline"], r["market"]), []).append(r)

    promoted: list[dict] = []
    for (bid, mkt), items in groups.items():
        ctrl = next((r for r in items if r["variant"] == "V0-control"), None)
        if not ctrl:
            continue
        for r in items:
            if r["variant"] == "V0-control":
                continue
            # Criterion 1: control was not ROBUST and variant is ROBUST
            rescue = ctrl["verdict"] != "ROBUST" and r["verdict"] == "ROBUST"
            # Criterion 2: both ROBUST but variant scores materially higher
            improve = (
                ctrl["verdict"] == "ROBUST"
                and r["verdict"] == "ROBUST"
                and r["wf_score"] > ctrl["wf_score"] + 0.03
            )
            if rescue or improve:
                promoted.append({
                    "baseline": bid, "market": mkt, "variant": r["variant"],
                    "ctrl_score": ctrl["wf_score"],
                    "new_score": r["wf_score"],
                    "d_score": r["wf_score"] - ctrl["wf_score"],
                    "ctrl_verdict": ctrl["verdict"],
                    "new_verdict": r["verdict"],
                    "ctrl_pos": ctrl["wf_pos"], "new_pos": r["wf_pos"],
                    "ctrl_mean": ctrl["wf_mean"], "new_mean": r["wf_mean"],
                    "ctrl_std": ctrl["wf_stdev"], "new_std": r["wf_stdev"],
                    "trades": r["trades"],
                    "reason": "RESCUE" if rescue else "IMPROVE",
                })

    if not promoted:
        print("(no variant materially improved any baseline)\n")
        return

    promoted.sort(key=lambda x: x["d_score"], reverse=True)
    hdr = (f"  {'reason':<8} {'baseline':<26} {'market':<8} "
           f"{'variant':<22} {'d_score':>8} {'verdict':>20}  d_pos%, d_mean%, d_std%")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for p in promoted:
        verdict_change = f"{p['ctrl_verdict']}->{p['new_verdict']}"
        print(
            f"  {p['reason']:<8} {p['baseline']:<26} {p['market']:<8} "
            f"{p['variant']:<22} {p['d_score']:>+8.2f} {verdict_change:>20}  "
            f"{p['new_pos']-p['ctrl_pos']:+.0f}%, "
            f"{p['new_mean']-p['ctrl_mean']:+.2f}%, "
            f"{p['new_std']-p['ctrl_std']:+.2f}%"
        )
    print()


def main() -> None:
    rows = run()
    print_deltas(rows)
    pick_winners(rows)
    with open(REPORT_JSON, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print(f"\nSaved detailed rows -> {REPORT_JSON}")


if __name__ == "__main__":
    main()
