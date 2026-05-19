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


def test_dashboard_session_expectancy_endpoint_shape(client, monkeypatch, sine_ohlcv):
    """POST /session/expectancy must return the right shape."""
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
        "weekend_split": False,
    }
    res = client.post(
        "/session/expectancy",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["symbol"] == "BTC/USDT"
    assert isinstance(payload["strategies"], list)
    assert isinstance(payload["sessions"], list)
    assert isinstance(payload["rows"], list)
    assert payload["weekend_split"] is False


def test_dashboard_session_expectancy_weekend_split(client, monkeypatch, sine_ohlcv):
    """weekend_split=True should produce session keys containing '|'."""
    import dashboard

    monkeypatch.setattr(dashboard, "fetch_data", lambda _p: sine_ohlcv.copy())
    body = {
        "params": {"fee_pct": 0.0, "bars": 300},
        "strategies": ["ema_crossover"],
        "weekend_split": True,
    }
    res = client.post(
        "/session/expectancy",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["weekend_split"] is True
    for row in payload["rows"]:
        assert "|" in row["session"]


def test_dashboard_session_expectancy_rejects_bad_strategies(client):
    res = client.post(
        "/session/expectancy",
        data=json.dumps({"params": {}, "strategies": "ema_crossover"}),
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "strategies" in (res.get_json() or {}).get("error", "")


def test_params_from_payload_allowed_sessions(client):
    """Verify allowed_sessions is validated and coerced by _params_from_payload."""
    import dashboard
    from backtest import Params

    p = dashboard._params_from_payload({"allowed_sessions": ["london", "ny"]})
    assert isinstance(p, Params)
    assert p.allowed_sessions == ("london", "ny")


def test_params_from_payload_allowed_sessions_rejects_invalid(client):
    import dashboard

    with pytest.raises(ValueError, match="invalid"):
        dashboard._params_from_payload({"allowed_sessions": ["mars"]})


def test_params_from_payload_block_weekends(client):
    import dashboard
    from backtest import Params

    p = dashboard._params_from_payload({"block_weekends": True})
    assert isinstance(p, Params)
    assert p.block_weekends is True
