import type { StrategyParams } from "./types";

/**
 * Human-readable lines for each enabled generic filter (StrategyForm
 * "Filters" section). Values come from persisted or live params.
 */
export function enabledFilterSummaries(
  params: Partial<StrategyParams> | undefined
): string[] {
  if (!params) return [];
  const out: string[] = [];
  if (params.use_htf_confirm) {
    out.push(
      `HTF ${params.htf_timeframe ?? "—"} · EMA ${params.htf_ema_period ?? "—"}`
    );
  }
  if (params.use_adx_filter) {
    const p = params.filter_adx_period ?? 14;
    const mn = Number(params.adx_min ?? 0);
    const mx = Number(params.adx_max ?? 0);
    const bits: string[] = [`period ${p}`];
    if (mn > 0) bits.push(`min ≥${trimNum(mn)}`);
    if (mx > 0) bits.push(`max ≤${trimNum(mx)}`);
    out.push(`ADX (${bits.join(", ")})`);
  }
  if (params.use_volume_filter) {
    const ma = params.vol_ma_period ?? "—";
    const mult = Number(params.vol_mult ?? 0);
    out.push(`Volume MA${ma} · ≥${trimNum(mult)}× median`);
  }
  if (params.use_atr_filter) {
    out.push(`ATR% ≥${trimNum(Number(params.atr_min_pct ?? 0))}`);
  }
  if (params.use_macd_confirm) {
    out.push(
      `MACD ${params.macd_fast ?? "—"}/${params.macd_slow ?? "—"}/${params.macd_signal ?? "—"}`
    );
  }
  return out;
}

function trimNum(n: number): string {
  if (!Number.isFinite(n)) return "?";
  const s = n.toFixed(4).replace(/\.?0+$/, "");
  return s || "0";
}
