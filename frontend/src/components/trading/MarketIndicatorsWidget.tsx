import { Metric } from "@/components/layout/PageShell";
import { compact, num, REGIME_LABEL } from "@/lib/format";
import type { EngineState } from "@/lib/types";

const asNum = (v: unknown): number | null => (typeof v === "number" ? v : null);

export function MarketIndicatorsWidget({
  state,
  testid = "market-indicators",
}: {
  state?: EngineState | null;
  testid?: string;
}) {
  const ind = state?.indicators ?? {};
  const supports = Array.isArray(ind.supports) ? (ind.supports as number[]) : [];
  const resistances = Array.isArray(ind.resistances) ? (ind.resistances as number[]) : [];
  const rsi = asNum(ind.rsi);

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" data-testid={testid}>
      <Metric label="Spot" value={num(asNum(ind.spot))} testid="indicator-spot" />
      <Metric label="VWAP" value={num(asNum(ind.vwap) ?? asNum(ind.vwap_quote))} testid="indicator-vwap" />
      <Metric label="EMA 20" value={num(asNum(ind.ema_fast))} testid="indicator-ema-fast" />
      <Metric label="EMA 50" value={num(asNum(ind.ema_slow))} testid="indicator-ema-slow" />
      <Metric label="EMA 200" value={num(asNum(ind.ema_200))} testid="indicator-ema-200" />
      <Metric
        label="RSI (14)"
        value={num(rsi, 1)}
        tone={rsi === null ? undefined : rsi > 70 ? "text-amber-300" : rsi < 30 ? "text-sky-300" : undefined}
        testid="indicator-rsi"
      />
      <Metric
        label="MACD hist"
        value={num(asNum(ind.macd_hist))}
        sub={`line ${num(asNum(ind.macd))}`}
        testid="indicator-macd"
      />
      <Metric label="ATR" value={num(asNum(ind.atr))} testid="indicator-atr" />
      <Metric
        label="Rel. volume"
        value={`${num(asNum(ind.rel_volume), 2)}x`}
        sub="vs 20-bar average"
        testid="indicator-rel-volume"
      />
      <Metric
        label="PCR (OI)"
        value={num(asNum(ind.pcr), 3)}
        tone={
          asNum(ind.pcr) === null ? undefined : (asNum(ind.pcr) as number) >= 1.1 ? "text-emerald-300" : (asNum(ind.pcr) as number) <= 0.9 ? "text-rose-300" : undefined
        }
        testid="indicator-pcr"
      />
      <Metric label="Max pain" value={num(asNum(ind.max_pain), 0)} testid="indicator-max-pain" />
      <Metric
        label="Futures basis"
        value={num(asNum(ind.basis))}
        sub={`fut ${num(asNum(ind.futures))}`}
        tone={asNum(ind.basis) === null ? undefined : (asNum(ind.basis) as number) >= 0 ? "text-emerald-300" : "text-rose-300"}
        testid="indicator-basis"
      />
      <Metric
        label="Fut ΔOI"
        value={compact(asNum(ind.fut_oi_change))}
        testid="indicator-fut-oi-change"
      />
      <Metric
        label="Support"
        value={supports.length ? num(supports[0], 0) : "—"}
        sub={supports.slice(1, 3).map((s) => num(s, 0)).join(" · ") || undefined}
        tone="text-emerald-300"
        testid="indicator-support"
      />
      <Metric
        label="Resistance"
        value={resistances.length ? num(resistances[0], 0) : "—"}
        sub={resistances.slice(1, 3).map((r) => num(r, 0)).join(" · ") || undefined}
        tone="text-rose-300"
        testid="indicator-resistance"
      />
      <Metric
        label="Regime"
        value={REGIME_LABEL[String(ind.regime ?? "")] ?? "—"}
        sub={`eval ${state?.evaluation_ms ?? 0} ms`}
        testid="indicator-regime"
      />
    </div>
  );
}
