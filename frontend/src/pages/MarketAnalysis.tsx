import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { LiveChartWidget } from "@/components/trading/LiveChartWidget";
import { MarketIndicatorsWidget } from "@/components/trading/MarketIndicatorsWidget";
import { FactorList, NoTradeCard } from "@/components/trading/SignalCardWidget";
import { compact, istTime, num, REGIME_LABEL, statusLabel } from "@/lib/format";
import type { Candle, Chain, EngineState, Quote, Signal } from "@/lib/types";

const SYMBOL_OPTS: Record<string, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY" };
const TF_OPTS: Record<string, string> = { "1m": "1 minute", "5m": "5 minutes", "15m": "15 minutes" };

export default function MarketAnalysis() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [timeframe, setTimeframe] = useState("5m");

  const { data: states } = useQuery({
    queryKey: ["engine-state"],
    queryFn: () => apiGet<EngineState[]>("/engine/state?symbols=NIFTY,BANKNIFTY"),
    refetchInterval: 4000,
    retry: false,
  });
  const { data: candles } = useQuery({
    queryKey: ["candles", symbol, timeframe, "analysis"],
    queryFn: () => apiGet<Candle[]>(`/market/candles/${symbol}?timeframe=${timeframe}&limit=120`),
    refetchInterval: 5000,
    retry: false,
  });
  const { data: quote } = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => apiGet<Quote>(`/market/quote/${symbol}`),
    refetchInterval: 2500,
    retry: false,
  });
  const { data: chain } = useQuery({
    queryKey: ["chain", symbol, "analysis"],
    queryFn: () => apiGet<Chain>(`/market/chain/${symbol}?strikes=6`),
    refetchInterval: 8000,
    retry: false,
  });
  const { data: active } = useQuery({
    queryKey: ["active-signals"],
    queryFn: () => apiGet<Signal[]>("/signals/active"),
    refetchInterval: 6000,
    retry: false,
  });

  const state = states?.find((s) => s.symbol === symbol) ?? null;
  const signal = (active ?? []).find((s) => s.symbol === symbol) ?? null;
  const overlays = useMemo(() => buildOverlays(candles ?? []), [candles]);
  const ind = state?.indicators ?? {};
  const supports = Array.isArray(ind.supports) ? (ind.supports as number[]) : [];
  const resistances = Array.isArray(ind.resistances) ? (ind.resistances as number[]) : [];

  const oiBuildup = useMemo(() => {
    const rows = chain?.rows ?? [];
    const near = rows.filter((r) => r.expiry === (chain?.expiries ?? [])[0]);
    const ce = near.filter((r) => r.option_type === "CE");
    const pe = near.filter((r) => r.option_type === "PE");
    const topCe = [...ce].sort((a, b) => b.open_interest - a.open_interest)[0];
    const topPe = [...pe].sort((a, b) => b.open_interest - a.open_interest)[0];
    return {
      ceOi: ce.reduce((a, b) => a + b.open_interest, 0),
      peOi: pe.reduce((a, b) => a + b.open_interest, 0),
      ceAdd: ce.reduce((a, b) => a + b.change_in_oi, 0),
      peAdd: pe.reduce((a, b) => a + b.change_in_oi, 0),
      resistanceStrike: topCe?.strike ?? null,
      supportStrike: topPe?.strike ?? null,
      atmIv: near.find((r) => r.strike === chain?.atm_strike && r.option_type === "CE")?.iv ?? null,
    };
  }, [chain]);

  return (
    <PageShell
      title="Market Analysis"
      subtitle="Multi-timeframe technical decomposition plus the F&O structure the direction engine consumes. 15m confirms trend, 5m generates signals, 1m tracks execution."
      testid="market-analysis-page"
      actions={
        <>
          <Select value={symbol} onValueChange={(v: string) => setSymbol(v)}>
            <SelectTrigger className="w-[150px]" data-testid="analysis-symbol-selector">
              <SelectValue>{(v) => SYMBOL_OPTS[v as string] ?? "Select"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {Object.entries(SYMBOL_OPTS).map(([v, l]) => (
                <SelectItem key={v} value={v} data-testid={`analysis-symbol-${v}`}>{l}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={timeframe} onValueChange={(v: string) => setTimeframe(v)}>
            <SelectTrigger className="w-[140px]" data-testid="timeframe-selector">
              <SelectValue>{(v) => TF_OPTS[v as string] ?? "Timeframe"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {Object.entries(TF_OPTS).map(([v, l]) => (
                <SelectItem key={v} value={v} data-testid={`timeframe-option-${v}`}>{l}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          <Metric label="LTP" value={num(quote?.ltp)} sub={`${istTime(quote?.ts)} IST`} testid="analysis-ltp" />
          <Metric
            label="Day change"
            value={`${num(quote?.change)} (${num(quote?.change_pct)}%)`}
            tone={(quote?.change ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
            testid="analysis-change"
          />
          <Metric label="Day range" value={`${num(quote?.low)} – ${num(quote?.high)}`} testid="analysis-range" />
          <Metric label="Volume" value={compact(quote?.volume)} testid="analysis-volume" />
          <Metric
            label="Direction"
            value={statusLabel(state?.direction ?? "—")}
            sub={`${state?.display_score ?? 0}/100`}
            tone={
              state?.direction === "BULLISH" ? "text-emerald-300" : state?.direction === "BEARISH" ? "text-rose-300" : undefined
            }
            testid="analysis-direction"
          />
          <Metric label="Regime" value={REGIME_LABEL[quote?.regime ?? ""] ?? "—"} testid="analysis-regime" />
        </div>

        <Panel
          title={`${SYMBOL_OPTS[symbol]} · ${TF_OPTS[timeframe]} candles with VWAP, EMA and S/R`}
          testid="analysis-chart-panel"
        >
          <LiveChartWidget
            candles={candles ?? []}
            vwap={overlays.vwapSeries}
            ema20={overlays.ema20}
            ema50={overlays.ema50}
            supports={supports}
            resistances={resistances}
            signal={signal}
            height={420}
            testid="analysis-chart"
          />
        </Panel>

        <Panel title="Indicator values (engine authoritative)" testid="analysis-indicators-panel">
          <MarketIndicatorsWidget state={state} testid="analysis-indicators" />
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Signal explanation — contributing factors" testid="analysis-factors-panel">
            {state && state.factors.length > 0 ? (
              <>
                <div className="mb-3 flex items-end justify-between gap-3">
                  <p
                    className={`font-heading text-lg font-bold ${
                      state.direction === "BULLISH"
                        ? "text-emerald-400"
                        : state.direction === "BEARISH"
                          ? "text-rose-400"
                          : "text-slate-400"
                    }`}
                    data-testid="analysis-verdict"
                  >
                    {statusLabel(state.direction)} — score {state.display_score}/100
                  </p>
                  <span className="font-mono text-[10px] text-slate-500">
                    {istTime(state.ts)} IST
                  </span>
                </div>
                <FactorList factors={state.factors} testid="analysis-factor-list" />
                {state.no_trade_reason ? (
                  <p
                    className="mt-3 rounded border border-slate-700/60 bg-slate-900/60 px-2.5 py-2 text-[11px] leading-relaxed text-slate-400"
                    data-testid="analysis-no-trade-reason"
                  >
                    {state.no_trade_reason}
                  </p>
                ) : null}
              </>
            ) : (
              <NoTradeCard state={state} testid="analysis-no-trade" />
            )}
          </Panel>

          <Panel title="F&O structure — option-chain derived levels" testid="analysis-fno-panel">
            <div className="grid grid-cols-2 gap-2">
              <Metric label="PCR (OI)" value={num(chain?.pcr, 3)} testid="fno-pcr" />
              <Metric label="Max pain" value={num(chain?.max_pain, 0)} testid="fno-max-pain" />
              <Metric
                label="Chain resistance"
                value={oiBuildup.resistanceStrike ? num(oiBuildup.resistanceStrike, 0) : "—"}
                sub="highest CE OI strike"
                tone="text-rose-300"
                testid="fno-chain-resistance"
              />
              <Metric
                label="Chain support"
                value={oiBuildup.supportStrike ? num(oiBuildup.supportStrike, 0) : "—"}
                sub="highest PE OI strike"
                tone="text-emerald-300"
                testid="fno-chain-support"
              />
              <Metric label="Total CE OI" value={compact(oiBuildup.ceOi)} sub={`Δ ${compact(oiBuildup.ceAdd)}`} testid="fno-ce-oi" />
              <Metric label="Total PE OI" value={compact(oiBuildup.peOi)} sub={`Δ ${compact(oiBuildup.peAdd)}`} testid="fno-pe-oi" />
              <Metric
                label="Futures / basis"
                value={num(chain?.futures_price)}
                sub={`basis ${num(chain?.basis)}`}
                testid="fno-futures"
              />
              <Metric
                label="ATM IV"
                value={oiBuildup.atmIv !== null ? `${num(oiBuildup.atmIv * 100, 2)}%` : "—"}
                testid="fno-atm-iv"
              />
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
              Technical observation only. Option-chain OI concentration is treated as a
              soft support/resistance input to the F&amp;O factor — never as a standalone
              trade trigger.
            </p>
          </Panel>
        </div>
      </div>
    </PageShell>
  );
}

function buildOverlays(candles: Candle[]) {
  const closes = candles.map((c) => c.c);
  const ema = (period: number): (number | null)[] => {
    const out: (number | null)[] = closes.map(() => null);
    if (closes.length < period) return out;
    const k = 2 / (period + 1);
    let prev = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    out[period - 1] = prev;
    for (let i = period; i < closes.length; i += 1) {
      prev = closes[i] * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  };
  const vwapSeries: (number | null)[] = [];
  let cumPV = 0;
  let cumV = 0;
  let day = "";
  candles.forEach((c) => {
    const d = c.ts.slice(0, 10);
    if (d !== day) {
      day = d;
      cumPV = 0;
      cumV = 0;
    }
    const tp = (c.h + c.l + c.c) / 3;
    cumPV += tp * c.v;
    cumV += c.v;
    vwapSeries.push(cumV > 0 ? cumPV / cumV : null);
  });
  return { vwapSeries, ema20: ema(20), ema50: ema(50) };
}
