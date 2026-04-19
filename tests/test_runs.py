"""
Tests for the runs store and sweep runner.

The conftest auto-redirects RUNS_DIR to tmp_path, so writes don't hit
the real `runs/` folder.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace

import pytest

import runs as runs_store
from backtest import Params


# -------------------------------------------------- runs.save_run / list -

class TestRunsStore:
    def _fake_data(
        self, trades: list[dict] | None = None, initial=1000.0, balance=None
    ) -> dict:
        trades = trades or []
        balance = balance if balance is not None else initial + sum(
            t["profit"] for t in trades
        )
        equity = [{"timestamp": "t", "balance": initial, "realized": True}]
        for t in trades:
            equity.append(
                {"timestamp": "t", "balance": balance, "realized": True}
            )
        return {
            "initial_balance": initial,
            "balance": balance,
            "position": None,
            "entry_price": 0,
            "position_size": 0,
            "trades": trades,
            "equity_history": equity,
            "updated_at": "t",
        }

    def test_save_and_load_roundtrip(self):
        params = Params()
        data = self._fake_data()
        meta = runs_store.save_run(kind="backtest", params=params, data=data)
        assert "id" in meta
        assert meta["kind"] == "backtest"

        loaded = runs_store.load_run(meta["id"])
        assert loaded["meta"]["id"] == meta["id"]
        assert loaded["data"]["initial_balance"] == 1000.0

    def test_list_runs_newest_first(self):
        # Force distinct timestamps.
        m1 = runs_store.save_run(
            kind="backtest", params=Params(), data=self._fake_data()
        )
        time.sleep(1.1)
        m2 = runs_store.save_run(
            kind="backtest", params=Params(), data=self._fake_data()
        )
        listed = runs_store.list_runs()
        assert listed[0]["id"] == m2["id"]
        assert listed[-1]["id"] == m1["id"]

    def test_delete_run_removes_dir(self):
        meta = runs_store.save_run(
            kind="backtest", params=Params(), data=self._fake_data()
        )
        assert runs_store.delete_run(meta["id"]) is True
        with pytest.raises(FileNotFoundError):
            runs_store.load_run(meta["id"])

    def test_rename_updates_label(self):
        meta = runs_store.save_run(
            kind="backtest", params=Params(),
            data=self._fake_data(), label="before",
        )
        renamed = runs_store.rename_run(meta["id"], "after")
        assert renamed["label"] == "after"
        again = runs_store.load_run(meta["id"])["meta"]
        assert again["label"] == "after"

    def test_rename_unknown_raises(self):
        with pytest.raises(FileNotFoundError):
            runs_store.rename_run("does-not-exist", "x")

    def test_invalid_id_rejected(self):
        with pytest.raises(ValueError):
            runs_store.load_run("../escape")


# -------------------------------------------------- runs._derive_summary

class TestDeriveSummary:
    def test_empty_data_is_safe(self):
        out = runs_store._derive_summary({})
        assert out["trades"] == 0
        assert out["balance"] == 0.0
        assert out["return_pct"] == 0.0
        assert out["profit_factor"] == 0.0
        assert out["max_drawdown_pct"] == 0.0

    def test_total_pnl_equals_sum_of_trade_profits(self):
        """Live-session snapshots save this way. The derived summary must
        agree with the same math the backtest uses: balance - initial ==
        sum(profit) over closed trades (PaperTrader only updates balance
        on close)."""
        trades = [
            {"profit": 50.0}, {"profit": -20.0}, {"profit": 10.0}
        ]
        data = {
            "initial_balance": 1000.0,
            "balance": 1000.0 + sum(t["profit"] for t in trades),
            "trades": trades,
            "equity_history": [{"balance": 1000.0}, {"balance": 1040.0}],
        }
        out = runs_store._derive_summary(data)
        assert out["trades"] == 3
        assert out["wins"] == 2
        assert out["total_pnl"] == pytest.approx(40.0)
        assert out["balance"] == pytest.approx(1040.0)
        # profit factor: 60 / 20 = 3.0
        assert out["profit_factor"] == pytest.approx(3.0)

    def test_profit_factor_clamped_when_no_losses(self):
        data = {
            "initial_balance": 1000.0,
            "balance": 1050.0,
            "trades": [{"profit": 50.0}],
            "equity_history": [{"balance": 1000.0}, {"balance": 1050.0}],
        }
        out = runs_store._derive_summary(data)
        assert out["profit_factor"] == 999.0

    def test_max_drawdown_from_equity_history(self):
        data = {
            "initial_balance": 1000.0,
            "balance": 1100.0,
            "trades": [{"profit": 100.0}],
            "equity_history": [
                {"balance": 1000.0},
                {"balance": 1200.0},
                {"balance": 900.0},
                {"balance": 1100.0},
            ],
        }
        out = runs_store._derive_summary(data)
        assert out["max_drawdown_pct"] == pytest.approx(25.0)


# ------------------------------------------------------- sweep runner ---

class TestSweepRunner:
    """Smoke-test the sweep runner end-to-end with a stubbed data fetcher.

    We monkeypatch `fetch_data` so tests never touch the exchange. A 2-combo
    grid runs in under a second on the synthetic frame.
    """

    @pytest.fixture
    def stubbed_fetch(self, monkeypatch, sine_ohlcv):
        import sweep_runner
        monkeypatch.setattr(sweep_runner, "fetch_data", lambda p: sine_ohlcv.copy())
        return sweep_runner

    def test_start_runs_all_combos_and_saves_runs(self, stubbed_fetch):
        sweep = stubbed_fetch.SweepJob()
        sweep.start(
            base_params={
                "strategy": "rsi_mean_reversion",
                "bars": 300,
                "initial_balance": 1000.0,
                "fee_pct": 0.0,
            },
            matrix={"rsi_oversold": [25, 30]},
            label_prefix="test",
        )
        # Wait up to 5 s for completion (should be <1 s in practice).
        for _ in range(50):
            st = sweep.status()
            if not st["running"]:
                break
            time.sleep(0.1)

        st = sweep.status()
        assert not st["running"]
        assert st["total"] == 2
        assert st["completed"] == 2
        assert st["error"] is None
        assert len(st["results"]) == 2
        # Each result is a saved RunMeta.
        for r in st["results"]:
            assert r["kind"] == "backtest"
            assert r["label"].startswith("test:")

    def test_empty_matrix_raises(self, stubbed_fetch):
        sweep = stubbed_fetch.SweepJob()
        with pytest.raises(ValueError, match="at least one"):
            sweep.start(base_params={}, matrix={})

    def test_empty_value_list_raises(self, stubbed_fetch):
        sweep = stubbed_fetch.SweepJob()
        with pytest.raises(ValueError, match="non-empty list"):
            sweep.start(
                base_params={}, matrix={"rsi_oversold": []}
            )

    def test_over_200_configs_rejected(self, stubbed_fetch):
        sweep = stubbed_fetch.SweepJob()
        with pytest.raises(ValueError, match="Refusing to run"):
            sweep.start(
                base_params={},
                matrix={"rsi_oversold": list(range(201))},
            )

    def test_second_start_while_running_raises(self, stubbed_fetch):
        sweep = stubbed_fetch.SweepJob()
        sweep.start(
            base_params={"strategy": "rsi_mean_reversion", "bars": 300,
                         "initial_balance": 1000.0, "fee_pct": 0.0},
            matrix={"rsi_oversold": [25, 28, 30]},
        )
        # It may or may not have finished by now, so only assert if still running.
        if sweep.status()["running"]:
            with pytest.raises(RuntimeError, match="already running"):
                sweep.start(base_params={}, matrix={"rsi_oversold": [25]})
        # Drain.
        sweep.cancel()
