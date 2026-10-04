"""Optional password gate for the Flask dashboard API.

Enable by setting ``DASHBOARD_AUTH_PASSWORD`` in the environment. When unset,
all routes behave as before (local dev). When set, clients must POST
``/auth/login`` and send the session cookie on subsequent requests.

Also set ``DASHBOARD_SECRET_KEY`` (>= 16 chars) to sign session cookies.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import timedelta
from secrets import compare_digest

from flask import Flask, jsonify, request, session

_log = logging.getLogger(__name__)


def auth_enabled() -> bool:
    return bool((os.getenv("DASHBOARD_AUTH_PASSWORD") or "").strip())


def auth_username() -> str:
    return (os.getenv("DASHBOARD_AUTH_USERNAME") or "admin").strip() or "admin"


def _expected_password() -> str:
    return os.getenv("DASHBOARD_AUTH_PASSWORD") or ""


def cookie_secure() -> bool:
    return os.getenv("DASHBOARD_COOKIE_SECURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def secret_key() -> str:
    return (
        os.getenv("DASHBOARD_SECRET_KEY")
        or os.getenv("FLASK_SECRET_KEY")
        or ""
    ).strip()


def _resolve_session_secret() -> str:
    """Session signing key; never log the value."""
    sk = secret_key()
    if len(sk) >= 16:
        return sk
    if not auth_enabled():
        return "tdx-dev-no-dashboard-auth"
    pwd = _expected_password()
    derived = hashlib.sha256(
        b"tdx-dashboard-session-v1:" + pwd.encode("utf-8")
    ).hexdigest()
    _log.warning(
        "DASHBOARD_SECRET_KEY is unset or too short; using a key derived "
        "from DASHBOARD_AUTH_PASSWORD. Set DASHBOARD_SECRET_KEY (>=16 chars) "
        "in .env for production."
    )
    return derived


def configure_app(app: Flask) -> None:
    """Apply session settings and register auth routes / guard."""
    _register_routes(app)

    if not auth_enabled():
        app.config.setdefault("SECRET_KEY", "tdx-dev-no-dashboard-auth")
        return

    app.config["SECRET_KEY"] = _resolve_session_secret()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure(),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    app.before_request(_guard)


_PUBLIC_PREFIXES = ("/health", "/auth/")


def _is_public_path(path: str) -> bool:
    if path == "/health":
        return True
    if path.startswith("/auth/"):
        return True
    return False


def _guard():
    if not auth_enabled():
        return None
    if request.method == "OPTIONS":
        return None
    path = request.path or "/"
    if _is_public_path(path):
        return None
    if session.get("authenticated") is True:
        return None
    return jsonify({"error": "authentication required"}), 401


def _register_routes(app: Flask) -> None:
    @app.get("/auth/config")
    def auth_config():
        return jsonify(
            {
                "auth_required": auth_enabled(),
                "username": auth_username() if auth_enabled() else None,
            }
        )

    @app.get("/auth/me")
    def auth_me():
        if not auth_enabled():
            return jsonify({"authenticated": True, "auth_required": False})
        if session.get("authenticated") is True:
            return jsonify(
                {
                    "authenticated": True,
                    "auth_required": True,
                    "username": session.get("username") or auth_username(),
                }
            )
        return jsonify({"authenticated": False, "auth_required": True})

    @app.post("/auth/login")
    def auth_login():
        if not auth_enabled():
            return jsonify({"ok": True, "username": auth_username()})

        body = request.get_json(silent=True) or {}
        user = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")

        if user != auth_username() or not compare_digest(
            password, _expected_password()
        ):
            return jsonify({"error": "invalid username or password"}), 401

        session.clear()
        session["authenticated"] = True
        session["username"] = user
        session.permanent = True
        return jsonify({"ok": True, "username": user})

    @app.post("/auth/logout")
    def auth_logout():
        session.clear()
        return jsonify({"ok": True})
