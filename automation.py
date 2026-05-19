"""
Phase 5/6 automation helpers.

- Weekly tournament runner: rebaseline + auto promote/demote tagging
- Live vs backtest divergence summary
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import profiles as profile_store
from experiments.rebaseline_profiles_walkforward import run_rebaseline
from walkforward import resolve_train_engine


def _classify(summary: dict[str, Any], *, min_pos_rate: float, min_oos_ret: float) -> tuple[str, float]:
    pos = float(summary.get("positive_rate", 0.0))
    oos = float(summary.get("final_oos_return_pct", 0.0))
    mean_ret = float(summary.get("mean_test_ret", 0.0))
    score = (0.45 * pos) + (0.35 * oos) + (0.20 * mean_ret)
    if pos >= min_pos_rate and oos >= min_oos_ret and mean_ret > 0:
        return "promoted", score
    if oos < 0 or pos < (min_pos_rate * 0.75):
        return "demoted", score
    return "candidate", score


def run_weekly_tournament(
    *,
    profile_names: list[str] | None = None,
    train_bars: int = 500,
    test_bars: int = 200,
    step: int | None = None,
    mc_sims: int = 2000,
    wf_train_engine: str = "optuna",
    wf_optuna_trials: int = 64,
    wf_optuna_seed: int = 42,
    min_pos_rate: float = 55.0,
    min_oos_ret: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run WFO rebaseline and attach promotion decisions to profile baselines."""
    requested_engine = str(wf_train_engine).strip().lower()
    effective_engine, fallback_reason = resolve_train_engine(requested_engine)
    append_message = "weekly tournament rebaseline"
    if fallback_reason:
        append_message += " (fallback grid)"
    base = run_rebaseline(
        profile_names=profile_names,
        train_bars=train_bars,
        test_bars=test_bars,
        step=step,
        mc_sims=mc_sims,
        wf_train_engine=requested_engine,
        wf_optuna_trials=wf_optuna_trials,
        wf_optuna_seed=wf_optuna_seed,
        append_message=append_message,
        dry_run=dry_run,
        verbose=False,
    )
    rows: list[dict[str, Any]] = []
    promoted = demoted = candidate = 0
    for r in base.get("rows", []):
        if not r.get("ok"):
            rows.append(dict(r))
            continue
        summary = dict(r.get("summary") or {})
        status, score = _classify(
            summary, min_pos_rate=min_pos_rate, min_oos_ret=min_oos_ret
        )
        summary["deployment_status"] = status
        summary["tournament_score"] = float(round(score, 4))
        row = dict(r)
        row["deployment_status"] = status
        row["tournament_score"] = summary["tournament_score"]
        rows.append(row)
        if status == "promoted":
            promoted += 1
        elif status == "demoted":
            demoted += 1
        else:
            candidate += 1
        if not dry_run:
            profile_store.update_profile(
                r["name"],
                performance={"kind": "walkforward", "summary": summary},
                append_message=(
                    f"weekly tournament: {status} "
                    f"(score={summary['tournament_score']:.3f}, "
                    f"oos={float(summary.get('final_oos_return_pct', 0.0)):+.2f}%)"
                ),
            )
    return {
        **base,
        "rows": rows,
        "promoted": promoted,
        "demoted": demoted,
        "candidate": candidate,
        "thresholds": {
            "min_pos_rate": float(min_pos_rate),
            "min_oos_ret": float(min_oos_ret),
        },
        "requested_engine": requested_engine,
        "effective_engine": effective_engine,
        "fallback_reason": fallback_reason,
    }


