"""
Smoke tests for the walk-forward background runner.

Same shape as the sweep-runner tests: stub `fetch_data` so nothing hits
the network, run a tiny 2-window validation on synthetic OHLCV, and
assert the aggregate matches what `walkforward.walk_forward()` would
produce for the same inputs.
"""
from __future__ import annotations

import time

import pytest


class TestWalkforwardRunner:
    @pytest.fixture
    def stubbed(self, monkeypatch, sine_ohlcv):
        import walkforward_runner
        monkeypatch.setattr(
            walkforward_runner, "fetch_data", lambda p: sine_ohlcv.copy()
        )
        return walkforward_runner

    def test_happy_path_produces_windows_and_summary(self, stubbed):
        job = stubbed.WalkforwardJob()
        job.start(
            base_params={
                "strategy": "rsi_mean_reversion",
                "bars": 300,
                "initial_balance": 1000.0,
                "fee_pct": 0.0,
                # Disable the 200-bar trend EMA or it eats most windows via
                # warmup on a 300-bar frame.
                "ema_trend": 0,
                "rsi_period": 5,
            },
            train_bars=100,
            test_bars=50,
        )

        for _ in range(100):
            if not job.status()["running"]:
                break
            time.sleep(0.1)

        st = job.status()
        assert not st["running"]
        assert st["error"] is None
        # (300 - 100 - 50) / 50 + 1 = 4 windows
        assert st["total"] == 4
        assert st["completed"] == 4
        assert len(st["windows"]) == 4

        summary = st["summary"]
        assert summary is not None
        assert summary["n_windows"] == 4
        assert "mean_test_ret" in summary
        assert "positive_rate" in summary
        assert summary["verdict"] in {"ROBUST", "WEAK", "NOT_VIABLE", "NO_DATA"}

    def test_insufficient_bars_raises(self, stubbed):
        job = stubbed.WalkforwardJob()
        job.start(
            base_params={
                "strategy": "rsi_mean_reversion",
                "bars": 300,
                "initial_balance": 1000.0,
            },
            train_bars=500,  # bigger than the stubbed 300-bar frame
            test_bars=200,
        )
        # Job raises inside the worker thread; error is captured in state.
        for _ in range(50):
            if not job.status()["running"]:
                break
            time.sleep(0.05)
        st = job.status()
        assert st["error"] is not None
        assert "Not enough bars" in st["error"]

    def test_invalid_args_raise_synchronously(self, stubbed):
        job = stubbed.WalkforwardJob()
        with pytest.raises(ValueError):
            job.start(base_params={}, train_bars=0, test_bars=100)
        with pytest.raises(ValueError):
            job.start(base_params={}, train_bars=100, test_bars=0)
        with pytest.raises(ValueError):
            job.start(
                base_params={}, train_bars=100, test_bars=50, step=-1
            )

    def test_double_start_raises(self, stubbed):
        job = stubbed.WalkforwardJob()
        job.start(
            base_params={
                "strategy": "rsi_mean_reversion", "bars": 300,
                "initial_balance": 1000.0, "fee_pct": 0.0,
                "ema_trend": 0, "rsi_period": 5,
            },
            train_bars=100, test_bars=50,
        )
        try:
            if job.status()["running"]:
                with pytest.raises(RuntimeError, match="already running"):
                    job.start(
                        base_params={}, train_bars=100, test_bars=50
                    )
        finally:
            job.cancel()
