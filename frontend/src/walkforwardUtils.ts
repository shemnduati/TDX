import type { StrategyParams } from "./types";

/** Match walkforward_runner dev slice (first 75% of bars, before holdout). */
export function estimateWalkforwardWindows(
  bars: number,
  trainBars: number,
  testBars: number,
  step: number | ""
): string {
  if (!bars || !trainBars || !testBars) return "—";
  const devEnd = Math.floor(bars * 0.75);
  if (devEnd < trainBars + testBars) return "0";
  const s = step === "" || !step ? testBars : step;
  let count = 0;
  let start = 0;
  while (start + trainBars + testBars <= devEnd) {
    count += 1;
    start += s;
  }
  return String(count);
}

/**
 * When validating a saved profile, lock tuned keys to the profile values
 * so WF does not fall back to the strategy default grid (Don 30/40/50, etc.).
 */
export function suggestFixedOptMatrix(params: StrategyParams): string {
  const s = params.strategy;
  if (s === "donchian_breakout" && params.donchian_period) {
    return JSON.stringify({ donchian_period: [params.donchian_period] });
  }
  if (s === "intraday_donchian" && params.donchian_period) {
    const o: Record<string, number[]> = {
      donchian_period: [params.donchian_period],
    };
    if (params.breakout_atr_mult) {
      o.breakout_atr_mult = [params.breakout_atr_mult];
    }
    return JSON.stringify(o);
  }
  if (s === "ema_crossover") {
    const o: Record<string, number[]> = {};
    if (params.ema_short) o.ema_short = [params.ema_short];
    if (params.ema_long) o.ema_long = [params.ema_long];
    if (Object.keys(o).length) return JSON.stringify(o);
  }
  if (s === "rsi_mean_reversion") {
    const o: Record<string, number[]> = {};
    if (params.rsi_oversold != null) o.rsi_oversold = [params.rsi_oversold];
    if (params.rsi_overbought != null) {
      o.rsi_overbought = [params.rsi_overbought];
    }
    if (Object.keys(o).length) return JSON.stringify(o);
  }
  return "";
}
