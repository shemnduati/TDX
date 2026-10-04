"""
Flask API for the TDX trading dashboard.

Endpoints:
    GET  /health                  simple liveness
    GET  /data                    latest live paper-trader state (data.json)
    GET  /backtest                latest ad-hoc backtest state (backtest.json)

    GET  /strategies              list available strategies + their hyperparams
    GET  /config/defaults         default Params values (for the form)

    POST /backtest/run            run a backtest and (optionally) save it
        body: {"params": {...}, "label": "optional", "save": true}
        returns: {"summary": {...}, "data": {...}, "saved": {meta}|null}
    POST /portfolio/run           run multi-strategy portfolio backtest
        body: {"params": {...}, "weights": {"strategy": weight, ...},
               "risk": {... optional overrides ...}}
        returns: {"result": {...}}

    GET    /runs                  list saved runs (newest first)
    GET    /runs/<id>             load a saved run (meta + data)
    DELETE /runs/<id>             delete a saved run
    PATCH  /runs/<id>             rename; body {"label": "..."}

    GET  /live/status             live bot status
    POST /live/start              start live bot; body {"params": {...}}
    POST /live/stop               stop live bot; optionally save as a run

    POST /sweep/start             start a parameter-grid sweep in the background
        body: {"base_params": {...}, "matrix": {"field": [v1, v2, ...]},
               "label_prefix": "optional"}
    GET  /sweep/status            current sweep progress + results
    POST /sweep/cancel            stop the currently-running sweep (if any)

    GET  /auth/config             whether login is required (+ default username)
    GET  /auth/me                 current session (always 200 when auth off)
    POST /auth/login              body {"username","password"} — session cookie
    POST /auth/logout             clear session

    POST /walkforward/start       start a walk-forward validation job
        body: {"params": {...}, "train_bars": N, "test_bars": M,
               "step": S?, "opt_matrix": {"field": [v1, ...]}?,
               "mc_sims": 2000?, "train_engine": "grid"|"optuna"?,
               "optuna_trials": 64?, "optuna_seed": 42?}
    GET  /walkforward/status      current WF progress + per-window rows + summary
    GET  /walkforward/stability   heatmap-ready matrix of chosen params vs outcomes
    POST /walkforward/cancel      stop the running WF job
    GET  /walkforward/stability.csv   CSV stability matrix (heatmap cells)
    GET  /walkforward/windows.csv     CSV per-window diagnostics + chosen params
    GET  /walkforward/report.json     full latest WFO job as JSON (download)
    POST /regime/expectancy           strategy x regime expectancy heatmap payload
    POST /session/expectancy          strategy x session expectancy heatmap payload
    POST /tournament/run              weekly WFO rerun + auto promote/demote
    POST /monitor/divergence          live-paper vs backtest divergence report
    POST /monitor/readiness           rolling readiness from live divergence

    GET    /profiles              list all profiles (name + metadata)
    GET    /profiles/<name>       load a single profile (full doc incl. params)
    POST   /profiles              save a profile (optionally a new version)
        body: {"name": "...", "params": {...}, "description": "...",
               "source": "...", "parent": "...",
               "changelog_message": "what changed",
               "performance": {"kind": "backtest", "run_id": "...",
                               "summary": {...}}}
    PATCH  /profiles/<name>       edit metadata / append changelog entry
        body: {"description": "...", "source": "...",
               "append_message": "added vol filter",
               "performance": {...} | null, "clear_performance": false}
    DELETE /profiles/<name>       remove a profile
    POST   /profiles/rebaseline/walkforward   refresh profile WF baselines
"""
from __future__ import annotations

import json
import os
import time
import traceback
import csv
import io
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, replace
from typing import Any

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

import runs as runs_store
import profiles as profile_store
from backtest import (
    OUTPUT_FILE,
    Params,
    apply_full_indicators,
    fetch_data,
    replay_on_df,
)
from config import AVAILABLE_SYMBOLS
from automation import (
    divergence_report,
    readiness_from_divergences,
    run_weekly_tournament,
)
from experiments.rebaseline_profiles_walkforward import run_rebaseline
from live_bot import LIVE
from portfolio import PortfolioRiskConfig, run_multi_strategy_portfolio
from regime import strategy_regime_expectancy, strategy_session_expectancy
from strategies import REGISTRY as STRATEGY_REGISTRY
from sweep_runner import SWEEP
from walkforward import _normalize_train_engine, resolve_train_engine, walkforward_report_payload
from walkforward_runner import WALKFORWARD
import dashboard_auth


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")
BACKTEST_FILE = OUTPUT_FILE

# API guardrails — Optuna installs are optional client-side too.
WALKFORWARD_OPTUNA_TRIALS_CAP = 512

app = Flask(__name__)
CORS(app, supports_credentials=True)
dashboard_auth.configure_app(app)


EMPTY_STATE = {
    "initial_balance": 1000,
    "balance": 1000,
    "position": None,
    "entry_price": 0,
    "position_size": 0,
    "trades": [],
    "equity_history": [],
    "updated_at": None,
}


