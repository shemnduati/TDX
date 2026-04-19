"""
Run storage.

Each "run" is a single backtest or live session the user wants to keep. It
lives on disk under RUNS_DIR as a directory:

    runs/<id>/
        meta.json   # {id, label, kind, created_at, params, summary}
        data.json   # {equity_history, trades, balance, position, ...}

`id` is a timestamp + short random suffix, sortable and human-friendly.
`kind` is one of "backtest" | "live".
`data.json` matches the exact shape produced by PaperTrader.save_data(),
so it can be served directly to the frontend without transformation.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "runs")
os.makedirs(RUNS_DIR, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    # 20260418T114530-ab12
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def _run_dir(run_id: str) -> str:
    # Basic safety: reject ids that try to escape RUNS_DIR.
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError(f"Invalid run id: {run_id!r}")
    return os.path.join(RUNS_DIR, run_id)


def _params_to_dict(params: Any) -> dict:
    if is_dataclass(params):
        return asdict(params)
    if isinstance(params, dict):
        return dict(params)
    raise TypeError(f"Cannot serialize params of type {type(params)!r}")


def save_run(
    *,
    kind: str,
    params: Any,
    data: dict,
    summary: Optional[dict] = None,
    label: Optional[str] = None,
) -> dict:
    """Persist a run and return its meta dict."""
    if kind not in ("backtest", "live"):
        raise ValueError(f"kind must be 'backtest' or 'live', got {kind!r}")

    run_id = _new_id()
    run_dir = _run_dir(run_id)
    os.makedirs(run_dir, exist_ok=True)

    meta = {
        "id": run_id,
        "label": label or _default_label(kind, params),
        "kind": kind,
        "created_at": _now_iso(),
        "params": _params_to_dict(params),
        "summary": summary or _derive_summary(data),
    }

    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(run_dir, "data.json"), "w") as f:
        json.dump(data, f, indent=2)

    return meta


def _default_label(kind: str, params: Any) -> str:
    p = _params_to_dict(params)
    bits = [
        kind,
        p.get("strategy", "?"),
        p.get("symbol", "?"),
        p.get("timeframe", "?"),
    ]
    return " · ".join(str(b) for b in bits)


def _derive_summary(data: dict) -> dict:
    """Compute a lightweight summary from the full run data so the list view
    doesn't have to load the whole equity history."""
    trades = data.get("trades") or []
    equity = data.get("equity_history") or []
    initial = float(data.get("initial_balance") or 0)
    balance = float(data.get("balance") or initial)
    wins = [t for t in trades if float(t.get("profit", 0)) > 0]
    total_pnl = balance - initial if initial else 0.0

    gross_win = sum(float(t["profit"]) for t in trades if float(t.get("profit", 0)) > 0)
    gross_loss = -sum(float(t["profit"]) for t in trades if float(t.get("profit", 0)) < 0)
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = 999.0 if gross_win > 0 else 0.0

    # Per-trade Sharpe (see backtest._trade_sharpe for rationale).
    sharpe = 0.0
    if initial > 0 and len(trades) >= 2:
        returns = [float(t.get("profit", 0.0)) / initial for t in trades]
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        if var > 0:
            sharpe = mean / (var ** 0.5)

    # Max drawdown on the MTM equity curve.
    peak = float("-inf")
    max_dd = 0.0
    for p in equity:
        bal = float(p.get("balance", 0.0))
        if bal > peak:
            peak = bal
        if peak > 0:
            dd = (peak - bal) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "total_pnl": total_pnl,
        "return_pct": (total_pnl / initial * 100) if initial else 0.0,
        "balance": balance,
        "profit_factor": round(pf, 3),
        "trade_sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 3),
    }


def list_runs() -> list[dict]:
    """Return meta dicts for every run, newest first."""
    out: list[dict] = []
    if not os.path.isdir(RUNS_DIR):
        return out
    for name in os.listdir(RUNS_DIR):
        meta_path = os.path.join(RUNS_DIR, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return out


def load_run(run_id: str) -> dict:
    """Return {meta, data} for a single run."""
    run_dir = _run_dir(run_id)
    meta_path = os.path.join(run_dir, "meta.json")
    data_path = os.path.join(run_dir, "data.json")
    if not os.path.isfile(meta_path):
        raise FileNotFoundError(f"Run not found: {run_id}")
    with open(meta_path) as f:
        meta = json.load(f)
    with open(data_path) as f:
        data = json.load(f)
    return {"meta": meta, "data": data}


def delete_run(run_id: str) -> bool:
    run_dir = _run_dir(run_id)
    if not os.path.isdir(run_dir):
        return False
    shutil.rmtree(run_dir)
    return True


def rename_run(run_id: str, label: str) -> dict:
    run_dir = _run_dir(run_id)
    meta_path = os.path.join(run_dir, "meta.json")
    if not os.path.isfile(meta_path):
        raise FileNotFoundError(f"Run not found: {run_id}")
    with open(meta_path) as f:
        meta = json.load(f)
    meta["label"] = label
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return meta
