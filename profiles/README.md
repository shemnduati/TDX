# Profiles

Per-market parameter presets. See `profiles.py` for the loader API and
the schema for the JSON files in this directory.

## Why this exists

The filter-ablation experiment (`experiments/filter_ablation.py`) made
it clear that no single Params configuration is best across every
(symbol, timeframe) pair. For example:

- `ADX min=20` lifts BTC/USDT 4h WF score from 0.17 → 0.30 (+76%).
- The same filter drops ETH/USDT 4h fast-donchian positive-window rate
  from 75% → 50%.

Baking one market's winner into `config.py` as universal defaults
silently degrades every other market. Profiles solve that: one file per
(symbol, timeframe) and strategy, each one pinning only the fields that
differ from `config.py` defaults.

## Usage

```bash
# List available profiles
python -m profiles list

# Inspect a profile
python -m profiles show btc-4h-adx

# Run the CLI bot with a profile
python bot.py --profile eth-4h-donchian

# Backtest with a profile
python backtest.py --profile btc-4h-adx-htf
```

Profile values override both `config.py` defaults AND any CLI flags
passed on the same command line. Rationale: a profile is meant to be a
reproducible preset — mixing a half-applied profile with manual CLI
tweaks is a recipe for misleading results. To try a variant, save a
new profile under a different name.

## Keep-up workflow

1. Run a walk-forward sweep for a market (via the dashboard or
   `experiments/explore_configs.py`).
2. Pick the WF winner and save its Params as a profile (either by
   copying an existing JSON file and editing, or extending
   `profiles.py` with a `save_profile()` call).
3. Commit the JSON. That market now has a reproducible,
   version-controlled best config.
4. When a better config emerges, save it under a new name
   (e.g. `btc-4h-adx-v2`) and keep the old one around for A/B
   comparisons. Do NOT delete old profiles — they serve as historical
   baselines.

## Currently seeded profiles

| Profile | Market | Strategy | WF score | WF mean % | Pos rate |
|---|---|---|---|---|---|
| `btc-4h-adx` | BTC/USDT 4h | EMA 12/50 crossover + ADX≥20 | **0.30** | +1.46% | 69% |
| `btc-4h-adx-htf` | BTC/USDT 4h | + HTF 1d EMA50 confirmation | **0.33** | +1.17% | 75% |
| `eth-4h-donchian` | ETH/USDT 4h | Donchian 20 + trend100, no ADX | **0.43** | +2.39% | 75% |
| `eth-4h-donchian-consistent` | ETH/USDT 4h | Donchian 20 + trend200, no ADX | **0.39** | +2.05% | **81%** |
| `btc-4h-don40-adx-htf-vol` | BTC/USDT 4h | Donchian 40 + ADX + HTF + vol 1.3× | — | +58% (full BT)* | — |

\*Full-sample backtest on cached history only (see profile `performance`); run walk-forward before treating as production-ready.

All four WF-validated profiles above were validated over 16 walk-forward windows on 10,000 bars of
4h data (~4.5 years covering 2022 bear, 2024 halving, 2025 top).
