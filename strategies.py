"""
Strategy registry.

Each concrete Strategy is a stateless singleton that knows:
  - which indicators it needs (`apply_indicators`)
  - how many bars of warm-up are required before its indicators are valid
  - how to turn an OHLCV+indicator DataFrame into a BUY / SELL / HOLD signal

Strategies read their hyperparameters from the shared `Params` dataclass
defined in `backtest.py`. This keeps the wiring simple: one dataclass is
the source of truth for a whole backtest, and each strategy picks the
fields it cares about.

Add a new strategy in three steps:
  1. Subclass `Strategy`, implement `apply_indicators`, `generate_signal`,
     and `warmup_bars`.
  2. Add any new hyperparameters to `Params` in backtest.py.
  3. Register the instance in `REGISTRY` at the bottom of this file.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backtest import Params


# -------------------------------------------------------------- indicators --
def rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI via EMA of gains/losses."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - (100 / (1 + rs))).fillna(50)


def macd(
    series: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def wilder_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder ATR(period) as a float Series (same TR definition as `backtest._apply_atr`)."""
    p = max(int(period), 1)
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / p, adjust=False).mean()


def adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's Average Directional Index.

    ADX measures trend *strength* regardless of direction. By convention:
      <20 : no trend / ranging
      20-25: weak / emerging
      >25 : trending
      >40 : strong trend

    Used by the liquidity-sweep strategy as a regime gate — stop-hunt
    reversals only have edge in ranging conditions, so we refuse to trade
    when ADX signals a real trend is in progress.
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    alpha = 1 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    # Use NaN (not pd.NA) for divide-by-zero guards so the resulting Series
    # stays float64 — pandas' rolling/ewm operations refuse object dtype.
    nan = float("nan")
    safe_atr = atr_w.replace(0, nan)
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / safe_atr
    di_sum = (plus_di + minus_di).replace(0, nan)
    dx = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0.0)
    return dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)


# ------------------------------------------------------------------ base ---
class Strategy(ABC):
    name: str
    # Which Params fields this strategy actually reads. Used by the frontend
    # to show only the relevant knobs. Risk/market params (symbol, timeframe,
    # stop_loss_pct, etc.) are always editable and not listed here.
    hyperparams: list[str] = []

    @abstractmethod
    def apply_indicators(
        self, df: pd.DataFrame, params: "Params"
    ) -> pd.DataFrame: ...

    @abstractmethod
    def generate_signal(
        self, df: pd.DataFrame, params: "Params"
    ) -> str: ...

    @abstractmethod
    def warmup_bars(self, params: "Params") -> int: ...


# -------------------------------------------------------- ema_crossover ---
class EmaCrossoverStrategy(Strategy):
    """Trend-following: fast EMA crossing slow EMA, RSI anti-overshoot filter,
    EMA-trend regime filter. Signal fires on the actual cross event only."""

    name = "ema_crossover"
    hyperparams = [
        "ema_short",
        "ema_long",
        "ema_trend",
        "rsi_period",
        "rsi_buy_max",
        "rsi_sell_min",
    ]

    def apply_indicators(self, df, params):
        df = df.copy()
        df["ema_short"] = df["close"].ewm(
            span=params.ema_short, adjust=False
        ).mean()
        df["ema_long"] = df["close"].ewm(
            span=params.ema_long, adjust=False
        ).mean()
        df["rsi"] = rsi(df["close"], params.rsi_period)
        if params.ema_trend and params.ema_trend > 0:
            df["ema_trend"] = df["close"].ewm(
                span=params.ema_trend, adjust=False
            ).mean()
        else:
            df["ema_trend"] = pd.NA
        return df

    def warmup_bars(self, params):
        return max(
            params.ema_long,
            params.rsi_period,
            params.ema_trend or 0,
            filter_warmup_bars(params),
        ) + 2

    def generate_signal(self, df, params):
        if len(df) < 2:
            return "HOLD"
        prev, last = df.iloc[-2], df.iloc[-1]

        for col in ("ema_short", "ema_long", "rsi"):
            if pd.isna(prev.get(col)) or pd.isna(last.get(col)):
                return "HOLD"

        cross_up = (
            prev["ema_short"] <= prev["ema_long"]
            and last["ema_short"] > last["ema_long"]
        )
        cross_down = (
            prev["ema_short"] >= prev["ema_long"]
            and last["ema_short"] < last["ema_long"]
        )

        rsi_last = last["rsi"]
        ok_long, ok_short = _trend_ok(last, params)

        if (
            cross_up
            and rsi_last < params.rsi_buy_max
            and ok_long
            and filters_pass(last, params, "long")
        ):
            return "BUY"
        if (
            cross_down
            and rsi_last > params.rsi_sell_min
            and ok_short
            and filters_pass(last, params, "short")
        ):
            return "SELL"
        return "HOLD"