# ------------------------------------------------------------------ helpers


def _serve_file(path: str):
    if not os.path.exists(path):
        return jsonify(EMPTY_STATE)
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            if not raw.strip():
                if attempt < 4:
                    time.sleep(0.05)
                    continue
                return jsonify(EMPTY_STATE)
            return jsonify(json.loads(raw))
        except json.JSONDecodeError as e:
            last_err = e
            if attempt < 4:
                time.sleep(0.05)
                continue
        except OSError as e:
            last_err = e
            break
    return jsonify(
        {
            **EMPTY_STATE,
            "error": f"Failed to read {os.path.basename(path)}: {last_err}",
        }
    ), 500


def _params_from_payload(payload: dict) -> Params:
    """Merge a partial params dict into a Params dataclass, ignoring fields
    that aren't defined on Params (so the frontend can send extras safely)."""
    if not isinstance(payload, dict):
        raise ValueError("params must be an object")
    defaults = Params()
    allowed = set(defaults.__dict__.keys())
    overrides = {k: v for k, v in payload.items() if k in allowed}
    # Coerce obvious int fields that JSON serializes as numbers.
    int_fields = {
        "bars",
        "ema_short",
        "ema_long",
        "ema_trend",
        "rsi_period",
        "donchian_period",
        "atr_ma_period",
        "ltf_ema_period",
        "sweep_lookback",
        "sweep_adx_period",
        "sweep_volume_lookback",
        "entry_cooldown_bars",
        "atr_period",
        "htf_ema_period",
        "filter_adx_period",
        "vol_ma_period",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "intrabar_random_seed",
        "funding_interval_hours",
    }
    for k in int_fields & overrides.keys():
        overrides[k] = int(overrides[k])
    bool_fields = {
        "use_atr_sizing",
        "use_htf_confirm",
        "use_adx_filter",
        "use_volume_filter",
        "use_atr_filter",
        "use_macd_confirm",
        "use_breakout_rsi",
        "use_atr_expansion",
        "enable_funding",
        "block_weekends",
    }
    for k in bool_fields & overrides.keys():
        overrides[k] = bool(overrides[k])
    # allowed_sessions: list[str] -> tuple[str, ...]; validate each bucket name.
    _valid_sessions = {"asia", "london", "overlap", "ny", "off"}
    if "allowed_sessions" in overrides:
        raw_sessions = overrides["allowed_sessions"]
        if isinstance(raw_sessions, (list, tuple)):
            bad = [s for s in raw_sessions if str(s) not in _valid_sessions]
            if bad:
                raise ValueError(
                    f"allowed_sessions contains invalid values: {bad}. "
                    f"Valid: {sorted(_valid_sessions)}"
                )
            overrides["allowed_sessions"] = tuple(str(s) for s in raw_sessions)
        else:
            raise ValueError("allowed_sessions must be an array")
    return replace(defaults, **overrides)


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ------------------------------------------------------------------- basic


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/data")
def get_data():
    return _serve_file(DATA_FILE)


@app.route("/backtest")
def get_backtest():
    return _serve_file(BACKTEST_FILE)


# ------------------------------------------------------- strategy metadata


@app.route("/strategies")
def list_strategies_endpoint():
    strategies = [
        {"name": s.name, "hyperparams": list(s.hyperparams)}
        for s in STRATEGY_REGISTRY.values()
    ]
    return jsonify({"strategies": strategies})


@app.route("/symbols")
def list_symbols_endpoint():
    """Curated list of markets the UI dropdown offers. Kept on the backend
    so the same list is visible to other consumers (tests, scripts) and
    can be extended without a frontend rebuild."""
    return jsonify({"symbols": list(AVAILABLE_SYMBOLS)})


@app.route("/config/defaults")
def config_defaults():
    return jsonify(asdict(Params()))


# ------------------------------------------------------------- backtesting


@app.route("/backtest/run", methods=["POST"])
def run_backtest():
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))

    label = body.get("label")
    should_save = bool(body.get("save", True))

    try:
        df = fetch_data(params)
        df = apply_full_indicators(df, params)
        # replay_on_df writes the run data to backtest.json for the "Current"
        # view — pass the existing OUTPUT_FILE so the dashboard polling still
        # sees fresh results immediately.
        summary = replay_on_df(
            df, params, data_file=BACKTEST_FILE, verbose=False
        )
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )

    # Load the resulting data.json equivalent so we can both return it and
    # (optionally) archive it as a saved run.
    with open(BACKTEST_FILE) as f:
        data = json.load(f)

    saved_meta: Any = None
    if should_save:
        saved_meta = runs_store.save_run(
            kind="backtest",
            params=params,
            data=data,
            summary=summary,
            label=label,
        )

    return jsonify(
        {
            "summary": summary,
            "data": data,
            "saved": saved_meta,
        }
    )


