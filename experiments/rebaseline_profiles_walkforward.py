"""
Batch rebaseline all profiles using walk-forward + final holdout OOS.

Updates each profile's `performance` payload to:
    {
      "kind": "walkforward",
      "summary": {... key WF + final OOS metrics ...}
    }

Usage:
    python -m experiments.rebaseline_profiles_walkforward
    python -m experiments.rebaseline_profiles_walkforward --dry-run
    python -m experiments.rebaseline_profiles_walkforward --profile btc-4h-adx
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any, Optional

from backtest import Params
import profiles as profile_store
from walkforward import walk_forward


def _performance_summary_from_wf(r: dict[str, Any]) -> dict[str, Any]:
    final_oos = r.get("final_oos") or {}
    return {
        "n_windows": int(r.get("n_windows", 0)),
        "mean_test_ret": float(r.get("mean_test_ret", 0.0)),
        "median_test_ret": float(r.get("median_test_ret", 0.0)),
        "stdev_test_ret": float(r.get("stdev_test_ret", 0.0)),
        "positive_rate": float(r.get("positive_rate", 0.0)),
        "mean_test_mdd_pct": float(r.get("mean_test_mdd_pct", 0.0)),
        "total_test_trades": int(r.get("total_test_trades", 0)),
        "total_train_trades": int(r.get("total_train_trades", 0)),
        "unique_selected_configs": int(r.get("unique_selected_configs", 0)),
        "selection_transition_rate": float(r.get("selection_transition_rate", 0.0)),
        "tuned_keys": list(r.get("tuned_keys") or []),
        "train_engine": r.get("train_engine", "grid"),
        "dev_end_bar": int(r.get("dev_end_bar", 0)),
        "holdout_start_bar": int(r.get("holdout_start_bar", 0)),
        "holdout_bars": int(r.get("holdout_bars", 0)),
        "final_oos_return_pct": float(final_oos.get("return_pct", 0.0)),
        "final_oos_trades": int(final_oos.get("trades", 0)),
        "final_oos_win_rate": float(final_oos.get("win_rate", 0.0)),
        "final_oos_mdd_pct": float(final_oos.get("max_drawdown_pct", 0.0)),
        "final_oos_profit_factor": float(final_oos.get("profit_factor", 0.0)),
        "final_oos_policy": final_oos.get("policy"),
    }


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Only process specific profile(s). Repeatable.",
    )
    p.add_argument("--train-bars", type=int, default=500)
    p.add_argument("--test-bars", type=int, default=200)
    p.add_argument(
        "--step",
        type=int,
        default=None,
        help="WFO step (defaults to test-bars if omitted).",
    )
    p.add_argument("--mc-sims", type=int, default=2000)
    p.add_argument(
        "--wf-train-engine",
        choices=["grid", "optuna"],
        default="grid",
    )
    p.add_argument("--wf-optuna-trials", type=int, default=64)
    p.add_argument("--wf-optuna-seed", type=int, default=42)
    p.add_argument(
        "--append-message",
        default="rebaseline performance with walk-forward + final holdout OOS",
        help="Changelog message appended on profile update.",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--report-out",
        default=None,
        help="Optional output JSON path with per-profile results/errors.",
    )
    a = p.parse_args(argv)
    if a.train_bars <= 0 or a.test_bars <= 0:
        p.error("--train-bars and --test-bars must be > 0")
    if a.step is not None and int(a.step) <= 0:
        p.error("--step must be > 0 when provided")
    if int(a.wf_optuna_trials) < 1:
        p.error("--wf-optuna-trials must be >= 1")
    return a


def run_rebaseline(
    *,
    profile_names: Optional[list[str]] = None,
    train_bars: int = 500,
    test_bars: int = 200,
    step: Optional[int] = None,
    mc_sims: int = 2000,
    wf_train_engine: str = "grid",
    wf_optuna_trials: int = 64,
    wf_optuna_seed: int = 42,
    append_message: str = "rebaseline performance with walk-forward + final holdout OOS",
    dry_run: bool = False,
    report_out: Optional[str] = None,
    verbose: bool = True,
) -> dict[str, Any]:
    if train_bars <= 0 or test_bars <= 0:
        raise ValueError("train_bars and test_bars must be > 0")
    if step is not None and int(step) <= 0:
        raise ValueError("step must be > 0 when provided")
    if int(wf_optuna_trials) < 1:
        raise ValueError("wf_optuna_trials must be >= 1")

    selected = [str(x).strip() for x in (profile_names or []) if str(x).strip()]
    names = selected or profile_store.list_profiles()
    if not names:
        payload = {
            "ok": 0,
            "total": 0,
            "dry_run": bool(dry_run),
            "rows": [],
            "elapsed_secs": 0.0,
        }
        return payload

    out_rows: list[dict[str, Any]] = []
    if verbose:
        print(
            f"Rebaseline {len(names)} profile(s): "
            f"train={train_bars} test={test_bars} step={step or test_bars} "
            f"engine={wf_train_engine}"
        )
    t0 = time.time()
    for i, name in enumerate(names, 1):
        try:
            _ = profile_store.load_profile(name)  # validate readable before run
            params = profile_store.apply_profile(Params(), name)
            wf = walk_forward(
                params,
                int(train_bars),
                int(test_bars),
                int(step) if step is not None else None,
                mc_sims=int(mc_sims),
                train_engine=str(wf_train_engine),
                optuna_trials=int(wf_optuna_trials),
                optuna_seed=int(wf_optuna_seed),
            )
            summary = _performance_summary_from_wf(wf)
            perf = {"kind": "walkforward", "summary": summary}
            if not dry_run:
                profile_store.update_profile(
                    name,
                    performance=perf,
                    append_message=append_message,
                )
            row = {
                "name": name,
                "ok": True,
                "symbol": params.symbol,
                "timeframe": params.timeframe,
                "strategy": params.strategy,
                "summary": summary,
            }
            out_rows.append(row)
            if verbose:
                print(
                    f"[{i}/{len(names)}] OK {name:<28} "
                    f"WFO mean={summary['mean_test_ret']:+6.2f}% "
                    f"pos={summary['positive_rate']:>5.1f}% "
                    f"final_oos={summary['final_oos_return_pct']:+6.2f}%"
                )
        except Exception as e:
            out_rows.append({"name": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
            if verbose:
                print(f"[{i}/{len(names)}] ERR {name:<28} {type(e).__name__}: {e}")

    elapsed = time.time() - t0
    ok_n = sum(1 for r in out_rows if r.get("ok"))
    if verbose:
        print(f"\nDone in {elapsed:.1f}s  ok={ok_n}/{len(out_rows)}")
        if dry_run:
            print("Dry-run only: profiles were NOT modified.")

    payload = {
        "ok": ok_n,
        "total": len(out_rows),
        "dry_run": bool(dry_run),
        "elapsed_secs": round(elapsed, 3),
        "rows": out_rows,
        "started_with": {
            "train_bars": int(train_bars),
            "test_bars": int(test_bars),
            "step": int(step) if step is not None else None,
            "mc_sims": int(mc_sims),
            "train_engine": str(wf_train_engine),
            "optuna_trials": int(wf_optuna_trials),
            "optuna_seed": int(wf_optuna_seed),
            "profiles": names,
        },
    }
    if report_out:
        with open(report_out, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, default=str)
        if verbose:
            print(f"Wrote report -> {report_out}")
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    a = _parse_args(argv)
    payload = run_rebaseline(
        profile_names=list(a.profile or []),
        train_bars=int(a.train_bars),
        test_bars=int(a.test_bars),
        step=int(a.step) if a.step is not None else None,
        mc_sims=int(a.mc_sims),
        wf_train_engine=str(a.wf_train_engine),
        wf_optuna_trials=int(a.wf_optuna_trials),
        wf_optuna_seed=int(a.wf_optuna_seed),
        append_message=str(a.append_message),
        dry_run=bool(a.dry_run),
        report_out=str(a.report_out) if a.report_out else None,
        verbose=True,
    )
    return 0 if int(payload.get("ok", 0)) == int(payload.get("total", 0)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