# --------------------------------------------------- rsi_mean_reversion ---
class RsiMeanReversionStrategy(Strategy):
    """Counter-trend mean reversion on RSI extremes.

    - BUY  on RSI crossing UP through `rsi_oversold` from below (bounce)
    - SELL on RSI crossing DOWN through `rsi_overbought` from above (rejection)

    The trend filter (optional, shared with EMA strategy) turns this into
    "buy the dip in uptrends, sell the rip in downtrends" — classic with-
    trend mean reversion.
    """

    name = "rsi_mean_reversion"
    hyperparams = [
        "rsi_period",
        "rsi_oversold",
        "rsi_overbought",
        "ema_trend",
        "mr_regime_adx_max",
    ]

    def apply_indicators(self, df, params):
        df = df.copy()
        df["rsi"] = rsi(df["close"], params.rsi_period)
        if params.ema_trend and params.ema_trend > 0:
            df["ema_trend"] = df["close"].ewm(
                span=params.ema_trend, adjust=False
            ).mean()
        else:
            df["ema_trend"] = pd.NA
        if params.mr_regime_adx_max and params.mr_regime_adx_max > 0:
            df["mr_adx"] = adx(df, params.filter_adx_period)
        else:
            df["mr_adx"] = pd.NA
        return df

    def warmup_bars(self, params):
        mrg = 0
        if params.mr_regime_adx_max and params.mr_regime_adx_max > 0:
            mrg = params.filter_adx_period * 3
        return max(
            params.rsi_period,
            params.ema_trend or 0,
            mrg,
            filter_warmup_bars(params),
        ) + 2

    def generate_signal(self, df, params):
        if len(df) < 2:
            return "HOLD"
        prev, last = df.iloc[-2], df.iloc[-1]
        if pd.isna(prev.get("rsi")) or pd.isna(last.get("rsi")):
            return "HOLD"

        cross_up_oversold = (
            prev["rsi"] <= params.rsi_oversold
            and last["rsi"] > params.rsi_oversold
        )
        cross_down_overbought = (
            prev["rsi"] >= params.rsi_overbought
            and last["rsi"] < params.rsi_overbought
        )

        if params.mr_regime_adx_max and params.mr_regime_adx_max > 0:
            mx = last.get("mr_adx")
            if pd.isna(mx) or float(mx) >= float(params.mr_regime_adx_max):
                return "HOLD"

        ok_long, ok_short = _trend_ok(last, params)

        if cross_up_oversold and ok_long and filters_pass(last, params, "long"):
            return "BUY"
        if (
            cross_down_overbought
            and ok_short
            and filters_pass(last, params, "short")
        ):
            return "SELL"
        return "HOLD"


