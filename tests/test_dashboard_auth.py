"""Dashboard login gate (optional via DASHBOARD_AUTH_PASSWORD)."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DASHBOARD_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    import dashboard
    import dashboard_auth

    importlib.reload(dashboard_auth)
    importlib.reload(dashboard)

    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def test_auth_disabled_by_default(client):
    assert client.get("/auth/config").get_json()["auth_required"] is False
    assert client.get("/auth/me").get_json()["authenticated"] is True
    assert client.get("/profiles").status_code == 200


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_AUTH_PASSWORD", "test-pass-123")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "x" * 32)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    import dashboard
    import dashboard_auth

    importlib.reload(dashboard_auth)
    importlib.reload(dashboard)

    dashboard.app.config["TESTING"] = True
    with dashboard.app.test_client() as c:
        yield c


def test_auth_required_blocks_api(auth_client):
    assert auth_client.get("/auth/config").get_json()["auth_required"] is True
    assert auth_client.get("/auth/me").get_json()["authenticated"] is False
    assert auth_client.get("/profiles").status_code == 401


def test_auth_login_session(auth_client):
    bad = auth_client.post(
        "/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert bad.status_code == 401

    ok = auth_client.post(
        "/auth/login",
        json={"username": "admin", "password": "test-pass-123"},
    )
    assert ok.status_code == 200
    assert auth_client.get("/profiles").status_code == 200

    auth_client.post("/auth/logout")
    assert auth_client.get("/profiles").status_code == 401


def test_health_public_when_auth_enabled(auth_client):
    assert auth_client.get("/health").status_code == 200