@app.route("/portfolio/run", methods=["POST"])
def run_portfolio():
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))

    weights = body.get("weights") or {}
    if not isinstance(weights, dict) or not weights:
        return _json_error("weights must be a non-empty object")
    try:
        weights = {str(k): float(v) for k, v in weights.items()}
    except (TypeError, ValueError):
        return _json_error("weights values must be numbers")

    risk_raw = body.get("risk") or {}
    if not isinstance(risk_raw, dict):
        return _json_error("risk must be an object")
    try:
        rb = risk_raw.get("risk_budget_overrides", {})
        cg = risk_raw.get("correlation_groups", {})
        if rb is None:
            rb = {}
        if cg is None:
            cg = {}
        if not isinstance(rb, dict) or not isinstance(cg, dict):
            return _json_error(
                "risk_budget_overrides and correlation_groups must be objects"
            )
        risk = PortfolioRiskConfig(
            max_open_positions=int(
                risk_raw.get("max_open_positions", 4)
            ),
            max_correlated_positions=int(
                risk_raw.get("max_correlated_positions", 2)
            ),
            vol_target_atr_pct=float(
                risk_raw.get("vol_target_atr_pct", 0.015)
            ),
            vol_scale_min=float(risk_raw.get("vol_scale_min", 0.25)),
            vol_scale_max=float(risk_raw.get("vol_scale_max", 2.0)),
            circuit_ema_fast=int(risk_raw.get("circuit_ema_fast", 20)),
            circuit_ema_slow=int(risk_raw.get("circuit_ema_slow", 60)),
            circuit_sigma=float(risk_raw.get("circuit_sigma", 2.0)),
            max_positions_per_group=int(
                risk_raw.get("max_positions_per_group", 2)
            ),
            risk_budget_overrides={
                str(k): float(v) for k, v in rb.items()
            },
            correlation_groups={
                str(k): str(v) for k, v in cg.items()
            },
        )
    except (TypeError, ValueError):
        return _json_error("invalid risk config")

    should_save = bool(body.get("save", True))
    label = body.get("label")
    try:
        result = run_multi_strategy_portfolio(
            params,
            weights,
            risk=risk,
            use_cache=True,
            verbose=False,
        )
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )
    saved_meta: Any = None
    if should_save:
        run_params = {
            "strategy": "portfolio",
            "symbol": params.symbol,
            "timeframe": params.timeframe,
            "bars": params.bars,
            "weights": result.get("weights", weights),
            "risk_config": result.get("risk_config", {}),
        }
        saved_meta = runs_store.save_run(
            kind="portfolio",
            params=run_params,
            data={
                "initial_balance": result.get("initial_balance", 0.0),
                "balance": result.get("balance", 0.0),
                "equity_history": result.get("equity_history", []),
                "trades": result.get("trades", []),
                "method": result.get("method"),
                "combined": result.get("combined", {}),
                "weights": result.get("weights", {}),
                "risk_config": result.get("risk_config", {}),
                "sleeves": result.get("sleeves", []),
                "symbol": result.get("symbol", params.symbol),
                "timeframe": result.get("timeframe", params.timeframe),
                "bars": result.get("bars", params.bars),
            },
            summary=result.get("combined"),
            label=label,
        )
    return jsonify({"result": result, "saved": saved_meta})


# ------------------------------------------------------------ runs storage


@app.route("/runs", methods=["GET"])
def runs_index():
    return jsonify({"runs": runs_store.list_runs()})


@app.route("/runs/<run_id>", methods=["GET"])
def runs_get(run_id: str):
    try:
        return jsonify(runs_store.load_run(run_id))
    except FileNotFoundError as e:
        return _json_error(str(e), 404)


@app.route("/runs/<run_id>", methods=["DELETE"])
def runs_delete(run_id: str):
    ok = runs_store.delete_run(run_id)
    return jsonify({"deleted": ok})


@app.route("/runs/<run_id>", methods=["PATCH"])
def runs_rename(run_id: str):
    body = request.get_json(silent=True) or {}
    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        return _json_error("label (string) is required")
    try:
        return jsonify(runs_store.rename_run(run_id, label.strip()))
    except FileNotFoundError as e:
        return _json_error(str(e), 404)


# ------------------------------------------------------------------- live


@app.route("/live/status", methods=["GET"])
def live_status():
    return jsonify(LIVE.status())


@app.route("/live/start", methods=["POST"])
def live_start():
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))
    try:
        status = LIVE.start(params)
    except RuntimeError as e:
        return _json_error(str(e), 409)
    return jsonify(status)


@app.route("/live/stop", methods=["POST"])
def live_stop():
    body = request.get_json(silent=True) or {}
    should_save = bool(body.get("save", True))
    label = body.get("label")

    status = LIVE.stop(snapshot=should_save)

    saved_meta: Any = None
    final_data = status.pop("_final_data", None)
    final_params = status.pop("_final_params", None)
    if should_save and final_data is not None and final_params is not None:
        # Only archive the session if it actually did something. A user who
        # clicks start/stop within a second shouldn't get an empty run.
        trades = final_data.get("trades") or []
        equity = final_data.get("equity_history") or []
        if trades or len(equity) > 1:
            saved_meta = runs_store.save_run(
                kind="live",
                params=final_params,
                data=final_data,
                label=label,
            )

    status["saved"] = saved_meta
    return jsonify(status)