# ------------------------------------------------------ donchian_breakout -
class DonchianBreakoutStrategy(Strategy):
    """Classic Donchian channel breakout.

    - BUY  when the close first breaks above the rolling N-bar high
           (computed over the previous N bars, not including the current).
    - SELL when the close first breaks below the rolling N-bar low.

    The "first" part matters: we only fire on the bar that transitions from
    "inside channel" to "outside channel", so a sustained trend produces one
    entry signal, not one per bar.

    The optional trend filter still applies — longs only above `ema_trend`,
    shorts only below. Disable with `ema_trend=0` for pure breakout.

    Optional `use_donchian_compression`: require a quiet period first — the
    mean bar range over the prior L bars must be <= k×ATR before a breakout
    counts (skip "late" breaks in already-wide markets).

    Optional `use_donchian_rsi` + `rsi_buy_max` / `rsi_sell_min`: skip longs
    when RSI is already stretched above the buy cap, and shorts when RSI
    is below the sell floor (anti-chase).
    """

    name = "donchian_breakout"
    hyperparams = [
        "donchian_period",
        "ema_trend",
        "use_donchian_rsi",
        "rsi_buy_max",
        "rsi_sell_min",
        "use_donchian_compression",
        "donchian_compression_lookback",
        "donchian_compression_max_range_atr",
    ]

    def apply_indicators(self, df, params):
        df = df.copy()
        n = params.donchian_period
        # Shifted so the channel at bar t reflects bars [t-N, t-1], making
        # the current bar's close a meaningful "breaks the channel" test.
        df["donchian_high"] = df["high"].rolling(n).max().shift(1)
        df["donchian_low"] = df["low"].rolling(n).min().shift(1)
        if params.ema_trend and params.ema_trend > 0:
            df["ema_trend"] = df["close"].ewm(
                span=params.ema_trend, adjust=False
            ).mean()
        else:
            df["ema_trend"] = pd.NA
        # RSI kept for consistency (other code expects the column to exist).
        df["rsi"] = rsi(df["close"], params.rsi_period)
        if params.use_donchian_compression:
            p_atr = max(int(params.atr_period), 1)
            df["dc_atr"] = wilder_atr(df, p_atr)
            Lc = max(int(params.donchian_compression_lookback), 1)
            br = (df["high"] - df["low"]).abs()
            # Mean range over the Lc bars *before* t (exclude signal bar).
            df["dc_prior_mean_range"] = br.rolling(Lc).mean().shift(1)
        else:
            df["dc_atr"] = pd.NA
            df["dc_prior_mean_range"] = pd.NA
        return df

    def warmup_bars(self, params):
        # +1 because of the .shift(1) above.
        comp = 0
        if params.use_donchian_compression:
            comp = max(
                params.donchian_compression_lookback + 1,
                params.atr_period + 2,
            )
        return max(
            params.donchian_period + 1,
            params.rsi_period,
            params.ema_trend or 0,
            comp,
            filter_warmup_bars(params),
        ) + 2

    def generate_signal(self, df, params):
        if len(df) < 2:
            return "HOLD"
        prev, last = df.iloc[-2], df.iloc[-1]
        for col in ("donchian_high", "donchian_low"):
            if pd.isna(prev.get(col)) or pd.isna(last.get(col)):
                return "HOLD"

        break_up = (
            prev["close"] <= prev["donchian_high"]
            and last["close"] > last["donchian_high"]
        )
        break_down = (
            prev["close"] >= prev["donchian_low"]
            and last["close"] < last["donchian_low"]
        )

        comp_ok = self._compression_passes(last, params)
        ok_long, ok_short = _trend_ok(last, params)

        long_ok = (
            break_up
            and comp_ok
            and ok_long
            and filters_pass(last, params, "long")
        )
        if long_ok and params.use_donchian_rsi:
            r = last.get("rsi")
            if pd.isna(r) or not (float(r) < params.rsi_buy_max):
                long_ok = False
        if long_ok:
            return "BUY"

        short_ok = (
            break_down
            and comp_ok
            and ok_short
            and filters_pass(last, params, "short")
        )
        if short_ok and params.use_donchian_rsi:
            r = last.get("rsi")
            if pd.isna(r) or not (float(r) > params.rsi_sell_min):
                short_ok = False
        if short_ok:
            return "SELL"
        return "HOLD"

    def _compression_passes(self, last, params) -> bool:
        """True when prior mean range is not wider than k×ATR (optional gate)."""
        if not params.use_donchian_compression:
            return True
        mr = last.get("dc_prior_mean_range")
        a = last.get("dc_atr")
        k = float(params.donchian_compression_max_range_atr)
        if pd.isna(mr) or pd.isna(a) or a <= 0.0 or k <= 0.0:
            return False
        return float(mr) <= k * float(a)


