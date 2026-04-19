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

from backtest import Params, _atr_overrides, apply_full_indicators
from config import LIMIT
from exchange import get_exchange
from paper_trader import PaperTrader
from strategies import get_strategy
from utils import format_data


def _build_trader(params: Params) -> PaperTrader:
    return PaperTrader(
        initial_balance=params.initial_balance,
        allocation_pct=params.allocation_pct,
        stop_loss_pct=params.stop_loss_pct,
        take_profit_pct=params.take_profit_pct,
        entry_cooldown_bars=params.entry_cooldown_bars,
        fee_pct=params.fee_pct,
    )


def run_bot(params: Params, strategy, exchange, trader: PaperTrader) -> None:
    # Symbol / timeframe pulled from `params` so profile overrides flow
    # through — previously these were module-level imports and profile
    # switches silently had no effect on the live fetch call.
    bars = exchange.fetch_ohlcv(params.symbol, params.timeframe, limit=LIMIT)
    df = format_data(bars)
    df = apply_full_indicators(df, params)
    signal = strategy.generate_signal(df, params)

    price = float(df["close"].iloc[-1])
    rsi_now = float(df["rsi"].iloc[-1])
    print(
        f"[{strategy.name} {params.symbol} {params.timeframe}] "
        f"Price: {price:.2f} | RSI: {rsi_now:.1f} | Signal: {signal}"
    )

    # Mirror live_bot / backtest: when ATR sizing is enabled, translate
    # the signal into explicit size / SL / TP overrides for this bar.
    overrides = _atr_overrides(signal, price, df.iloc[-1], trader, params)
    trader.on_signal(signal, price, **overrides)
    trader.on_tick(price)
    trader.status(price)


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

    while True:
        try:
            run_bot(params, strategy, exchange, trader)
            time.sleep(args.interval)
        except Exception as e:
            print("Error:", e)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