# ------------------------------------------------------------------ sweep


@app.route("/sweep/status", methods=["GET"])
def sweep_status():
    return jsonify(SWEEP.status())


@app.route("/sweep/start", methods=["POST"])
def sweep_start():
    body = request.get_json(silent=True) or {}
    base = body.get("base_params") or {}
    matrix = body.get("matrix") or {}
    prefix = body.get("label_prefix") or "sweep"

    if not isinstance(base, dict):
        return _json_error("base_params must be an object")
    if not isinstance(matrix, dict) or not matrix:
        return _json_error("matrix must be a non-empty object of lists")

    # Only allow matrix keys that are actual Params fields.
    allowed = set(Params().__dict__.keys())
    unknown = set(matrix) - allowed
    if unknown:
        return _json_error(f"unknown matrix fields: {sorted(unknown)}")

    try:
        status = SWEEP.start(
            base_params=base, matrix=matrix, label_prefix=str(prefix)
        )
    except (RuntimeError, ValueError) as e:
        return _json_error(str(e), 409 if isinstance(e, RuntimeError) else 400)
    return jsonify(status)


@app.route("/sweep/cancel", methods=["POST"])
def sweep_cancel():
    return jsonify(SWEEP.cancel())


# ------------------------------------------------------------ walk-forward


@app.route("/walkforward/status", methods=["GET"])
def walkforward_status():
    return jsonify(WALKFORWARD.status())


@app.route("/walkforward/start", methods=["POST"])
def walkforward_start():
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))

    try:
        train_bars = int(body.get("train_bars", 500))
        test_bars = int(body.get("test_bars", 200))
        step_raw = body.get("step")
        step = int(step_raw) if step_raw not in (None, "", 0) else None
        mc_sims = int(body.get("mc_sims", 2000))
    except (TypeError, ValueError):
        return _json_error(
            "train_bars, test_bars, step and mc_sims must be integers"
        )

    te_raw = body.get("train_engine", "grid")
    try:
        requested_engine = _normalize_train_engine(str(te_raw))
        train_engine, _fallback_reason = resolve_train_engine(requested_engine)
    except ValueError as e:
        return _json_error(str(e))

    try:
        optuna_trials = int(body.get("optuna_trials", 64))
        optuna_seed = int(body.get("optuna_seed", 42))
    except (TypeError, ValueError):
        return _json_error("optuna_trials and optuna_seed must be integers")
    if optuna_trials < 1:
        return _json_error("optuna_trials must be >= 1")
    optuna_trials = min(optuna_trials, WALKFORWARD_OPTUNA_TRIALS_CAP)

    opt_matrix = body.get("opt_matrix") or {}
    if not isinstance(opt_matrix, dict):
        return _json_error("opt_matrix must be an object")
    allowed = set(Params().__dict__.keys())
    unknown = set(opt_matrix) - allowed
    if unknown:
        return _json_error(f"unknown opt_matrix fields: {sorted(unknown)}")
    for k, v in opt_matrix.items():
        if not isinstance(v, list) or len(v) == 0:
            return _json_error(
                f"opt_matrix[{k!r}] must be a non-empty list"
            )

    try:
        status = WALKFORWARD.start(
            base_params=asdict(params),
            train_bars=train_bars,
            test_bars=test_bars,
            step=step,
            opt_matrix=opt_matrix,
            mc_sims=mc_sims,
            train_engine=train_engine,
            optuna_trials=optuna_trials,
            optuna_seed=optuna_seed,
        )
    except RuntimeError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e))
    return jsonify(status)


@app.route("/walkforward/cancel", methods=["POST"])
def walkforward_cancel():
    return jsonify(WALKFORWARD.cancel())


@app.route("/walkforward/stability", methods=["GET"])
def walkforward_stability():
    """Heatmap-ready parameter stability cells for the latest WF job."""
    st = WALKFORWARD.status()
    summary = st.get("summary") or {}
    matrix = summary.get("stability_matrix") or {
        "x_key": None,
        "y_key": None,
        "cells": [],
    }
    return jsonify(
        {
            "running": bool(st.get("running")),
            "completed": int(st.get("completed", 0)),
            "total": int(st.get("total", 0)),
            "n_candidates": int(st.get("n_candidates", 0)),
            "tuned_keys": st.get("tuned_keys", []),
            "train_engine": st.get("train_engine", "grid"),
            "optuna_trials_requested": st.get("optuna_trials_requested"),
            "optuna_trials_effective": st.get("optuna_trials_effective"),
            "optuna_seed": st.get("optuna_seed"),
            "search_space_size": st.get("search_space_size"),
            "matrix": matrix,
        }
    )