# ---------------------------------------------------- intraday_donchian ----
class IntradayDonchianStrategy(Strategy):
    """HTF trend (opt-in: `use_htf_confirm` + 1h EMA) + LTF Donchian breakout
    with ATR regime and strength filters. Intended for 5m/15m entries vs
    1h regime.

    Entry (long, symmetric for short):
      - First close through shifted Donchian high / low (no repeat entries).
      - ATR > rolling mean of ATR (volatility "alive").
      - Breakout distance beyond the channel >= `breakout_atr_mult` * ATR.
      - Optional: ATR increasing vs prior bar, RSI not extreme, LTF EMA
        alignment.

    Use `use_atr_sizing=True` in Params so SL/TP and size use ATR (e.g. stop
    2*ATR, take 4*ATR for 1:2 R:R with default mults).
    """

    name = "intraday_donchian"
    hyperparams = [
        "donchian_period",
        "rsi_period",
        "rsi_buy_max",
        "rsi_sell_min",
        "atr_period",
        "atr_ma_period",
        "breakout_atr_mult",
        "ltf_ema_period",
        "use_breakout_rsi",
        "use_atr_expansion",
    ]

    def apply_indicators(self, df, params):
        df = df.copy()
        n = params.donchian_period
        df["donchian_high"] = df["high"].rolling(n).max().shift(1)
        df["donchian_low"] = df["low"].rolling(n).min().shift(1)
        df["rsi"] = rsi(df["close"], params.rsi_period)
        p_atr = max(params.atr_period, 1)
        df["atr"] = wilder_atr(df, p_atr)
        ma = max(params.atr_ma_period, 1)
        df["atr_ma"] = df["atr"].rolling(ma).mean()
        if params.ltf_ema_period and params.ltf_ema_period > 0:
            df["ltf_ema"] = df["close"].ewm(
                span=int(params.ltf_ema_period), adjust=False
            ).mean()
        else:
            df["ltf_ema"] = pd.NA
        return df

    def warmup_bars(self, params):
        return max(
            params.donchian_period + 1,
            params.rsi_period,
            params.atr_period + 2,
            params.atr_ma_period,
            params.ltf_ema_period or 0,
            filter_warmup_bars(params),
        ) + 2

    def generate_signal(self, df, params):
        if len(df) < 2:
            return "HOLD"
        prev, last = df.iloc[-2], df.iloc[-1]
        for col in (
            "donchian_high",
            "donchian_low",
            "atr",
            "atr_ma",
            "rsi",
        ):
            if pd.isna(prev.get(col)) or pd.isna(last.get(col)):
                return "HOLD"

        break_up = (
            prev["close"] <= prev["donchian_high"]
            and last["close"] > last["donchian_high"]
        )
        break_down = (
            prev["close"] >= prev["donchian_low"]
            and last["close"] < last["donchian_low"]
        )

        if not (last["atr"] > last["atr_ma"]):
            return "HOLD"

        mult = float(params.breakout_atr_mult)
        if break_up:
            ext = last["close"] - last["donchian_high"]
            if ext < mult * last["atr"]:
                return "HOLD"
        elif break_down:
            ext = last["donchian_low"] - last["close"]
            if ext < mult * last["atr"]:
                return "HOLD"
        else:
            return "HOLD"

        if params.use_atr_expansion:
            pa = prev.get("atr")
            if pd.isna(pa) or not (last["atr"] > pa):
                return "HOLD"

        if params.ltf_ema_period and params.ltf_ema_period > 0:
            ema = last.get("ltf_ema")
            if pd.isna(ema):
                return "HOLD"
            if break_up and not (last["close"] > ema):
                return "HOLD"
            if break_down and not (last["close"] < ema):
                return "HOLD"

        if params.use_breakout_rsi:
            r = last["rsi"]
            if break_up and not (r < params.rsi_buy_max):
                return "HOLD"
            if break_down and not (r > params.rsi_sell_min):
                return "HOLD"

        if break_up and filters_pass(last, params, "long"):
            return "BUY"
        if break_down and filters_pass(last, params, "short"):
            return "SELL"
        return "HOLD"


