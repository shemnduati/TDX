"""
Historical OHLCV fetcher with on-disk cache.

Binance caps `fetch_ohlcv` at ~1000 bars per call, which is far too little
for serious backtesting or walk-forward validation. This module paginates
via the `since` parameter so you can request N bars of arbitrary depth,
and caches everything to disk so subsequent runs are instant and keep
working offline.

Public API:
    fetch_history(symbol, timeframe, bars, use_cache=True) -> DataFrame

Cache layout:
    cache/<symbol>_<timeframe>.json
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterable

import pandas as pd

from exchange import get_exchange
from utils import format_data

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Timeframe -> milliseconds. Covers every interval Binance supports that we
# realistically care about.
TF_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}

CHUNK = 1000  # Binance max bars per fetch_ohlcv call.


def _cache_path(symbol: str, timeframe: str) -> str:
    safe = symbol.replace("/", "-")
    return os.path.join(CACHE_DIR, f"{safe}_{timeframe}.json")


def _load_cache(path: str) -> list[list]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_cache(path: str, bars: list[list]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(bars, f)
    os.replace(tmp, path)


def _dedupe_sorted(bars: Iterable[list]) -> list[list]:
    by_ts = {b[0]: b for b in bars}
    return [by_ts[ts] for ts in sorted(by_ts)]


def _fetch_range(
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> list[list]:
    """Paginate fetch_ohlcv from start_ms up to end_ms."""
    exchange = get_exchange()
    tf_ms = TF_MS[timeframe]
    out: list[list] = []
    cursor = start_ms

    while cursor < end_ms:
        bars = exchange.fetch_ohlcv(
            symbol, timeframe, since=cursor, limit=CHUNK
        )
        if not bars:
            break
        out.extend(bars)
        next_cursor = bars[-1][0] + tf_ms
        if next_cursor <= cursor:
            # Exchange stopped progressing; bail to avoid an infinite loop.
            break
        cursor = next_cursor
        # ccxt's enableRateLimit handles the hard limit; small sleep is polite.
        time.sleep(0.15)

    return out


def ts_open_ms(ts) -> int:
    """Candle open time in milliseconds (Binance: row timestamp = open)."""
    if ts is None:
        return 0
    t = pd.Timestamp(ts)
    return int(t.value // 1_000_000)


def trim_incomplete_last_row(
    df: pd.DataFrame, timeframe: str, now_ms: int | None = None,
) -> pd.DataFrame:
    """Drop the last row if that candle is still in progress (unclosed).

    OHLCV rows use open time; a bar with open T is complete only when
    now >= T + tf_ms, so the newest row from `fetch_ohlcv` is often partial.
    """
    if df.empty or timeframe not in TF_MS:
        return df
    tf_ms = TF_MS[timeframe]
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    out = df
    if not out.empty:
        last_open = ts_open_ms(out.iloc[-1]["timestamp"])
        if last_open + tf_ms > now_ms:
            out = out.iloc[:-1].copy()
    return out


def fetch_history(
    symbol: str,
    timeframe: str,
    bars: int,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Return a DataFrame of the most-recent `bars` OHLCV rows."""
    if timeframe not in TF_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    tf_ms = TF_MS[timeframe]
    now_ms = int(time.time() * 1000)
    needed_start_ms = now_ms - bars * tf_ms
    path = _cache_path(symbol, timeframe)

    cached = _dedupe_sorted(_load_cache(path)) if use_cache else []

    ranges_to_fetch: list[tuple[int, int]] = []
    if not cached:
        ranges_to_fetch.append((needed_start_ms, now_ms))
    else:
        oldest = cached[0][0]
        newest = cached[-1][0]
        # Extend backwards if we need older bars than we have.
        if needed_start_ms < oldest:
            ranges_to_fetch.append((needed_start_ms, oldest))
        # Extend forwards if fresh bars have closed since last fetch.
        if newest + tf_ms < now_ms:
            ranges_to_fetch.append((newest + tf_ms, now_ms))

    for start_ms, end_ms in ranges_to_fetch:
        print(
            f"  Fetching {symbol} {timeframe}: "
            f"{pd.Timestamp(start_ms, unit='ms')} -> "
            f"{pd.Timestamp(end_ms, unit='ms')}"
        )
        fetched = _fetch_range(symbol, timeframe, start_ms, end_ms)
        cached.extend(fetched)

    cached = _dedupe_sorted(cached)

    if use_cache and ranges_to_fetch:
        _save_cache(path, cached)

    take = cached[-bars:] if len(cached) >= bars else cached
    if len(take) < bars:
        print(
            f"  WARNING: asked for {bars} bars, exchange returned {len(take)}."
        )
    df = format_data(take)
    return trim_incomplete_last_row(df, timeframe)
