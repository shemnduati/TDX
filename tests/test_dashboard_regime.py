from __future__ import annotations

import json

import pytest


@pytest.fixture
def client():
    import dashboard

    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def test_regime_expectancy_endpoint_shape(client, monkeypatch, sine_ohlcv):
    import dashboard

    monkeypatch.setattr(dashboard, "fetch_data", lambda _p: sine_ohlcv.copy())
    body = {
        "params": {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "bars": 300,
            "fee_pct": 0.0,
        },
        "strategies": ["rsi_mean_reversion", "ema_crossover"],
    }
    res = client.post(
        "/regime/expectancy",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["symbol"] == "BTC/USDT"
    assert isinstance(payload["strategies"], list)
    assert isinstance(payload["regimes"], list)
    assert isinstance(payload["rows"], list)


def test_regime_expectancy_rejects_bad_strategies_type(client):
    res = client.post(
        "/regime/expectancy",
        data=json.dumps({"params": {}, "strategies": "ema_crossover"}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "strategies" in (res.get_json() or {}).get("error", "")