# ---------------------------------------------------- liquidity_sweep ----
class LiquiditySweepStrategy(Strategy):
    """Fade failed breakouts of prior swing highs / lows.

    Economic hypothesis: retail stop-losses cluster just above recent highs
    and just below recent lows. Size players push price through these
    clusters to trigger the stops and harvest the liquidity; once the forced
    flow exhausts, price reverts. We enter on the rejection bar and ride
    the reversion.

    Entry rules (on the latest closed bar):
      Bearish sweep (SHORT)
        - bar.high   > prior N-bar swing high  (took out the highs)
        - bar.close  < prior N-bar swing high  (failed to hold above)
        - bar.close  < bar.open                (closed red = rejection)
        - bar.volume > mult × rolling median   (a real sweep, not a drift)
        - ADX        < adx_max                 (ranging regime only)

      Bullish sweep (LONG) is the exact mirror.

    SL/TP are left to the replay layer: run with USE_ATR_SIZING=True to get
    ATR-normalized stops (recommended — wick-based risk fits the mechanism),
    or with fixed pct SL/TP for a simpler first test.
    """

    name = "liquidity_sweep"
    hyperparams = [
        "sweep_lookback",
        "sweep_adx_period",
        "sweep_adx_max",
        "sweep_volume_mult",
        "sweep_volume_lookback",
    ]

    def apply_indicators(self, df, params):
        df = df.copy()
        n = params.sweep_lookback
        # .shift(1) so the swing high at bar t reflects bars [t-N, t-1], making
        # the current bar's wick a meaningful "did it poke above?" test.
        df["sweep_high"] = df["high"].rolling(n).max().shift(1)
        df["sweep_low"] = df["low"].rolling(n).min().shift(1)
        df["adx"] = adx(df, params.sweep_adx_period)
        # Median of prior bars only; current bar's volume is not in the window.
        df["vol_median"] = (
            df["volume"].shift(1).rolling(params.sweep_volume_lookback).median()
        )
        # RSI kept only so replay_on_df's "has this df been indicator'd?"
        # sentinel check (looks for an "rsi" column) passes cleanly.
        df["rsi"] = rsi(df["close"], params.rsi_period)
        return df

    def warmup_bars(self, params):
        # ADX needs ~3× period to stabilize under Wilder smoothing.
        return max(
            params.sweep_lookback + 1,
            params.sweep_adx_period * 3,
            params.sweep_volume_lookback,
            params.rsi_period,
            filter_warmup_bars(params),
        ) + 2

    def generate_signal(self, df, params):
        if len(df) < 2:
            return "HOLD"
        last = df.iloc[-1]

        for col in ("sweep_high", "sweep_low", "adx", "vol_median"):
            if pd.isna(last.get(col)):
                return "HOLD"

        if params.sweep_adx_max > 0 and last["adx"] >= params.sweep_adx_max:
            return "HOLD"

        median_vol = last["vol_median"]
        if median_vol <= 0 or pd.isna(median_vol):
            return "HOLD"
        if last["volume"] < params.sweep_volume_mult * median_vol:
            return "HOLD"

        bearish_sweep = (
            last["high"] > last["sweep_high"]
            and last["close"] < last["sweep_high"]
            and last["close"] < last["open"]
        )
        bullish_sweep = (
            last["low"] < last["sweep_low"]
            and last["close"] > last["sweep_low"]
            and last["close"] > last["open"]
        )

        if bearish_sweep and filters_pass(last, params, "short"):
            return "SELL"
        if bullish_sweep and filters_pass(last, params, "long"):
            return "BUY"
        return "HOLD"


