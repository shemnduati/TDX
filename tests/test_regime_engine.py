from __future__ import annotations

import pandas as pd
import pytest

from backtest import Params, apply_full_indicators, replay_on_df
from regime import (
    SESSIONS,
    _classify_session,
    attach_regime_columns,
    attach_session_columns,
    strategy_regime_expectancy,
    strategy_session_expectancy,
)


def test_attach_regime_columns_adds_expected_fields(sine_ohlcv):
    out = attach_regime_columns(sine_ohlcv.copy())
    for k in ("regime_trend", "regime_vol", "regime_micro", "regime"):
        assert k in out.columns
    assert out["regime"].astype(str).str.contains(r"\|").any()


def test_classify_session_covers_all_buckets():
    """Every UTC hour should map to one of the five known sessions."""
    seen = set()
    for h in range(24):
        ts = pd.Timestamp(f"2024-01-01 {h:02d}:00:00", tz="UTC")
        s = _classify_session(ts)
        assert s in SESSIONS, f"hour {h} gave unknown session {s!r}"
        seen.add(s)
    assert seen == set(SESSIONS), "Not all session buckets were hit"


@pytest.mark.parametrize(
    "hour,expected",
    [(0, "asia"), (6, "asia"), (7, "london"), (12, "london"),
     (13, "overlap"), (15, "overlap"), (16, "ny"), (21, "ny"),
     (22, "off"), (23, "off")],
)
def test_classify_session_hour_boundaries(hour, expected):
    ts = pd.Timestamp(f"2024-01-01 {hour:02d}:30:00", tz="UTC")
    assert _classify_session(ts) == expected


def test_attach_session_columns_buckets_match_hour_boundaries(sine_ohlcv):
    """attach_session_columns produces session values consistent with UTC hours."""
    out = attach_session_columns(sine_ohlcv.copy())
    assert "session" in out.columns
    assert "is_weekend" in out.columns
    # Spot-check: re-classify manually and compare
    for _, row in out.iterrows():
        ts = pd.to_datetime(row["timestamp"], utc=True)
        expected = _classify_session(ts)
        assert row["session"] == expected, f"Mismatch at ts={ts}: got {row['session']}"


def test_attach_session_columns_marks_weekend():
    """Weekend flag must be True on Sat/Sun, False on weekdays."""
    dates = pd.date_range("2024-01-01", periods=7, freq="D", tz="UTC")  # Mon–Sun
    df = pd.DataFrame({
        "timestamp": dates,
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
    })
    out = attach_session_columns(df)
    for _, row in out.iterrows():
        ts = pd.to_datetime(row["timestamp"], utc=True)
        is_wkend = ts.dayofweek >= 5
        assert row["is_weekend"] == is_wkend, f"Bad weekend flag at {ts}"


def test_strategy_session_expectancy_returns_rows(sine_ohlcv):
    p = Params(
        strategy="rsi_mean_reversion",
        bars=300,
        fee_pct=0.0,
        use_atr_sizing=False,
    )
    out = strategy_session_expectancy(
        base_params=p,
        strategy_names=["rsi_mean_reversion", "ema_crossover"],
        df_raw=sine_ohlcv.copy(),
        apply_full_indicators_fn=apply_full_indicators,
        replay_on_df_fn=replay_on_df,
    )
    assert out["strategies"] == ["ema_crossover", "rsi_mean_reversion"]
    assert isinstance(out["sessions"], list)
    assert isinstance(out["rows"], list)
    if out["rows"]:
        row = out["rows"][0]
        assert "strategy" in row
        assert "session" in row
        assert "expectancy_pct" in row


def test_strategy_session_expectancy_weekend_split(sine_ohlcv):
    p = Params(strategy="ema_crossover", bars=300, fee_pct=0.0)
    out = strategy_session_expectancy(
        base_params=p,
        strategy_names=["ema_crossover"],
        df_raw=sine_ohlcv.copy(),
        apply_full_indicators_fn=apply_full_indicators,
        replay_on_df_fn=replay_on_df,
        weekend_split=True,
    )
    assert out["weekend_split"] is True
    # With weekend_split, session keys should contain "|"
    for row in out["rows"]:
        assert "|" in row["session"], f"Expected 'session|weekday' format, got {row['session']!r}"


def test_strategy_regime_expectancy_returns_rows(sine_ohlcv):
    p = Params(
        strategy="rsi_mean_reversion",
        bars=300,
        fee_pct=0.0,
        use_atr_sizing=False,
    )
    out = strategy_regime_expectancy(
        base_params=p,
        strategy_names=["rsi_mean_reversion", "ema_crossover"],
        df_raw=sine_ohlcv.copy(),
        apply_full_indicators_fn=apply_full_indicators,
        replay_on_df_fn=replay_on_df,
    )
    assert out["strategies"] == ["ema_crossover", "rsi_mean_reversion"]
    assert isinstance(out["regimes"], list)
    assert isinstance(out["rows"], list)
    if out["rows"]:
        row = out["rows"][0]
        assert "strategy" in row
        assert "regime" in row
        assert "expectancy_pct" in row
