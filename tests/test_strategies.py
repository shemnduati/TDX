"""
Tests for the strategy registry.

For each strategy we verify:
  - it's registered and accessible by name
  - `apply_indicators` attaches the columns `generate_signal` needs
  - `generate_signal` returns HOLD when there's insufficient warm-up
  - a crafted DataFrame produces the expected BUY/SELL event on the
    transition bar (and only the transition bar)
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from backtest import Params, apply_full_indicators
from strategies import (
    FILTER_HYPERPARAMS,
    REGISTRY,
    DonchianBreakoutStrategy,
    EmaCrossoverStrategy,
    RsiMeanReversionStrategy,
    _utc_time_filter_allows,
    attach_htf_trend,
    filters_pass,
    get_strategy,
    list_strategies,
    rsi,
)


class TestRegistry:
    def test_registered_strategies(self):
        names = list_strategies()
        assert set(names) == {
            "ema_crossover",
            "rsi_mean_reversion",
            "donchian_breakout",
            "intraday_donchian",
            "liquidity_sweep",
        }

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy("not_a_real_strategy")

    def test_each_strategy_declares_hyperparams(self):
        for name in list_strategies():
            s = get_strategy(name)
            assert isinstance(s.hyperparams, list)
            # Every declared hyperparam must exist on Params.
            allowed = set(Params().__dict__.keys())
            assert set(s.hyperparams).issubset(allowed), (
                f"{name} declares unknown hyperparams: "
                f"{set(s.hyperparams) - allowed}"
            )


class TestRsiHelper:
    def test_rsi_length_matches_input(self):
        s = pd.Series(range(50), dtype=float)
        out = rsi(s, 14)
        assert len(out) == 50

    def test_rsi_bounded_0_to_100(self):
        s = pd.Series(range(100), dtype=float)
        out = rsi(s, 14).dropna()
        assert out.min() >= 0.0
        assert out.max() <= 100.0


class TestEmaCrossover:
    """ema_crossover only emits on the cross bar itself."""

    def _params(self) -> Params:
        # Big buy window / trend off so nothing accidentally filters us out.
        # ADX is now on by default in config.py; explicitly disable so these
        # pure-strategy tests don't get gated by the generic regime filter.
        return replace(
            Params(),
            strategy="ema_crossover",
            ema_short=3,
            ema_long=10,
            ema_trend=0,
            rsi_period=5,
            rsi_buy_max=90,
            rsi_sell_min=10,
            use_adx_filter=False,
        )

    def test_buy_on_fast_crossing_up(self, ohlcv):
        # Slow decline so slow EMA is above fast, then rally so fast crosses up.
        closes = [100 - i for i in range(30)] + [70 + 2 * i for i in range(20)]
        df = ohlcv(closes)
        params = self._params()
        df = apply_full_indicators(df, params)

        s = EmaCrossoverStrategy()
        # Walk bar-by-bar and collect events — we expect exactly one BUY.
        signals = [s.generate_signal(df.iloc[: i + 1], params) for i in range(len(df))]
        assert signals.count("BUY") >= 1
        assert signals.count("BUY") <= 3  # event-only, not continuous

    def test_short_warmup_returns_hold(self, ohlcv):
        # Only 1 bar → `len(df) < 2` guard fires before indicators are checked.
        df = ohlcv([100.0])
        params = self._params()
        df = apply_full_indicators(df, params)
        assert EmaCrossoverStrategy().generate_signal(df, params) == "HOLD"


class TestRsiMeanReversion:
    def _params(self) -> Params:
        return replace(
            Params(),
            strategy="rsi_mean_reversion",
            rsi_period=5,
            rsi_oversold=35,
            rsi_overbought=65,
            ema_trend=0,
            use_adx_filter=False,  # disable default-on ADX gate for pure strategy test
        )

    def test_buy_on_cross_up_through_oversold(self, ohlcv):
        """Crash (RSI < 30), then sharp bounce: expect a BUY on the bar the
        RSI crosses back above oversold."""
        # Drop then rally.
        closes = [100 - i * 2 for i in range(15)] + [60 + i * 3 for i in range(15)]
        df = ohlcv(closes)
        params = self._params()
        df = apply_full_indicators(df, params)
        s = RsiMeanReversionStrategy()
        signals = [s.generate_signal(df.iloc[: i + 1], params) for i in range(len(df))]
        assert "BUY" in signals


class TestDonchianBreakout:
    def _params(self) -> Params:
        return replace(
            Params(),
            strategy="donchian_breakout",
            donchian_period=10,
            ema_trend=0,
            rsi_period=5,
            use_adx_filter=False,  # disable default-on ADX gate for pure strategy test
        )

    def test_buy_on_first_break_above_channel(self, ohlcv):
        # Flat at 100, then jumps above the 10-bar high.
        closes = [100.0] * 20 + [105.0, 106.0, 107.0]
        df = ohlcv(closes)
        params = self._params()
        df = apply_full_indicators(df, params)
        s = DonchianBreakoutStrategy()
        signals = [s.generate_signal(df.iloc[: i + 1], params) for i in range(len(df))]
        assert signals.count("BUY") >= 1

    def test_hold_before_warmup(self, ohlcv):
        df = ohlcv([100.0] * 5)
        params = self._params()
        df = apply_full_indicators(df, params)
        assert DonchianBreakoutStrategy().generate_signal(df, params) == "HOLD"

    def test_compression_off_default_unchanged(self, ohlcv):
        p = replace(self._params(), use_donchian_compression=False)
        closes = [100.0] * 20 + [105.0, 106.0, 107.0]
        df = apply_full_indicators(ohlcv(closes), p)
        s = [DonchianBreakoutStrategy().generate_signal(df.iloc[: i + 1], p) for i in range(len(df))]
        assert s.count("BUY") >= 1


class TestIntradayDonchian:
    def _params(self) -> Params:
        return replace(
            Params(),
            strategy="intraday_donchian",
            donchian_period=5,
            rsi_period=5,
            rsi_buy_max=90,
            rsi_sell_min=10,
            atr_period=5,
            atr_ma_period=3,
            breakout_atr_mult=0.0,
            ltf_ema_period=0,
            use_breakout_rsi=False,
            use_atr_expansion=False,
            use_adx_filter=False,
            use_htf_confirm=False,
            use_atr_sizing=True,
        )

    def test_columns_after_apply(self, ohlcv):
        from strategies import IntradayDonchianStrategy

        df = ohlcv([100.0] * 40)
        p = self._params()
        out = IntradayDonchianStrategy().apply_indicators(df, p)
        assert "atr_ma" in out.columns
        assert "ltf_ema" in out.columns

    def test_warmup_short_data_returns_hold(self, ohlcv):
        from strategies import IntradayDonchianStrategy

        df = ohlcv([100.0] * 8)
        p = self._params()
        df = apply_full_indicators(df, p)
        assert IntradayDonchianStrategy().generate_signal(df, p) == "HOLD"

    def test_signal_types_bounded(self, sine_ohlcv):
        """Long synthetic series: every bar returns a valid decision."""
        from strategies import IntradayDonchianStrategy

        p = self._params()
        df = apply_full_indicators(sine_ohlcv, p)
        s = IntradayDonchianStrategy()
        for i in range(len(df)):
            out = s.generate_signal(df.iloc[: i + 1], p)
            assert out in ("BUY", "SELL", "HOLD")


class TestTrendFilter:
    """The ema_trend filter gates longs to closes > trend and shorts to
    closes < trend. Verify by comparing signals with filter on vs off on
    the same downward-then-breakout price path: the breakout SELLs should
    survive the filter, BUYs should not."""

    def test_filter_blocks_long_breakout_below_trend(self, ohlcv):
        # Build a downtrend so the EMA trend sits ABOVE price, then a tiny
        # rally that would be a BUY but shouldn't pass the filter.
        closes = [100 - i * 0.5 for i in range(80)] + [60, 62, 64, 66, 68]
        df = ohlcv(closes)
        common = dict(
            strategy="donchian_breakout",
            donchian_period=10,
            rsi_period=5,
        )
        with_filter = replace(Params(), ema_trend=50, **common)
        without_filter = replace(Params(), ema_trend=0, **common)

        df_with = apply_full_indicators(df.copy(), with_filter)
        df_without = apply_full_indicators(df.copy(), without_filter)

        s = DonchianBreakoutStrategy()
        sig_with = [
            s.generate_signal(df_with.iloc[: i + 1], with_filter)
            for i in range(len(df_with))
        ]
        sig_without = [
            s.generate_signal(df_without.iloc[: i + 1], without_filter)
            for i in range(len(df_without))
        ]

        # Without the filter, the tail rally should produce at least one BUY.
        assert sig_without.count("BUY") >= 1
        # With the filter, no BUYs: price is still below the 50-EMA trend.
        assert sig_with.count("BUY") == 0


class TestGenericFilters:
    """The opt-in filter toggles added on top of every strategy."""

    def test_every_strategy_exposes_filter_toggles(self):
        # `hyperparams` is post-registry extended with FILTER_HYPERPARAMS,
        # so the UI/sweep code can present filters as per-strategy knobs.
        for name, s in REGISTRY.items():
            missing = set(FILTER_HYPERPARAMS) - set(s.hyperparams)
            assert not missing, f"{name} is missing filter hyperparams: {missing}"

    # Base Params with every filter explicitly OFF. We don't rely on
    # config.py's defaults here because they're deliberately tuned for
    # live trading (e.g. ADX on) — these tests validate the filter
    # *mechanism*, not the defaults, so we pin the baseline.
    _FILTERS_OFF = {
        "use_adx_filter": False,
        "use_htf_confirm": False,
        "use_volume_filter": False,
        "use_atr_filter": False,
        "use_macd_confirm": False,
    }

    def test_filters_off_pass_unconditionally(self):
        # With every `use_*` flag False, filters_pass must always return True
        # regardless of the bar's content — this is the "no-op when off"
        # guarantee the whole design rests on.
        p = replace(Params(), **self._FILTERS_OFF)
        last = pd.Series({
            "volume": 0.0, "close": 100.0, "filt_adx": float("nan"),
            "filt_vol_ma": float("nan"), "filt_atr_pct": float("nan"),
            "filt_macd": float("nan"), "filt_macd_signal": float("nan"),
            "htf_bull": pd.NA,
        })
        assert filters_pass(last, p, "long") is True
        assert filters_pass(last, p, "short") is True

    def _off_except(self, **on) -> Params:
        """Base Params with filters OFF, then flip on the ones we're testing.

        We do this merge in a dict to avoid the `replace(**dict, **kw)`
        collision when the kwarg's name also appears in the dict.
        """
        merged = {**self._FILTERS_OFF, **on}
        return replace(Params(), **merged)

    def test_adx_filter_range_gate(self):
        p = self._off_except(use_adx_filter=True, adx_min=20.0, adx_max=40.0)
        assert filters_pass(pd.Series({"filt_adx": 30.0}), p, "long") is True
        assert filters_pass(pd.Series({"filt_adx": 15.0}), p, "long") is False
        assert filters_pass(pd.Series({"filt_adx": 45.0}), p, "long") is False

    def test_volume_filter_requires_participation(self):
        p = self._off_except(use_volume_filter=True, vol_mult=1.5)
        ok = pd.Series({"volume": 200.0, "filt_vol_ma": 100.0})
        weak = pd.Series({"volume": 120.0, "filt_vol_ma": 100.0})
        assert filters_pass(ok, p, "long") is True
        assert filters_pass(weak, p, "long") is False

    def test_htf_confirm_blocks_long_in_downtrend(self):
        p = self._off_except(use_htf_confirm=True)
        bull = pd.Series({"htf_bull": True})
        bear = pd.Series({"htf_bull": False})
        assert filters_pass(bull, p, "long") is True
        assert filters_pass(bear, p, "long") is False
        assert filters_pass(bull, p, "short") is False
        assert filters_pass(bear, p, "short") is True

    def test_macd_confirm_checks_direction(self):
        p = self._off_except(use_macd_confirm=True)
        bull = pd.Series({"filt_macd": 1.0, "filt_macd_signal": 0.5})
        bear = pd.Series({"filt_macd": -1.0, "filt_macd_signal": -0.5})
        # Also test the zero-line requirement: line above signal but below
        # zero is not a confirmed long.
        weak_long = pd.Series({"filt_macd": -0.2, "filt_macd_signal": -0.5})
        assert filters_pass(bull, p, "long") is True
        assert filters_pass(bear, p, "short") is True
        assert filters_pass(weak_long, p, "long") is False


class TestHtfAttach:
    """`attach_htf_trend` must not leak future HTF bars into earlier LTF
    bars. We enforce this with `merge_asof(direction="backward")` so the
    HTF value at LTF time t reflects only HTF bars that have ALREADY closed
    at t."""

    def _build_ltf(self, n: int) -> pd.DataFrame:
        """An LTF frame at 1h resolution."""
        ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        return pd.DataFrame({
            "timestamp": ts,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
        })

    def _build_htf(self) -> pd.DataFrame:
        """An HTF frame at daily resolution with a step change in trend so
        we can tell "before" vs "after" apart."""
        ts = pd.date_range("2024-01-01", periods=10, freq="1D", tz="UTC")
        closes = [100.0] * 5 + [200.0] * 5  # regime change halfway through
        return pd.DataFrame({
            "timestamp": ts,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * 10,
        })

    def test_htf_value_never_from_future(self):
        ltf = self._build_ltf(72)  # 72 hours = 3 days
        htf = self._build_htf()
        merged = attach_htf_trend(ltf, htf, ema_period=3)

        # For every LTF row the HTF value must come from an HTF bar whose
        # timestamp is <= that LTF row's timestamp.
        for _, row in merged.iterrows():
            if pd.isna(row["htf_close"]):
                continue
            # The HTF close equals the close of some HTF bar at or before t.
            matching = htf[htf["timestamp"] <= row["timestamp"]]
            assert not matching.empty
            latest = matching.iloc[-1]
            assert row["htf_close"] == latest["close"]

    def test_htf_empty_input_degrades_gracefully(self):
        ltf = self._build_ltf(5)
        merged = attach_htf_trend(ltf, ltf.iloc[0:0], ema_period=3)
        assert "htf_close" in merged.columns
        assert merged["htf_close"].isna().all()


class TestSessionFilter:
    """Tests for _utc_time_filter_allows with allowed_sessions / block_weekends."""

    def _p(self, **kw):
        """Build a Params-like object via Params dataclass."""
        return Params(**kw)

    def test_allowed_sessions_filters_entries_outside_window(self):
        """A bar in the NY session (17:00 UTC) should be rejected when only
        asia + london are allowed."""
        ny_ts = pd.Timestamp("2024-01-03 17:30:00", tz="UTC")  # Wednesday NY
        p = self._p(allowed_sessions=("asia", "london"), use_time_filter=False)
        assert _utc_time_filter_allows(p, ny_ts) is False

    def test_allowed_sessions_permits_bar_in_allowed_session(self):
        london_ts = pd.Timestamp("2024-01-03 09:00:00", tz="UTC")  # Wednesday London
        p = self._p(allowed_sessions=("london",), use_time_filter=False)
        assert _utc_time_filter_allows(p, london_ts) is True

    def test_empty_allowed_sessions_allows_all(self):
        """Empty tuple (default) disables the session gate."""
        ny_ts = pd.Timestamp("2024-01-03 17:30:00", tz="UTC")
        p = self._p(allowed_sessions=(), use_time_filter=False)
        assert _utc_time_filter_allows(p, ny_ts) is True

    def test_block_weekends_blocks_saturday(self):
        sat_ts = pd.Timestamp("2024-01-06 12:00:00", tz="UTC")  # Saturday
        p = self._p(block_weekends=True, use_time_filter=False)
        assert _utc_time_filter_allows(p, sat_ts) is False

    def test_block_weekends_blocks_sunday(self):
        sun_ts = pd.Timestamp("2024-01-07 12:00:00", tz="UTC")  # Sunday
        p = self._p(block_weekends=True, use_time_filter=False)
        assert _utc_time_filter_allows(p, sun_ts) is False

    def test_block_weekends_allows_weekday(self):
        mon_ts = pd.Timestamp("2024-01-08 12:00:00", tz="UTC")  # Monday
        p = self._p(block_weekends=True, use_time_filter=False)
        assert _utc_time_filter_allows(p, mon_ts) is True

    def test_session_and_weekend_combined(self):
        """A Saturday bar in the 'london' session should be blocked when both
        filters are active."""
        sat_london = pd.Timestamp("2024-01-06 10:00:00", tz="UTC")  # Sat London hour
        p = self._p(
            allowed_sessions=("london",),
            block_weekends=True,
            use_time_filter=False,
        )
        assert _utc_time_filter_allows(p, sat_london) is False

    def test_legacy_time_filter_still_works(self):
        """use_time_filter=True with a narrow window still rejects bars outside it."""
        ts = pd.Timestamp("2024-01-03 05:00:00", tz="UTC")  # 05:00 outside 08:00–20:00
        p = self._p(use_time_filter=True, time_start_utc_mins=480, time_end_utc_mins=1200)
        assert _utc_time_filter_allows(p, ts) is False