@app.route("/walkforward/stability.csv", methods=["GET"])
def walkforward_stability_csv():
    """CSV export of latest walk-forward stability cells."""
    st = WALKFORWARD.status()
    summary = st.get("summary") or {}
    matrix = summary.get("stability_matrix") or {
        "x_key": None,
        "y_key": None,
        "cells": [],
    }
    x_key = matrix.get("x_key")
    y_key = matrix.get("y_key")
    cells = matrix.get("cells") or []

    out = io.StringIO()
    w = csv.DictWriter(
        out,
        fieldnames=[
            "x_key",
            "y_key",
            "x",
            "y",
            "n_windows",
            "mean_test_ret",
            "mean_test_mdd",
            "mean_train_score",
            "positive_rate",
        ],
    )
    w.writeheader()
    for c in cells:
        w.writerow(
            {
                "x_key": x_key,
                "y_key": y_key,
                "x": c.get("x"),
                "y": c.get("y"),
                "n_windows": c.get("n_windows"),
                "mean_test_ret": c.get("mean_test_ret"),
                "mean_test_mdd": c.get("mean_test_mdd"),
                "mean_train_score": c.get("mean_train_score"),
                "positive_rate": c.get("positive_rate"),
            }
        )
    csv_text = out.getvalue()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="walkforward_stability.csv"'
            )
        },
    )


@app.route("/walkforward/windows.csv", methods=["GET"])
def walkforward_windows_csv():
    """CSV export of per-window walk-forward results (metrics + chosen knobs)."""
    st = WALKFORWARD.status()
    windows = st.get("windows") or []
    tuned = list(st.get("tuned_keys") or [])
    snap = st.get("params") or {}

    meta_fields = [
        "strategy",
        "symbol",
        "timeframe",
        "bars_fetch",
        "train_bars",
        "test_bars",
        "step",
        "total_bars",
        "n_candidates",
        "train_engine",
        "optuna_trials_requested",
        "optuna_trials_effective",
        "optuna_seed",
        "search_space_size",
    ]
    window_fields = [
        "i",
        "train_ret",
        "test_ret",
        "train_n",
        "test_n",
        "test_wr",
        "test_mdd",
        "train_score",
    ]
    chosen_cols = [f"chosen_{k}" for k in tuned]
    fieldnames = meta_fields + window_fields + chosen_cols

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    bars_fetch = snap.get("bars") if isinstance(snap, dict) else None
    meta_row = {
        "strategy": snap.get("strategy") if isinstance(snap, dict) else None,
        "symbol": snap.get("symbol") if isinstance(snap, dict) else None,
        "timeframe": snap.get("timeframe") if isinstance(snap, dict) else None,
        "bars_fetch": bars_fetch,
        "train_bars": st.get("train_bars"),
        "test_bars": st.get("test_bars"),
        "step": st.get("step"),
        "total_bars": st.get("total_bars"),
        "n_candidates": st.get("n_candidates"),
        "train_engine": st.get("train_engine"),
        "optuna_trials_requested": st.get("optuna_trials_requested"),
        "optuna_trials_effective": st.get("optuna_trials_effective"),
        "optuna_seed": st.get("optuna_seed"),
        "search_space_size": st.get("search_space_size"),
    }
    for win in windows:
        chosen = win.get("chosen") or {}
        if not isinstance(chosen, dict):
            chosen = {}
        row = {**meta_row}
        row["i"] = win.get("i")
        row["train_ret"] = win.get("train_ret")
        row["test_ret"] = win.get("test_ret")
        row["train_n"] = win.get("train_n")
        row["test_n"] = win.get("test_n")
        row["test_wr"] = win.get("test_wr")
        row["test_mdd"] = win.get("test_mdd")
        row["train_score"] = win.get("train_score")
        for k in tuned:
            v = chosen.get(k, "")
            if isinstance(v, bool):
                v = str(v).lower()
            row[f"chosen_{k}"] = v
        w.writerow(row)

    csv_text = out.getvalue()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="walkforward_windows.csv"'
            )
        },
    )


@app.route("/walkforward/report.json", methods=["GET"])
def walkforward_report_json():
    """Export latest walk-forward job: job meta, summary, windows."""
    payload = walkforward_report_payload(WALKFORWARD.status())
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": (
                'attachment; filename="walkforward_report.json"'
            )
        },
    )


@app.route("/regime/expectancy", methods=["POST"])
def regime_expectancy():
    """Build strategy x regime expectancy from replayed historical trades."""
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))

    raw = body.get("strategies")
    if raw is None:
        strategy_names = sorted(STRATEGY_REGISTRY.keys())
    elif isinstance(raw, list):
        strategy_names = [str(s) for s in raw if str(s) in STRATEGY_REGISTRY]
        if not strategy_names:
            return _json_error("strategies list has no valid strategy names")
    else:
        return _json_error("strategies must be an array of names")

    try:
        df_raw = fetch_data(params)
        payload = strategy_regime_expectancy(
            base_params=params,
            strategy_names=strategy_names,
            df_raw=df_raw,
            apply_full_indicators_fn=apply_full_indicators,
            replay_on_df_fn=replay_on_df,
            include_unknown=False,
        )
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )
    payload["symbol"] = params.symbol
    payload["timeframe"] = params.timeframe
    payload["bars"] = params.bars
    return jsonify(payload)


