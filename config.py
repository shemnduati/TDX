import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET = os.getenv("SECRET")

# Market
# Baseline was updated after the filter-ablation experiment documented in
# experiments/filter_ablation.py. The best WF result on BTC/USDT 4h came
# from the 12/50 EMA crossover + 100-bar trend filter + ATR sizing + ADX
# regime filter (adx_min=20). WF score 0.30 (vs. 0.17 without ADX); WF
# mean +1.46%/window, positive rate 69%, stdev 2.78%. Cross-market note:
# this config is BTC-4h-specialist — on ETH-4h the ADX filter hurts
# (positive rate drops from 62% to 44%). For a multi-asset deployment,
# use per-symbol profiles (see profiles/ and profiles.py) rather than
# this default.
#
# Want more consistency and willing to sacrifice mean return? Also turn
# USE_HTF_CONFIRM=True with HTF_EMA_PERIOD=50 — WF score bumps to 0.33
# on BTC-4h (pos 75%, mean +1.17%).
SYMBOL = "BTC/USDT"
# Curated list of symbols the dashboard's Symbol dropdown offers. Ordered
# roughly by Binance spot volume — the pairs a user is most likely to
# actually backtest. Extend this list if you care about other assets;
# strings here become the options in the UI.
AVAILABLE_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "MATIC/USDT",
    "LTC/USDT",
    "TRX/USDT",
    "ATOM/USDT",
    "NEAR/USDT",
    "ARB/USDT",
    "OP/USDT",
    "APT/USDT",
    "SUI/USDT",
    "SHIB/USDT",
]
TIMEFRAME = "4h"     # 4h baseline: 16-window walk-forward (69% pos, +1.46% mean with ADX)
LIMIT = 300          # bars fetched per live tick (enough warm-up for EMA_TREND=100)
# Bars for backtests / WF. Binance caps one fetch at ~1000; `history.fetch_history`
# paginates automatically, so raising this pulls deeper history via multiple calls.
BACKTEST_BARS = 1000

# ---- Strategy ----------------------------------------------------------------
# Active strategy. Implementations live in strategies.py. Currently:
#   "ema_crossover"       — EMA crossover + RSI filter + trend filter
#   "rsi_mean_reversion"  — RSI bounce off oversold / rejection off overbought
#   "donchian_breakout"   — breakout above/below the N-bar Donchian channel
#   "intraday_donchian"  — HTF+Donchian+ATR filters (use 1h HTF + 5m/15m LTF)
STRATEGY = "ema_crossover"

# EMA crossover hyperparameters
# 12/50 was the cross-market ROBUST winner (BTC-4h AND ETH-4h) and scored
# highest on BTC-4h once the ADX filter was layered on (score 0.30 vs 0.17
# for the 20/50 control). EMA_TREND=100 (~17 days on 4h) reacts faster
# than 200 and held up OOS.
EMA_SHORT = 12
EMA_LONG = 50
EMA_TREND = 100    # regime filter: only long above, only short below (0 disables)

# RSI — shared by both strategies
RSI_PERIOD = 14
RSI_BUY_MAX = 70       # ema_crossover: skip long entries when RSI >= this
RSI_SELL_MIN = 30      # ema_crossover: skip short entries when RSI <= this
RSI_OVERSOLD = 30      # rsi_mean_reversion: long entry when crossing up through this
RSI_OVERBOUGHT = 70    # rsi_mean_reversion: short entry when crossing down through this

# Donchian breakout lookback (bars). Classic "turtle" value is 20; 50/55 are
# also common for slower, fewer-but-bigger breakouts.
DONCHIAN_PERIOD = 20
# When True, require a "tight" market before a valid break: the average bar
# range (high–low) over the prior L bars must be <= max_range_atr × ATR.
USE_DONCHIAN_COMPRESSION = False
DONCHIAN_COMPRESSION_LOOKBACK = 20
DONCHIAN_COMPRESSION_MAX_RANGE_ATR = 1.0
# When True, longs require RSI < rsi_buy_max, shorts require RSI > rsi_sell_min
# (anti-chase; like intraday_donchian use_breakout_rsi).
USE_DONCHIAN_RSI = False

