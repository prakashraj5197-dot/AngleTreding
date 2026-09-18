import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { MarketStatusBar } from "@/components/trading/MarketStatusBar";
import { LiveChartWidget } from "@/components/trading/LiveChartWidget";
import { MarketIndicatorsWidget } from "@/components/trading/MarketIndicatorsWidget";
import { SignalCardWidget, SignalMiniRow } from "@/components/trading/SignalCardWidget";
import { istTime, num, statusLabel } from "@/lib/format";
import type { Candle, EngineState, PaperAccount, Signal } from "@/lib/types";

const SYMBOLS = [
  { value: "NIFTY", label: "NIFTY 50" },
  { value: "BANKNIFTY", label: "BANK NIFTY" },
];
const SYMBOL_LABEL: Record<string, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY" };

export default function Dashboard() {
  const [symbol, setSymbol] = useState("NIFTY");
  const qc = useQueryClient();

  const { data: states } = useQuery({
    queryKey: ["engine-state"],
    queryFn: () => apiGet<EngineState[]>("/engine/state?symbols=NIFTY,BANKNIFTY"),
    refetchInterval: 4000,
    retry: false,
  });
  const { data: active } = useQuery({
    queryKey: ["active-signals"],
    queryFn: () => apiGet<Signal[]>("/signals/active"),
    refetchInterval: 4000,
    retry: false,
  });
  const { data: recent } = useQuery({
    queryKey: ["signals", "recent"],
    queryFn: () => apiGet<Signal[]>("/signals?limit=12"),
    refetchInterval: 8000,
    retry: false,
  });
  const { data: candles } = useQuery({
    queryKey: ["candles", symbol, "5m"],
    queryFn: () => apiGet<Candle[]>(`/market/candles/${symbol}?timeframe=5m&limit=90`),
    refetchInterval: 5000,
    retry: false,
  });
  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: () => apiGet<PaperAccount>("/paper/account"),
    refetchInterval: 6000,
    retry: false,
  });

  const evaluate = useMutation({
    mutationFn: () => apiPost<EngineState[]>("/engine/evaluate", { symbol }),
    onSuccess: (res) => {
      const st = res[0];
      toast.success(
        `${SYMBOL_LABEL[st.symbol] ?? st.symbol}: ${statusLabel(st.direction)} (${st.display_score}/100)`,
        { description: st.no_trade_reason ?? "Setup qualified — signal recorded." },
      );
      void qc.invalidateQueries({ queryKey: ["engine-state"] });
      void qc.invalidateQueries({ queryKey: ["active-signals"] });
      void qc.invalidateQueries({ queryKey: ["signals"] });
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: () => toast.error("Evaluation request failed."),
  });

  const state = states?.find((s) => s.symbol === symbol) ?? null;
  const activeForSymbol = (active ?? []).find((s) => s.symbol === symbol) ?? (active ?? [])[0] ?? null;

  const { vwapSeries, ema20, ema50 } = useMemo(() => buildOverlays(candles ?? []), [candles]);
  const ind = state?.indicators ?? {};
  const supports = Array.isArray(ind.supports) ? (ind.supports as number[]) : [];
  const resistances = Array.isArray(ind.resistances) ? (ind.resistances as number[]) : [];

  return (
    <PageShell
      title="Trading Command Center"
      subtitle="Live simulated NSE feed, multi-factor direction engine and option selection in one view. NO TRADE is a valid, expected outcome — the engine only signals when every gate passes."
      testid="dashboard-page"
      actions={
        <>
          <Select value={symbol} onValueChange={(v: string) => setSymbol(v)}>
            <SelectTrigger className="w-[150px]" data-testid="symbol-selector">
              <SelectValue>{(v) => SYMBOL_LABEL[v as string] ?? "Select"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {SYMBOLS.map((s) => (
                <SelectItem key={s.value} value={s.value} data-testid={`symbol-option-${s.value}`}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            onClick={() => evaluate.mutate()}
            disabled={evaluate.isPending}
            data-testid="evaluate-now-button"
          >
            <RefreshCw className={`size-3.5 ${evaluate.isPending ? "animate-spin" : ""}`} />
            Evaluate now
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <MarketStatusBar />

        <div className="grid gap-4 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-8">
            <Panel
              title="Current signal"
              testid="current-signal-panel"
              right={
                <Link
                  to="/signals"
                  className={buttonVariants({ variant: "ghost", size: "xs" })}
                  data-testid="view-all-signals-link"
                >
                  All signals
                </Link>
              }
            >
              <SignalCardWidget signal={activeForSymbol} state={state} />
            </Panel>

            <Panel
              title={`${SYMBOL_LABEL[symbol]} · 5-minute structure`}
              testid="live-chart-panel"
              right={
                <span className="font-mono text-[10px] text-slate-500" data-testid="chart-last-candle">
                  last {istTime(candles?.[candles.length - 1]?.ts)} IST
                </span>
              }
            >
              <LiveChartWidget
                candles={candles ?? []}
                vwap={vwapSeries}
                ema20={ema20}
                ema50={ema50}
                supports={supports}
                resistances={resistances}
                signal={activeForSymbol}
              />
            </Panel>

            <Panel title="Market indicators" testid="indicators-panel">
              <MarketIndicatorsWidget state={state} />
            </Panel>
          </div>

          <div className="space-y-4 lg:col-span-4">
            <Panel title="Direction engine" testid="direction-panel">
              {state ? (
                <div className="space-y-3">
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <p
                        className={`font-heading text-2xl font-bold tracking-tight ${
                          state.direction === "BULLISH"
                            ? "text-emerald-400"
                            : state.direction === "BEARISH"
                              ? "text-rose-400"
                              : "text-slate-400"
                        }`}
                        data-testid="direction-value"
                      >
                        {statusLabel(state.direction)}
                      </p>
                      <p className="font-mono text-[11px] text-slate-500">
                        evaluated {istTime(state.ts)} IST · {state.evaluation_ms} ms
                      </p>
                    </div>
                    <span
                      className="font-mono text-xl font-bold tabular-nums text-slate-200"
                      data-testid="direction-score"
                    >
                      {state.display_score}
                      <span className="text-sm text-slate-500">/100</span>
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        state.direction === "BEARISH" ? "bg-rose-500" : "bg-emerald-500"
                      }`}
                      style={{ width: `${Math.min(100, state.display_score)}%` }}
                    />
                  </div>
                  {state.no_trade_reason ? (
                    <p
                      className="rounded border border-slate-700/60 bg-slate-900/60 px-2.5 py-2 text-[11px] leading-relaxed text-slate-400"
                      data-testid="direction-no-trade-reason"
                    >
                      {state.no_trade_reason}
                    </p>
                  ) : null}
                </div>
              ) : (
                <EmptyState title="Engine warming up" body="The first evaluation cycle runs within a few seconds." testid="direction-empty" />
              )}
            </Panel>

            <Panel title="Paper account" testid="paper-summary-panel"
              right={
                <Link to="/paper-trading" className={buttonVariants({ variant: "ghost", size: "xs" })} data-testid="paper-trading-link">
                  Open
                </Link>
              }
            >
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Equity" value={`₹${num(account?.equity ?? 0, 0)}`} testid="paper-equity" />
                <Metric
                  label="Day P&L"
                  value={`₹${num(account?.daily_pnl ?? 0, 0)}`}
                  tone={(account?.daily_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
                  testid="paper-daily-pnl"
                />
                <Metric label="Open positions" value={num(account?.open_positions ?? 0, 0)} testid="paper-open-count" />
                <Metric
                  label="Drawdown"
                  value={`${num(account?.drawdown_pct ?? 0, 2)}%`}
                  testid="paper-drawdown"
                />
              </div>
              {account?.risk_blocked_reason ? (
                <p
                  className="mt-2 rounded border border-rose-500/30 bg-rose-950/40 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-rose-300"
                  data-testid="risk-blocked-banner"
                >
                  {account.risk_blocked_reason}
                </p>
              ) : null}
            </Panel>

            <Panel title="Recent signals" testid="recent-signals-panel">
              {recent && recent.length > 0 ? (
                <div className="-mx-4 -mb-4" data-testid="recent-signals-list">
                  {recent.map((s) => (
                    <SignalMiniRow key={s.id} signal={s} />
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No signals yet"
                  body="Signals appear here as soon as a setup clears direction, option-quality, risk/reward and risk-limit checks."
                  testid="recent-signals-empty"
                />
              )}
            </Panel>

            <Panel title="Other underlying" testid="other-symbols-panel">
              <div className="space-y-2">
                {(states ?? [])
                  .filter((s) => s.symbol !== symbol)
                  .map((s) => (
                    <button
                      key={s.symbol}
                      type="button"
                      onClick={() => setSymbol(s.symbol)}
                      className="flex w-full items-center justify-between rounded-md border border-slate-800/70 bg-slate-900/40 px-3 py-2 text-left transition-colors duration-150 hover:border-slate-700"
                      data-testid={`switch-symbol-${s.symbol}`}
                    >
                      <span className="font-mono text-[11px] text-slate-300">
                        {SYMBOL_LABEL[s.symbol] ?? s.symbol}
                      </span>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {statusLabel(s.direction)} {s.display_score}/100
                      </Badge>
                    </button>
                  ))}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </PageShell>
  );
}

/** Client-side overlays for the chart only — the engine's authoritative values come from
 *  the backend indicator bundle shown in the indicators panel. */
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
