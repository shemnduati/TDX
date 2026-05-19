"""
Standalone CLI paper-trading bot.

This is the pre-dashboard entry point and still handy for headless paper
trading on a server. For an interactive experience, prefer starting the
live bot from the React dashboard (which wraps `live_bot.LiveBotManager`).

Anything module-level here must be pure — we do NOT instantiate PaperTrader
or hit the exchange on import, because doing so would clobber `data.json`
if this module were ever imported by the dashboard process.
"""
from __future__ import annotations

import argparse
import time

from backtest import Params
from config import LIMIT
from exchange import get_exchange
from history import TF_MS
from live_bot import _seconds_until_next_bar_close, run_exchange_paper_step
from paper_trader import PaperTrader
from strategies import get_strategy


def _build_trader(params: Params) -> PaperTrader:
    return PaperTrader(
        initial_balance=params.initial_balance,
        allocation_pct=params.allocation_pct,
        stop_loss_pct=params.stop_loss_pct,
        take_profit_pct=params.take_profit_pct,
        entry_cooldown_bars=params.entry_cooldown_bars,
        fee_pct=params.fee_pct,
        slippage_pct=params.slippage_pct,
        slippage_atr_mult=params.slippage_atr_mult,
        half_spread_bps=params.half_spread_bps,
        intrabar_sl_tp_policy=params.intrabar_sl_tp_policy,
        intrabar_random_seed=params.intrabar_random_seed,
        use_trailing_stop=params.use_trailing_stop,
        trailing_stop_pct=params.trailing_stop_pct,
        max_consecutive_losses=params.max_consecutive_losses,
        max_daily_loss_pct=params.max_daily_loss_pct,
        enable_funding=params.enable_funding,
        funding_rate_bps=params.funding_rate_bps,
        funding_interval_hours=params.funding_interval_hours,
    )


def run_bot(
    params: Params,
    strategy,
    exchange,
    trader: PaperTrader,
    loop_state: dict,
) -> None:
    # Same path as `live_bot`: signal on closed bars, entry at current
    # in-progress open, then SL/TP on that bar's range. `loop_state` holds
    # dedupe keys so we do not re-run the strategy on the same closed bar
    # if the loop fires twice before a new candle completes.
    signal, mtm, rsi_val, out_ts = run_exchange_paper_step(
        params,
        strategy,
        exchange,
        trader,
        ohlcv_limit=LIMIT,
        last_processed_closed_ts=loop_state.get("last_closed_ts"),
        last_reported_signal=loop_state.get("last_signal", "HOLD"),
    )
    loop_state["last_closed_ts"] = out_ts
    loop_state["last_signal"] = signal
    rtxt = f"{rsi_val:.1f}" if rsi_val is not None else "n/a"
    print(
        f"[{strategy.name} {params.symbol} {params.timeframe}] "
        f"Price: {mtm:.2f} | RSI: {rtxt} | Signal: {signal}"
    )
    trader.status(mtm)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CLI paper-trading bot.")
    p.add_argument(
        "--profile", default=None,
        help="Named profile to load (see profiles/ and profiles.py). "
             "If omitted, config.py defaults are used."
    )
    p.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between ticks (default: 60)."
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    params = Params()
    if args.profile:
        from profiles import apply_profile, load_profile
        doc = load_profile(args.profile)
        params = apply_profile(params, args.profile)
        print(
            f"[bot] profile={args.profile!r} "
            f"({doc.get('description', 'no description')})  "
            f"symbol={params.symbol} timeframe={params.timeframe} "
            f"strategy={params.strategy}"
        )

    strategy = get_strategy(params.strategy)
    exchange = get_exchange()
    trader = _build_trader(params)

    tf_ms = TF_MS.get(params.timeframe, 60_000)
    loop_state: dict = {}
    while True:
        try:
            run_bot(params, strategy, exchange, trader, loop_state)
        except Exception as e:
            print("Error:", e)
        sleep_s = max(args.interval, _seconds_until_next_bar_close(tf_ms))
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