# intraday_donchian: ATR mean window, min extension past Donchian band in ATR
# units, optional LTF EMA (0 = off), optional RSI / ATR-expansion gates.
ATR_MA_PERIOD = 20
BREAKOUT_ATR_MULT = 0.5
LTF_EMA_PERIOD = 0
USE_BREAKOUT_RSI = False
USE_ATR_EXPANSION = False

# ---- Liquidity-sweep reversal ------------------------------------------------
# "Stop hunt" fade: price pokes above a prior swing high (or below a prior
# swing low), fails to hold, and closes back inside the range. The mechanism
# is retail stop-cluster harvesting — once the stops are cleared, the driving
# flow exhausts and price reverts. Works in *ranging* regimes, gets chopped
# in strong trends, so it's gated by ADX.
SWEEP_LOOKBACK = 20          # bars to define the swing high/low we sweep
SWEEP_ADX_PERIOD = 14
SWEEP_ADX_MAX = 25.0         # only trade when ADX < this (0 disables the gate)
SWEEP_VOLUME_MULT = 1.5      # sweep bar's volume must exceed this × rolling median
SWEEP_VOLUME_LOOKBACK = 20

# Bars of "no new entries" after a position closes. Prevents the strategy
# from re-entering on the same wobble that just closed it. (0 disables.)
ENTRY_COOLDOWN_BARS = 3

# ---- Risk --------------------------------------------------------------------
# Balanced profile: full allocation, 2% stop / 4% take-profit.
TRADE_ALLOCATION_PCT = 1.0  # fraction of balance used per trade
STOP_LOSS_PCT = 0.02        # 2% adverse move from entry triggers exit
TAKE_PROFIT_PCT = 0.04      # 4% favourable move from entry triggers exit

# Per-side taker fee. Binance spot ~0.001 (0.1%), Binance futures ~0.0004 (0.04%).
FEE_PCT = 0.001

INITIAL_BALANCE = 1000

# ---- ATR-based position sizing (optional) -----------------------------------
# When USE_ATR_SIZING is True, per-trade notional is derived from volatility:
#   risk_amount = balance * ATR_RISK_PCT
#   stop_distance = ATR_STOP_MULT * ATR
#   size = risk_amount / stop_distance
# SL/TP levels override the fixed pct levels — they're placed at
# entry ± ATR_STOP_MULT*ATR and entry ± ATR_TP_MULT*ATR respectively.
# This keeps dollar risk per trade stable across regimes. The BTC 4h ROBUST
# config leans on this to keep the per-window stdev at 2.57% instead of
# blowing up on the volatile windows.
USE_ATR_SIZING = True
ATR_PERIOD = 14
ATR_RISK_PCT = 0.01     # risk 1% of balance per trade
ATR_STOP_MULT = 2.0     # stop at entry ± 2*ATR
ATR_TP_MULT = 3.0       # take at entry ± 3*ATR (1.5:1 R:R)

# ---- Generic filters (apply to every strategy) -------------------------------
# Each filter is a separate boolean toggle. When OFF the corresponding
# indicator is never computed and the gate always passes, so a strategy with
# every filter OFF behaves exactly the same as before this was added.
#
# Flip one on during a sweep (e.g. grid {"use_htf_confirm": [False, True]})
# to see whether it genuinely helps. Don't promote a filter to "default on"
# for a strategy unless it improves walk-forward score on ≥2 markets — the
# whole point of making these opt-in is so we can *measure* each one.

# Higher-timeframe trend confirmation (e.g. only long when the daily EMA is
# rising). HTF data is fetched separately from the LTF series and merged
# with `pd.merge_asof(direction="backward")` so there's no look-ahead.
USE_HTF_CONFIRM = False
HTF_TIMEFRAME = "1d"
HTF_EMA_PERIOD = 50

# Generic ADX regime filter. Independent of liquidity_sweep's built-in ADX
# gate — the sweep strategy keeps its own knobs (`sweep_adx_*`) while these
# fields govern the shared filter applied on top of every strategy.
#   adx_min > 0 : require ADX > adx_min (trend strategies want trending)
#   adx_max > 0 : require ADX < adx_max (MR wants range)
#   both 0      : the filter ignores ADX even when use_adx_filter=True
#
# Enabled by default with adx_min=20: the ablation experiment showed this
# adds +0.10–0.13 WF score to EMA crossover on BTC-4h and donchian on BTC
# and ETH 4h. On ETH-4h fast-donchian configs it HURTS (those want lower
# ADX) — use a profile override to turn it off there.
USE_ADX_FILTER = True
FILTER_ADX_PERIOD = 14
ADX_MIN = 20.0
ADX_MAX = 0.0

