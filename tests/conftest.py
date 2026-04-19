"""
Shared pytest fixtures.

Design goals:
- Tests NEVER touch the exchange. We build synthetic OHLCV frames in-memory.
- Tests NEVER touch the project's real `data.json` / `backtest.json` / `runs/`.
  Any PaperTrader or runs-store interaction uses tmp_path.
- Fixtures are small and composable; complex setup lives in the test itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pytest

# Make the project root importable for `import backtest`, `import runs`, etc.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_disk(tmp_path, monkeypatch):
    """Redirect default file outputs to tmp_path for every test.

    This is paranoid on purpose: if a test accidentally constructs a bare
    PaperTrader() or touches runs storage, we want it to land in tmp_path,
    not in the user's real repo.
    """
    import paper_trader
    import runs as runs_store
    import backtest

    monkeypatch.setattr(
        paper_trader, "DEFAULT_DATA_FILE", str(tmp_path / "data.json")
    )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(runs_store, "RUNS_DIR", str(runs_dir))
    monkeypatch.setattr(
        backtest, "OUTPUT_FILE", str(tmp_path / "backtest.json")
    )

    # Also redirect the profile store so dashboard/profile tests never
    # mutate the real profiles/ directory. Set via env var (the module
    # reads it at import) AND via direct attribute override for code
    # that's already imported.
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("TDX_PROFILES_DIR", str(profiles_dir))
    try:
        import profiles as profile_store
        monkeypatch.setattr(
            profile_store, "PROFILES_DIR", str(profiles_dir)
        )
    except ImportError:
        # profiles.py isn't on sys.path for a subset of tests; that's fine.
        pass


def _ohlcv_frame(closes: Iterable[float], start_ts: int = 1700000000) -> pd.DataFrame:
    """Wrap a sequence of closes into a minimal OHLCV DataFrame.

    All bars are flat (open=high=low=close) unless the caller wants to
    introduce wicks — tests that care about wicks build their own frame.
    """
    closes = list(closes)
    n = len(closes)
    idx = pd.date_range(
        start=pd.Timestamp(start_ts, unit="s", tz="UTC"),
        periods=n,
        freq="1h",
    )
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * n,
        }
    )


@pytest.fixture
def ohlcv():
    """Factory that builds minimal OHLCV frames from a list of closes."""
    return _ohlcv_frame


@pytest.fixture
def sine_ohlcv():
    """A deterministic oscillating series useful for mean-reversion tests.

    It alternates above / below 100 so RSI, EMAs and Donchian channels all
    have something to crunch on, without being so extreme that tests become
    brittle to small indicator tweaks.
    """
    n = 300
    t = np.linspace(0, 12 * np.pi, n)
    closes = 100.0 + 5.0 * np.sin(t) + 0.01 * t  # gentle drift + oscillation
    return _ohlcv_frame(closes)


@pytest.fixture
def trending_up_ohlcv():
    """A clean uptrend: good for exercising stop-loss and trend-filter logic."""
    n = 300
    closes = np.linspace(100.0, 150.0, n)
    return _ohlcv_frame(closes)


@pytest.fixture
def fresh_params():
    """A Params() with sensible, deterministic defaults for tests."""
    from backtest import Params
    return Params(
        bars=200,
        initial_balance=1000.0,
        allocation_pct=1.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        fee_pct=0.0,
        entry_cooldown_bars=0,
    )