# ------------------------------------------------------ generic filters --
# Everything below is opt-in. A strategy with every `use_*` flag False is
# indistinguishable from one that doesn't know filters exist. See
# config.py for the default-off rationale.

FILTER_HYPERPARAMS: list[str] = [
    "use_htf_confirm",
    "htf_timeframe",
    "htf_ema_period",
    "use_adx_filter",
    "filter_adx_period",
    "adx_min",
    "adx_max",
    "use_volume_filter",
    "vol_ma_period",
    "vol_mult",
    "use_atr_filter",
    "atr_min_pct",
    "use_atr_max_filter",
    "atr_max_pct",
    "use_time_filter",
    "time_start_utc_mins",
    "time_end_utc_mins",
    "use_macd_confirm",
    "macd_fast",
    "macd_slow",
    "macd_signal",
]


def _utc_time_filter_allows(params, ts) -> bool:
    """True if the bar's UTC time-of-day is inside the allowed window."""
    if not params.use_time_filter:
        return True
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return True
    t = pd.Timestamp(ts)
    if t.tz is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    m = t.hour * 60 + t.minute
    a, b = int(params.time_start_utc_mins) % 1440, int(params.time_end_utc_mins) % 1440
    if a < b:
        return a <= m < b
    if a > b:
        return m >= a or m < b
    return True


