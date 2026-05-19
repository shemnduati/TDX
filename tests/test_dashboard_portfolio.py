from __future__ import annotations

import json

import pytest


@pytest.fixture
def client():
    import dashboard

    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def test_portfolio_run_endpoint_shape(client, monkeypatch):
    import dashboard

    fake = {
        "method": "shared_market_multi_strategy_runner",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "bars": 300,
        "master_initial_balance": 1000.0,
        "weights": {"ema_crossover": 0.5, "rsi_mean_reversion": 0.5},
        "risk_config": {"max_open_positions": 4},
        "combined": {
            "balance": 1050.0,
            "total_pnl": 50.0,
            "return_pct": 5.0,
            "total_trades": 10,
            "max_drawdown_pct": 4.0,
            "max_drawdown_pct_conservative_proxy": 5.0,
            "skipped_by_risk_limit": 1,
            "skipped_by_corr_limit": 2,
            "skipped_by_circuit": 3,
            "circuit_halted_bars": 4,
        },
        "sleeves": [],
    }
    monkeypatch.setattr(dashboard, "run_multi_strategy_portfolio", lambda *a, **k: fake)
    body = {
        "params": {"symbol": "BTC/USDT", "timeframe": "1h", "bars": 300},
        "weights": {"ema_crossover": 1.0},
    }
    res = client.post(
        "/portfolio/run",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["result"]["symbol"] == "BTC/USDT"
    assert "combined" in payload["result"]
    assert payload.get("saved") is not None


def test_portfolio_run_rejects_bad_weights(client):
    res = client.post(
        "/portfolio/run",
        data=json.dumps({"params": {}, "weights": []}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "weights" in (res.get_json() or {}).get("error", "")


def test_portfolio_run_rejects_bad_risk_overrides(client):
    res = client.post(
        "/portfolio/run",
        data=json.dumps(
            {
                "params": {},
                "weights": {"ema_crossover": 1.0},
                "risk": {"risk_budget_overrides": []},
            }
        ),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "risk_budget_overrides" in (res.get_json() or {}).get("error", "")
