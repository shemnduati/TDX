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

    POST /walkforward/start       start a walk-forward validation job
        body: {"params": {...}, "train_bars": N, "test_bars": M,
               "step": S?}
    GET  /walkforward/status      current WF progress + per-window rows + summary
    POST /walkforward/cancel      stop the running WF job

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
"""
from __future__ import annotations

import json
import os
import traceback
from dataclasses import asdict, replace
from typing import Any

from flask import Flask, jsonify, request
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
from live_bot import LIVE
from strategies import REGISTRY as STRATEGY_REGISTRY
from sweep_runner import SWEEP
from walkforward_runner import WALKFORWARD


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")
BACKTEST_FILE = OUTPUT_FILE

app = Flask(__name__)
CORS(app)


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
    try:
        with open(path) as f:
            return jsonify(json.load(f))
    except (OSError, json.JSONDecodeError) as e:
        return jsonify(
            {
                **EMPTY_STATE,
                "error": f"Failed to read {os.path.basename(path)}: {e}",
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
    }
    for k in bool_fields & overrides.keys():
        overrides[k] = bool(overrides[k])
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
    except (TypeError, ValueError):
        return _json_error("train_bars, test_bars and step must be integers")

    try:
        status = WALKFORWARD.start(
            base_params=asdict(params),
            train_bars=train_bars,
            test_bars=test_bars,
            step=step,
        )
    except RuntimeError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e))
    return jsonify(status)


@app.route("/walkforward/cancel", methods=["POST"])
def walkforward_cancel():
    return jsonify(WALKFORWARD.cancel())


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


if __name__ == "__main__":
    # threaded=True so the live bot thread and incoming requests can coexist.
    app.run(debug=True, port=5001, host="127.0.0.1", threaded=True)
