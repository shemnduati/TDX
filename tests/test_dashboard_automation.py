from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def client():
    import dashboard

    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def test_tournament_run_endpoint_shape(client, monkeypatch):
    import dashboard

    fake = {
        "ok": 1,
        "total": 1,
        "rows": [
            {
                "name": "btc-4h-adx",
                "ok": True,
                "deployment_status": "promoted",
                "tournament_score": 12.3,
            }
        ],
        "promoted": 1,
        "demoted": 0,
        "candidate": 0,
    }
    monkeypatch.setattr(dashboard, "run_weekly_tournament", lambda **_: fake)
    res = client.post(
        "/tournament/run",
        data=json.dumps({"dry_run": True}),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["promoted"] == 1
    assert payload["rows"][0]["deployment_status"] == "promoted"


def test_tournament_defaults_to_optuna_engine(client, monkeypatch):
    import dashboard

    seen = {"engine": None}

    def _fake(**kwargs):
        seen["engine"] = kwargs.get("wf_train_engine")
        return {"ok": 0, "total": 0, "rows": [], "promoted": 0, "demoted": 0, "candidate": 0}

    monkeypatch.setattr(dashboard, "run_weekly_tournament", _fake)
    res = client.post(
        "/tournament/run",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert seen["engine"] == "optuna"


def test_monitor_divergence_for_live_run(client, monkeypatch):
    import dashboard

    monkeypatch.setattr(
        dashboard.runs_store,
        "load_run",
        lambda _id: {
            "meta": {
                "kind": "live",
                "params": {"symbol": "BTC/USDT", "timeframe": "1h", "bars": 300},
            },
            "data": {"initial_balance": 1000.0, "balance": 1010.0, "trades": []},
        },
    )
    monkeypatch.setattr(dashboard, "fetch_data", lambda p: [])
    monkeypatch.setattr(dashboard, "apply_full_indicators", lambda d, p: d)
    monkeypatch.setattr(
        dashboard,
        "replay_on_df",
        lambda *a, **k: {"return_pct": 9.0, "win_rate": 60.0, "trades_detail": []},
    )
    res = client.post(
        "/monitor/divergence",
        data=json.dumps({"run_id": "r1", "thresholds": {"min_timestamp_match_rate": 90}}),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert "verdict" in payload
    assert "return_delta_pct" in payload
    assert "matched_trades" in payload
    assert "thresholds" in payload
    assert payload["thresholds"]["min_timestamp_match_rate"] == 90.0


def test_monitor_readiness_rollup(client, monkeypatch):
    import dashboard

    # Use timestamps inside the default 30-day readiness window (CI date varies).
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(days=2)).isoformat()
    t2 = (now - timedelta(days=1)).isoformat()
    t_backtest = now.isoformat()

    monkeypatch.setattr(
        dashboard.runs_store,
        "list_runs",
        lambda: [
            {"id": "r1", "kind": "live", "created_at": t1, "label": "l1"},
            {"id": "r2", "kind": "live", "created_at": t2, "label": "l2"},
            {"id": "b1", "kind": "backtest", "created_at": t_backtest, "label": "b"},
        ],
    )
    monkeypatch.setattr(
        dashboard.runs_store,
        "load_run",
        lambda rid: {
            "meta": {"params": {"symbol": "BTC/USDT", "timeframe": "1h", "bars": 300}},
            "data": {"initial_balance": 1000.0, "balance": 1000.0, "trades": []},
        },
    )
    calls = {"n": 0}

    seen = {"thresholds": None}

    def _fake(_live_data, _params, *, thresholds=None):
        seen["thresholds"] = thresholds
        calls["n"] += 1
        return {
            "verdict": "aligned" if calls["n"] == 1 else "diverged",
            "return_delta_pct": 0.5 if calls["n"] == 1 else -3.0,
            "trade_count_delta": 0 if calls["n"] == 1 else 4,
            "timestamp_match_rate": 75.0,
            "mean_abs_pnl_delta_pct": 1.0,
        }

    monkeypatch.setattr(dashboard, "_compute_divergence_for_params", _fake)
    res = client.post(
        "/monitor/readiness",
        data=json.dumps({"days": 30, "min_samples": 1, "min_aligned_pct": 40}),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["runs_considered"] == 2
    assert payload["summary"]["samples"] == 2
    assert payload["summary"]["aligned"] == 1
    assert payload["summary"]["avg_timestamp_match_rate"] == 75.0
    assert payload["summary"]["avg_mean_abs_pnl_delta_pct"] == 1.0
    assert payload["summary"]["min_avg_timestamp_match_rate"] == 60.0
    assert payload["summary"]["max_avg_mean_abs_pnl_delta_pct"] == 2.0
    assert seen["thresholds"] == {}