def divergence_report(
    *,
    live_data: dict[str, Any],
    backtest_summary: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare live-paper trades to replayed backtest trades."""
    live_trades = list(live_data.get("trades") or [])
    bt_trades = list(backtest_summary.get("trades_detail") or [])
    cfg = {
        "max_return_delta_pct": 2.0,
        "max_trade_count_delta_abs": 2.0,
        "min_timestamp_match_rate": 50.0,
        "max_mean_abs_entry_slip_pct": 0.50,
        "max_mean_abs_exit_slip_pct": 0.50,
        "max_mean_abs_pnl_delta_pct": 1.50,
    }
    if thresholds:
        for k, v in thresholds.items():
            if k in cfg:
                cfg[k] = float(v)
    li = float(live_data.get("initial_balance") or 0.0)
    lb = float(live_data.get("balance") or li)
    live_ret = ((lb - li) / li * 100.0) if li > 0 else 0.0
    bt_ret = float(backtest_summary.get("return_pct", 0.0))
    live_wr = (
        sum(1 for t in live_trades if float(t.get("profit", 0.0)) > 0)
        / len(live_trades)
        * 100.0
        if live_trades
        else 0.0
    )
    bt_wr = float(backtest_summary.get("win_rate", 0.0))
    live_ts = {str(t.get("timestamp")) for t in live_trades if t.get("timestamp")}
    bt_ts = {str(t.get("timestamp")) for t in bt_trades if t.get("timestamp")}
    shared = len(live_ts & bt_ts)
    denom = max(1, min(len(live_ts), len(bt_ts)))
    ts_match_rate = shared / denom * 100.0

    live_by_key = {
        _trade_match_key(t): t for t in live_trades if _trade_match_key(t) is not None
    }
    bt_by_key = {
        _trade_match_key(t): t for t in bt_trades if _trade_match_key(t) is not None
    }
    shared_keys = sorted(set(live_by_key) & set(bt_by_key))
    entry_slips: list[float] = []
    exit_slips: list[float] = []
    pnl_deltas: list[float] = []
    for k in shared_keys:
        lt = live_by_key[k]
        bt = bt_by_key[k]
        le = float(lt.get("entry", 0.0))
        be = float(bt.get("entry", 0.0))
        lx = float(lt.get("exit", 0.0))
        bx = float(bt.get("exit", 0.0))
        lp = float(lt.get("profit", 0.0))
        bp = float(bt.get("profit", 0.0))
        if be != 0:
            entry_slips.append(abs(le - be) / abs(be) * 100.0)
        if bx != 0:
            exit_slips.append(abs(lx - bx) / abs(bx) * 100.0)
        denom_p = max(1.0, abs(bp))
        pnl_deltas.append(abs(lp - bp) / denom_p * 100.0)

    mean_entry_slip = sum(entry_slips) / len(entry_slips) if entry_slips else 0.0
    mean_exit_slip = sum(exit_slips) / len(exit_slips) if exit_slips else 0.0
    mean_pnl_delta = sum(pnl_deltas) / len(pnl_deltas) if pnl_deltas else 0.0
    matched = len(shared_keys)
    unmatched_live = len(set(live_by_key) - set(bt_by_key))
    unmatched_bt = len(set(bt_by_key) - set(live_by_key))

    ret_delta = live_ret - bt_ret
    cnt_delta = len(live_trades) - len(bt_trades)
    aligned = (
        abs(ret_delta) <= cfg["max_return_delta_pct"]
        and abs(cnt_delta) <= max(int(cfg["max_trade_count_delta_abs"]), int(len(bt_trades) * 0.25))
        and ts_match_rate >= cfg["min_timestamp_match_rate"]
        and mean_entry_slip <= cfg["max_mean_abs_entry_slip_pct"]
        and mean_exit_slip <= cfg["max_mean_abs_exit_slip_pct"]
        and mean_pnl_delta <= cfg["max_mean_abs_pnl_delta_pct"]
    )
    return {
        "live_trades": len(live_trades),
        "backtest_trades": len(bt_trades),
        "matched_trades": matched,
        "unmatched_live_trades": unmatched_live,
        "unmatched_backtest_trades": unmatched_bt,
        "trade_count_delta": cnt_delta,
        "live_return_pct": live_ret,
        "backtest_return_pct": bt_ret,
        "return_delta_pct": ret_delta,
        "live_win_rate": live_wr,
        "backtest_win_rate": bt_wr,
        "timestamp_match_rate": ts_match_rate,
        "mean_abs_entry_slip_pct": mean_entry_slip,
        "mean_abs_exit_slip_pct": mean_exit_slip,
        "mean_abs_pnl_delta_pct": mean_pnl_delta,
        "thresholds": cfg,
        "verdict": "aligned" if aligned else "diverged",
    }


def readiness_from_divergences(
    reports: list[dict[str, Any]],
    *,
    min_aligned_pct: float = 80.0,
    min_samples: int = 10,
    min_avg_timestamp_match_rate: float = 60.0,
    max_avg_mean_abs_pnl_delta_pct: float = 2.0,
) -> dict[str, Any]:
    """Aggregate divergence reports into a go-live readiness verdict."""
    n = len(reports)
    if n == 0:
        return {
            "samples": 0,
            "aligned": 0,
            "aligned_pct": 0.0,
            "avg_timestamp_match_rate": 0.0,
            "avg_mean_abs_pnl_delta_pct": 0.0,
            "min_aligned_pct": float(min_aligned_pct),
            "min_samples": int(min_samples),
            "min_avg_timestamp_match_rate": float(min_avg_timestamp_match_rate),
            "max_avg_mean_abs_pnl_delta_pct": float(max_avg_mean_abs_pnl_delta_pct),
            "verdict": "NO_DATA",
        }
    aligned = sum(1 for r in reports if str(r.get("verdict")) == "aligned")
    avg_ts_match = (
        sum(float(r.get("timestamp_match_rate", 0.0)) for r in reports) / n
    )
    avg_pnl_delta = (
        sum(float(r.get("mean_abs_pnl_delta_pct", 0.0)) for r in reports) / n
    )
    pct = aligned / n * 100.0
    ready = (
        n >= int(min_samples)
        and pct >= float(min_aligned_pct)
        and avg_ts_match >= float(min_avg_timestamp_match_rate)
        and avg_pnl_delta <= float(max_avg_mean_abs_pnl_delta_pct)
    )
    return {
        "samples": n,
        "aligned": aligned,
        "aligned_pct": pct,
        "avg_timestamp_match_rate": avg_ts_match,
        "avg_mean_abs_pnl_delta_pct": avg_pnl_delta,
        "min_aligned_pct": float(min_aligned_pct),
        "min_samples": int(min_samples),
        "min_avg_timestamp_match_rate": float(min_avg_timestamp_match_rate),
        "max_avg_mean_abs_pnl_delta_pct": float(max_avg_mean_abs_pnl_delta_pct),
        "verdict": "READY" if ready else "NOT_READY",
    }


def _trade_match_key(trade: dict[str, Any]) -> str | None:
    side = str(trade.get("side") or "").upper()
    ts_raw = trade.get("timestamp")
    if not side or ts_raw is None:
        return None
    try:
        ts = _parse_utc(ts_raw)
    except Exception:
        return None
    # Minute bucket + side is stable across paper/backtest route for same signal.
    bucket = int(ts.timestamp() // 60)
    return f"{side}:{bucket}"


def _parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        d = value
    else:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)