@app.route("/session/expectancy", methods=["POST"])
def session_expectancy():
    """Build strategy x session expectancy from replayed historical trades."""
    body = request.get_json(silent=True) or {}
    try:
        params = _params_from_payload(body.get("params") or {})
    except ValueError as e:
        return _json_error(str(e))

    raw = body.get("strategies")
    if raw is None:
        strategy_names = sorted(STRATEGY_REGISTRY.keys())
    elif isinstance(raw, list):
        strategy_names = [str(s) for s in raw if str(s) in STRATEGY_REGISTRY]
        if not strategy_names:
            return _json_error("strategies list has no valid strategy names")
    else:
        return _json_error("strategies must be an array of names")

    weekend_split = bool(body.get("weekend_split", False))

    try:
        df_raw = fetch_data(params)
        payload = strategy_session_expectancy(
            base_params=params,
            strategy_names=strategy_names,
            df_raw=df_raw,
            apply_full_indicators_fn=apply_full_indicators,
            replay_on_df_fn=replay_on_df,
            weekend_split=weekend_split,
            include_unknown=False,
        )
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )
    payload["symbol"] = params.symbol
    payload["timeframe"] = params.timeframe
    payload["bars"] = params.bars
    return jsonify(payload)


@app.route("/tournament/run", methods=["POST"])
def tournament_run():
    body = request.get_json(silent=True) or {}
    raw_profiles = body.get("profiles")
    if raw_profiles in (None, ""):
        profile_names: list[str] = []
    else:
        if not isinstance(raw_profiles, list):
            return _json_error("profiles must be a list of profile names")
        bad = [x for x in raw_profiles if not isinstance(x, str)]
        if bad:
            return _json_error("profiles must contain only strings")
        profile_names = [p.strip() for p in raw_profiles if p and p.strip()]
    try:
        payload = run_weekly_tournament(
            profile_names=profile_names or None,
            train_bars=max(1, int(body.get("train_bars", 500))),
            test_bars=max(1, int(body.get("test_bars", 200))),
            step=(
                int(body.get("step"))
                if body.get("step") not in (None, "")
                else None
            ),
            mc_sims=max(0, int(body.get("mc_sims", 2000))),
            wf_train_engine=_normalize_train_engine(
                str(body.get("train_engine", "optuna"))
            ),
            wf_optuna_trials=max(1, int(body.get("optuna_trials", 64))),
            wf_optuna_seed=int(body.get("optuna_seed", 42)),
            min_pos_rate=float(body.get("min_pos_rate", 55.0)),
            min_oos_ret=float(body.get("min_oos_ret", 0.0)),
            dry_run=bool(body.get("dry_run", False)),
        )
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )
    return jsonify(payload)


@app.route("/monitor/divergence", methods=["POST"])
def monitor_divergence():
    body = request.get_json(silent=True) or {}
    run_id = body.get("run_id")
    compare_bars = body.get("compare_bars")
    if compare_bars in (None, ""):
        compare_bars = None
    else:
        try:
            compare_bars = max(100, int(compare_bars))
        except (TypeError, ValueError):
            return _json_error("compare_bars must be an integer")
    thresholds = body.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        return _json_error("thresholds must be an object")
    try:
        if run_id:
            payload = runs_store.load_run(str(run_id))
            if payload["meta"].get("kind") != "live":
                return _json_error("run_id must reference a live run", 400)
            live_data = payload["data"]
            params = _params_from_payload(payload["meta"].get("params") or {})
        else:
            status = LIVE.status()
            p = status.get("params")
            if not p:
                return _json_error(
                    "no active live params; provide run_id for a saved live run",
                    400,
                )
            params = _params_from_payload(p)
            if not os.path.exists(DATA_FILE):
                return _json_error("live data file not found", 400)
            with open(DATA_FILE, "r", encoding="utf-8") as fp:
                live_data = json.load(fp)
        if compare_bars is not None:
            params = replace(params, bars=int(compare_bars))
        out = _compute_divergence_for_params(
            live_data, params, thresholds=thresholds
        )
        out["symbol"] = params.symbol
        out["timeframe"] = params.timeframe
        out["bars"] = params.bars
        return jsonify(out)
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )


def _compute_divergence_for_params(
    live_data: dict[str, Any],
    params: Params,
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    df = fetch_data(params)
    df = apply_full_indicators(df, params)
    bt = replay_on_df(
        df,
        params,
        data_file=os.devnull,
        verbose=False,
        include_trades=True,
    )
    return divergence_report(
        live_data=live_data,
        backtest_summary=bt,
        thresholds=thresholds,
    )


@app.route("/monitor/readiness", methods=["POST"])
def monitor_readiness():
    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 30))
    min_aligned_pct = float(body.get("min_aligned_pct", 80.0))
    min_samples = int(body.get("min_samples", 10))
    min_avg_ts_match = float(body.get("min_avg_timestamp_match_rate", 60.0))
    max_avg_pnl_delta = float(body.get("max_avg_mean_abs_pnl_delta_pct", 2.0))
    thresholds = body.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        return _json_error("thresholds must be an object")
    compare_bars_raw = body.get("compare_bars")
    if compare_bars_raw in (None, ""):
        compare_bars = None
    else:
        try:
            compare_bars = max(100, int(compare_bars_raw))
        except (TypeError, ValueError):
            return _json_error("compare_bars must be an integer")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    reports: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    try:
        for meta in runs_store.list_runs():
            if meta.get("kind") != "live":
                continue
            created = meta.get("created_at")
            if not created:
                continue
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if ts < cutoff:
                continue
            payload = runs_store.load_run(str(meta.get("id")))
            params = _params_from_payload(payload["meta"].get("params") or {})
            if compare_bars is not None:
                params = replace(params, bars=max(100, compare_bars))
            rep = _compute_divergence_for_params(
                payload["data"],
                params,
                thresholds=thresholds,
            )
            reports.append(rep)
            rows.append(
                {
                    "run_id": meta.get("id"),
                    "label": meta.get("label"),
                    "created_at": created,
                    "verdict": rep.get("verdict"),
                    "return_delta_pct": rep.get("return_delta_pct"),
                    "trade_count_delta": rep.get("trade_count_delta"),
                    "timestamp_match_rate": rep.get("timestamp_match_rate"),
                    "mean_abs_pnl_delta_pct": rep.get("mean_abs_pnl_delta_pct"),
                }
            )
        agg = readiness_from_divergences(
            reports,
            min_aligned_pct=min_aligned_pct,
            min_samples=min_samples,
            min_avg_timestamp_match_rate=min_avg_ts_match,
            max_avg_mean_abs_pnl_delta_pct=max_avg_pnl_delta,
        )
        return jsonify(
            {
                "days": max(1, days),
                "runs_considered": len(rows),
                "summary": agg,
                "rows": rows,
            }
        )
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )


# -------------------------------------------------------------- profiles ---
# Per-market parameter presets. See profiles.py for the loader and the
# keep-up workflow this is the UI face of. Every write goes through
# profile_store so validation (unknown-field check, name regex) is
# centralised.


def _profile_summary(doc: dict, child_counts: dict[str, int]) -> dict:
    """Lightweight meta view of a profile for the dropdown / list tab.

    We surface the few Params fields that identify the market and
    strategy at a glance, plus a compact performance preview for the
    list view. The full params + full changelog are only returned from
    GET /profiles/<name> to keep the list response small.
    """
    p = doc.get("params", {})
    perf = doc.get("performance") or None
    perf_preview = None
    if perf and isinstance(perf.get("summary"), dict):
        s = perf["summary"]
        # Pick the handful of metrics the list column shows. Missing
        # metrics just don't appear; the UI tolerates absence.
        perf_preview = {
            k: s[k]
            for k in (
                "trades", "return_pct", "max_drawdown_pct",
                "profit_factor", "trade_sharpe", "win_rate",
            )
            if k in s
        }
        perf_preview["kind"] = perf.get("kind", "backtest")

    return {
        "name": doc.get("name"),
        "description": doc.get("description", ""),
        "source": doc.get("source", ""),
        "parent": doc.get("parent"),
        "created_at": doc.get("created_at"),
        # Shallow preview — the fields users care about at glance time.
        "preview": {
            k: p.get(k)
            for k in ("symbol", "timeframe", "strategy")
            if k in p
        },
        # Count of overridden fields; useful as a "how opinionated is
        # this profile?" badge.
        "override_count": len(p),
        # Number of later profiles that list this one as parent, so the
        # list can show "has descendants" cues without a second request.
        "version_count": child_counts.get(doc.get("name") or "", 0),
        "performance_preview": perf_preview,
    }


@app.route("/profiles", methods=["GET"])
def profiles_list():
    names = profile_store.list_profiles()
    # Two-pass: load once, then walk parents so version_count is O(N).
    docs: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for n in names:
        try:
            docs[n] = profile_store.load_profile(n)
        except (ValueError, FileNotFoundError, OSError) as e:
            errors[n] = str(e)

    child_counts: dict[str, int] = {}
    for d in docs.values():
        parent = d.get("parent")
        if parent:
            child_counts[parent] = child_counts.get(parent, 0) + 1

    items: list[dict] = []
    for n in names:
        if n in docs:
            items.append(_profile_summary(docs[n], child_counts))
        else:
            items.append({
                "name": n,
                "description": f"(unreadable: {errors[n]})",
                "source": "",
                "parent": None,
                "created_at": None,
                "preview": {},
                "override_count": 0,
                "version_count": 0,
                "performance_preview": None,
            })
    return jsonify({"profiles": items})


@app.route("/profiles/<name>", methods=["GET"])
def profiles_get(name: str):
    try:
        return jsonify(profile_store.load_profile(name))
    except FileNotFoundError as e:
        return _json_error(str(e), 404)
    except ValueError as e:
        return _json_error(str(e), 400)