# Require the signal bar's volume to exceed `vol_mult` × rolling median over
# `vol_ma_period` bars. Useful for breakouts — a breakout without
# participation is usually a fake.
USE_VOLUME_FILTER = False
VOL_MA_PERIOD = 20
VOL_MULT = 1.2

# Skip signals when volatility is too low (nothing to trade). ATR expressed
# as a percentage of close price, so the threshold is regime-agnostic.
USE_ATR_FILTER = False
ATR_MIN_PCT = 0.0
# Cap volatility (opposite of atr_min). Skip when ATR/close is *above* the
# threshold—useful to avoid news-like spikes in mean reversion, etc.
USE_ATR_MAX_FILTER = False
ATR_MAX_PCT = 0.0  # 0 = disabled even when the toggle is on

# UTC time-of-day window (bar timestamp must fall in [start, end) in minutes
# from midnight; end may be < start for a session that wraps past midnight).
USE_TIME_FILTER = False
# Default: 08:00–20:00 UTC (crypto cash session overlap proxy; adjust in UI).
TIME_START_UTC_MINS = 8 * 60
TIME_END_UTC_MINS = 20 * 60

# Session-aware filter. Empty tuple = all sessions allowed.
# Valid values: "asia", "london", "overlap", "ny", "off".
ALLOWED_SESSIONS: tuple[str, ...] = ()
# Block Saturday and Sunday bars entirely.
BLOCK_WEEKENDS: bool = False

# --- Mean-reversion–specific (rsi_mean_reversion only) --------------------
# 0 = off. When >0, only trade when ADX < this (ranging; uses filter_adx_period).
MR_REGIME_ADX_MAX = 0.0

# --- Execution & risk (PaperTrader) --------------------------------------
# Proportional half-spread / slippage on each fill (0 = off).
SLIPPAGE_PCT = 0.0
# Extra proportional slippage per fill added as atr_mult × (ATR / reference_price).
# When >0 backtests/live compute ATR on the series (`atr_period` from Params).
SLIPPAGE_ATR_MULT = 0.0
# Fixed half-spread per fill as basis points (1 bp = 0.01%).
# Adds (HALF_SPREAD_BPS / 10000) to the *fractional* adverse move on entry/exit,
# stacked on top of SLIPPAGE_PCT + ATR-linked terms (see PaperTrader).
HALF_SPREAD_BPS = 0.0
# Live paper only: skip new entries when full bid–ask spread exceeds this (bps).
# 0 = off. Typical BTC/USDT spot is often ~1–5 bps; alts can be 20+ in stress.
MAX_SPREAD_BPS = 0.0
# Intraday ambiguity: candle touches BOTH stop and TP. `stop_first` is conservative.
# Use `take_first` for an optimistic bracket; `random` for a stochastic path (seeded).
INTRABAR_SL_TP_POLICY = "stop_first"  # stop_first | take_first | random
INTRABAR_RANDOM_SEED = 42
# Trail stop this far below the best price (long) / above (short). 0 = off.
USE_TRAILING_STOP = False
TRAILING_STOP_PCT = 0.015
# 0 = off. Halt *new* entries after this many realized losses in a row.
MAX_CONSECUTIVE_LOSSES = 0
# 0 = off. Halt if realized balance fell more than this fraction since UTC day start.
MAX_DAILY_LOSS_PCT = 0.0

# Perpetual funding model (optional). Positive `FUNDING_RATE_BPS` means longs pay
# shorts every `FUNDING_INTERVAL_HOURS`. Negative does the reverse.
ENABLE_FUNDING = False
FUNDING_RATE_BPS = 0.0
FUNDING_INTERVAL_HOURS = 8

# MACD confirmation. For a BUY we require MACD line > signal line (and >0);
# for a SELL we require MACD line < signal line (and <0).
USE_MACD_CONFIRM = False
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Legacy aliases (kept so nothing outside this file breaks if it imports them)
SHORT_WINDOW = EMA_SHORT
LONG_WINDOW = EMA_LONG