def attach_filter_indicators(df: pd.DataFrame, params) -> pd.DataFrame:
    """Attach every filter indicator whose toggle is on.

    Columns are prefixed `filt_` so they never collide with strategy-owned
    columns (liquidity_sweep has its own `adx`, for example).
    """
    df = df.copy()
    if params.use_adx_filter:
        df["filt_adx"] = adx(df, params.filter_adx_period)
    if params.use_volume_filter:
        df["filt_vol_ma"] = (
            df["volume"].rolling(params.vol_ma_period).median()
        )
    if params.use_atr_filter or params.use_atr_max_filter:
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - close_prev).abs(),
                (low - close_prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_series = tr.ewm(alpha=1 / max(params.atr_period, 1),
                            adjust=False).mean()
        df["filt_atr_pct"] = (atr_series / df["close"]).fillna(0.0)
    if params.use_macd_confirm:
        line, sig, hist = macd(
            df["close"], params.macd_fast, params.macd_slow,
            params.macd_signal,
        )
        df["filt_macd"] = line
        df["filt_macd_signal"] = sig
        df["filt_macd_hist"] = hist
    return df


def attach_htf_trend(
    ltf: pd.DataFrame, htf: pd.DataFrame, ema_period: int
) -> pd.DataFrame:
    """Merge an htf trend (close vs EMA) onto the ltf frame without
    look-ahead. The HTF value at LTF bar t is the last HTF bar that has
    *already closed* at or before t (direction="backward" in merge_asof).

    Adds columns `htf_close`, `htf_ema`, `htf_bull`. If the HTF frame is
    empty or the timeframes don't overlap, the columns are present but NaN
    so downstream code can skip safely.
    """
    if len(htf) == 0 or len(ltf) == 0:
        out = ltf.copy()
        out["htf_close"] = float("nan")
        out["htf_ema"] = float("nan")
        out["htf_bull"] = pd.NA
        return out

    h = htf[["timestamp", "close"]].copy()
    h["htf_ema"] = h["close"].ewm(span=ema_period, adjust=False).mean()
    h = h.rename(columns={"close": "htf_close"}).sort_values("timestamp")

    # `merge_asof` requires both sides sorted by the join key. Our LTF
    # frames (built by `format_data`) are already timestamp-sorted, so we
    # don't reorder here — the caller gets rows back in LTF input order.
    merged = pd.merge_asof(
        ltf.sort_values("timestamp").reset_index(drop=True),
        h,
        on="timestamp",
        direction="backward",
    )
    merged["htf_bull"] = merged["htf_close"] > merged["htf_ema"]
    return merged


def filter_warmup_bars(params) -> int:
    """Extra bars of warm-up required by whichever filters are enabled."""
    need = 0
    if params.use_adx_filter:
        need = max(need, params.filter_adx_period * 3)
    if params.use_volume_filter:
        need = max(need, params.vol_ma_period)
    if params.use_atr_filter or params.use_atr_max_filter:
        need = max(need, params.atr_period + 2)
    if params.use_macd_confirm:
        need = max(need, params.macd_slow + params.macd_signal + 2)
    # HTF has its own warm-up but it's enforced at fetch time, so no LTF
    # bar budget is needed here.
    return need


def _filter_gate_ok(last, params, side: str) -> bool:
    """Return False when ANY enabled filter vetoes the signal.

    side: "long" or "short". Filters that care about direction (HTF trend,
    MACD) check the side; symmetric filters (ADX, volume, ATR) ignore it.
    """
    if params.use_time_filter:
        if not _utc_time_filter_allows(params, last.get("timestamp")):
            return False

    if params.use_htf_confirm:
        htf_bull = last.get("htf_bull")
        if pd.isna(htf_bull):
            return False  # no HTF data yet: refuse to trade blind
        if side == "long" and not bool(htf_bull):
            return False
        if side == "short" and bool(htf_bull):
            return False

    if params.use_adx_filter:
        a = last.get("filt_adx")
        if pd.isna(a):
            return False
        if params.adx_min > 0 and a <= params.adx_min:
            return False
        if params.adx_max > 0 and a >= params.adx_max:
            return False

    if params.use_volume_filter:
        vma = last.get("filt_vol_ma")
        vol = last.get("volume")
        if pd.isna(vma) or pd.isna(vol) or vma <= 0:
            return False
        if vol < params.vol_mult * vma:
            return False

    if params.use_atr_filter:
        atr_pct = last.get("filt_atr_pct")
        if pd.isna(atr_pct):
            return False
        if atr_pct < params.atr_min_pct:
            return False

    if params.use_atr_max_filter and params.atr_max_pct > 0:
        atr_pct = last.get("filt_atr_pct")
        if pd.isna(atr_pct):
            return False
        if atr_pct > params.atr_max_pct:
            return False

    if params.use_macd_confirm:
        line = last.get("filt_macd")
        sig = last.get("filt_macd_signal")
        if pd.isna(line) or pd.isna(sig):
            return False
        if side == "long" and not (line > sig and line > 0):
            return False
        if side == "short" and not (line < sig and line < 0):
            return False

    return True


def filters_pass(last, params, side: str) -> bool:
    """Public entry point: True if ALL enabled filters pass for `side`.

    Strategies wrap their BUY/SELL decisions with this so every filter in
    FILTER_HYPERPARAMS becomes a free knob on every strategy.
    """
    return _filter_gate_ok(last, params, side)


# ----------------------------------------------------------- registry ----
def _trend_ok(last, params) -> tuple[bool, bool]:
    trend = last.get("ema_trend")
    use_trend = params.ema_trend > 0 and not pd.isna(trend)
    if not use_trend:
        return True, True
    return last["close"] > trend, last["close"] < trend


REGISTRY: dict[str, Strategy] = {
    s.name: s
    for s in [
        EmaCrossoverStrategy(),
        RsiMeanReversionStrategy(),
        DonchianBreakoutStrategy(),
        IntradayDonchianStrategy(),
        LiquiditySweepStrategy(),
    ]
}

# Every strategy inherits the generic filter toggles via filters_pass(), so
# expose them uniformly on every strategy's hyperparams list. The UI and
# sweep runner iterate this list to know which knobs to show / sweep.
for _s in REGISTRY.values():
    _s.hyperparams = list(_s.hyperparams) + [
        k for k in FILTER_HYPERPARAMS if k not in _s.hyperparams
    ]


def get_strategy(name: str) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown strategy: {name!r}. Available: {list(REGISTRY)}"
        )
    return REGISTRY[name]


def list_strategies() -> list[str]:
    return list(REGISTRY)