@app.route("/profiles", methods=["POST"])
def profiles_save():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    params_payload = body.get("params")
    description = body.get("description") or ""
    source = body.get("source") or ""
    parent = body.get("parent") or None
    changelog_message = body.get("changelog_message") or None
    performance = body.get("performance")  # None / dict; normalised downstream

    if not isinstance(name, str) or not name.strip():
        return _json_error("name (string) is required")
    if not isinstance(params_payload, dict):
        return _json_error("params (object) is required")
    if parent is not None and not isinstance(parent, str):
        return _json_error("parent must be a string or null")

    try:
        params = _params_from_payload(params_payload)
    except ValueError as e:
        return _json_error(str(e))

    try:
        path = profile_store.save_profile(
            name.strip(),
            params,
            description=description,
            source=source,
            parent=parent.strip() if isinstance(parent, str) else None,
            changelog_message=changelog_message,
            performance=performance,
        )
    except ValueError as e:
        return _json_error(str(e))
    except OSError as e:
        return _json_error(f"failed to write profile: {e}", 500)

    # Re-read so the response exactly reflects what was persisted (incl.
    # the auto-generated created_at timestamp).
    doc = profile_store.load_profile(name.strip())
    return jsonify({"saved": doc, "path": path})


@app.route("/profiles/<name>", methods=["PATCH"])
def profiles_patch(name: str):
    """Amend an existing profile's metadata or append a changelog entry.

    Cannot change `params` — that's intentional. To iterate on params,
    create a new profile with `parent=<old>` so the history is
    preserved and reproducible.
    """
    body = request.get_json(silent=True) or {}
    try:
        doc = profile_store.update_profile(
            name,
            description=body.get("description"),
            source=body.get("source"),
            performance=body.get("performance"),
            clear_performance=bool(body.get("clear_performance", False)),
            append_message=body.get("append_message"),
        )
    except FileNotFoundError as e:
        return _json_error(str(e), 404)
    except ValueError as e:
        return _json_error(str(e), 400)
    except OSError as e:
        return _json_error(f"failed to write profile: {e}", 500)
    return jsonify({"saved": doc})


@app.route("/profiles/<name>", methods=["DELETE"])
def profiles_delete(name: str):
    try:
        profile_store.delete_profile(name)
    except ValueError as e:
        return _json_error(str(e), 400)
    return jsonify({"deleted": True})


@app.route("/profiles/rebaseline/walkforward", methods=["POST"])
def profiles_rebaseline_walkforward():
    """Batch refresh profile performance baselines from walk-forward."""
    body = request.get_json(silent=True) or {}
    raw_profiles = body.get("profiles")
    if raw_profiles in (None, ""):
        profiles_list: list[str] = []
    else:
        if not isinstance(raw_profiles, list):
            return _json_error("profiles must be a list of profile names")
        bad = [x for x in raw_profiles if not isinstance(x, str)]
        if bad:
            return _json_error("profiles must contain only strings")
        profiles_list = [p.strip() for p in raw_profiles if p and p.strip()]

    try:
        train_bars = int(body.get("train_bars", 500))
        test_bars = int(body.get("test_bars", 200))
        step_raw = body.get("step")
        step = int(step_raw) if step_raw not in (None, "", 0) else None
        mc_sims = int(body.get("mc_sims", 2000))
        wf_optuna_trials = int(body.get("optuna_trials", 64))
        wf_optuna_seed = int(body.get("optuna_seed", 42))
    except (TypeError, ValueError):
        return _json_error(
            "train_bars, test_bars, step, mc_sims, optuna_trials and optuna_seed must be integers"
        )

    te_raw = body.get("train_engine", "grid")
    try:
        train_engine = _normalize_train_engine(str(te_raw))
    except ValueError as e:
        return _json_error(str(e))

    if train_bars <= 0 or test_bars <= 0:
        return _json_error("train_bars and test_bars must be > 0")
    if step is not None and step <= 0:
        return _json_error("step must be > 0")
    if mc_sims < 0:
        return _json_error("mc_sims must be >= 0")
    if wf_optuna_trials < 1:
        return _json_error("optuna_trials must be >= 1")

    append_message = body.get("append_message")
    if append_message is not None and not isinstance(append_message, str):
        return _json_error("append_message must be a string")
    dry_run = bool(body.get("dry_run", False))

    try:
        payload = run_rebaseline(
            profile_names=profiles_list or None,
            train_bars=train_bars,
            test_bars=test_bars,
            step=step,
            mc_sims=mc_sims,
            wf_train_engine=train_engine,
            wf_optuna_trials=min(wf_optuna_trials, WALKFORWARD_OPTUNA_TRIALS_CAP),
            wf_optuna_seed=wf_optuna_seed,
            append_message=(
                append_message.strip()
                if isinstance(append_message, str) and append_message.strip()
                else "rebaseline performance with walk-forward + final holdout OOS"
            ),
            dry_run=dry_run,
            report_out=None,
            verbose=False,
        )
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        return _json_error(
            f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", 500
        )

    payload["profiles_updated"] = 0 if dry_run else int(payload.get("ok", 0))
    return jsonify(payload)


if __name__ == "__main__":
    # threaded=True so the live bot thread and incoming requests can coexist.
    app.run(debug=True, port=5001, host="127.0.0.1", threaded=True)
