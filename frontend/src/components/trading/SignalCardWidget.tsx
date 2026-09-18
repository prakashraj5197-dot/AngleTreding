import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, X } from "lucide-react";
import { toast } from "sonner";
import { apiPost, ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, Metric } from "@/components/layout/PageShell";
import { SignalLevelBar } from "@/components/trading/LiveChartWidget";
import { expiryLabel, inr, istDateTime, num, statusLabel, STATUS_TONE } from "@/lib/format";
import type { EngineState, Factor, Signal } from "@/lib/types";

export function FactorList({ factors, testid }: { factors: Factor[]; testid?: string }) {
  if (factors.length === 0) return null;
  return (
    <ul className="space-y-1.5" data-testid={testid ?? "factor-list"}>
      {factors.map((f) => {
        const Icon = f.state === "bull" ? Check : f.state === "bear" ? X : Minus;
        const tone =
          f.state === "bull" ? "text-emerald-400" : f.state === "bear" ? "text-rose-400" : "text-slate-500";
        return (
          <li
            key={f.key}
            className="flex items-start gap-2 rounded-md border border-slate-800/60 bg-slate-900/40 px-2.5 py-2"
            data-testid={`factor-row-${f.key}`}
          >
            <Icon className={`mt-0.5 size-3.5 shrink-0 ${tone}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] font-semibold text-slate-200">{f.label}</span>
                <span className={`font-mono text-[11px] tabular-nums ${tone}`}>
                  {f.score >= 0 ? "+" : ""}
                  {num(f.score, 1)}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{f.value}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function NoTradeCard({ state, testid }: { state?: EngineState | null; testid?: string }) {
  const reason = state?.no_trade_reason ?? "Waiting for the first evaluation cycle to complete.";
  return (
    <div
      className="rounded-lg border border-slate-700/60 bg-gradient-to-br from-slate-900/80 to-[#111722] p-4"
      data-testid={testid ?? "no-trade-card"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="flex items-center gap-2 font-heading text-base font-bold tracking-tight text-slate-300"
          data-testid="no-active-signal-headline"
        >
          <span className="size-2.5 rounded-full bg-slate-500" />
          {state?.direction === "SIDEWAYS" || state?.direction === "NO_TRADE"
            ? "NO TRADE"
            : "NO ACTIVE SIGNAL"}
        </span>
        {state ? (
          <Badge variant="outline" className="font-mono text-[10px]" data-testid="no-trade-direction-badge">
            {statusLabel(state.direction)} · {state.display_score}/100
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-400" data-testid="no-trade-reason">
        <span className="font-semibold text-slate-300">Reason: </span>
        {reason}
      </p>
      {state && state.factors.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Factor breakdown
          </p>
          <FactorList factors={state.factors} testid="no-trade-factors" />
        </div>
      ) : null}
    </div>
  );
}

export function SignalCardWidget({
  signal,
  state,
  compactView,
}: {
  signal?: Signal | null;
  state?: EngineState | null;
  compactView?: boolean;
}) {
  const qc = useQueryClient();
  const execute = useMutation({
    mutationFn: (id: string) => apiPost(`/paper/execute/${id}`),
    onSuccess: () => {
      toast.success("Paper position opened — virtual capital only, no real order placed.");
      void qc.invalidateQueries({ queryKey: ["paper-account"] });
      void qc.invalidateQueries({ queryKey: ["paper-positions"] });
      void qc.invalidateQueries({ queryKey: ["signals"] });
      void qc.invalidateQueries({ queryKey: ["active-signals"] });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      toast.error(detail ?? "Could not open the paper position.");
    },
  });

  if (!signal) return <NoTradeCard state={state} />;

  const isCall = signal.option_type === "CE";
  const tone = isCall ? "emerald" : "rose";

  return (
    <div
      className={`animate-slide-up rounded-lg border p-4 ${
        isCall
          ? "border-emerald-500/40 bg-gradient-to-br from-emerald-950/40 to-[#111722]"
          : "border-rose-500/40 bg-gradient-to-br from-rose-950/40 to-[#111722]"
      }`}
      data-testid="signal-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p
            className={`flex items-center gap-2 font-heading text-lg font-bold tracking-tight ${
              isCall ? "text-emerald-300" : "text-rose-300"
            }`}
            data-testid="signal-headline"
          >
            <span className={`size-2.5 rounded-full ${isCall ? "bg-emerald-400" : "bg-rose-400"}`} />
            {isCall ? "BUY CALL" : "BUY PUT"}
            <span className="font-mono text-xs font-normal text-slate-400">{isCall ? "▲" : "▼"}</span>
          </p>
          <p className="mt-1 font-mono text-sm font-semibold text-slate-100" data-testid="signal-contract">
            {signal.symbol} {num(signal.strike, 0)} {signal.option_type}
          </p>
          <p className="font-mono text-[11px] text-slate-500" data-testid="signal-expiry">
            Expiry: {expiryLabel(signal.expiry)} · Spot at signal {num(signal.spot_at_signal, 2)}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Badge
            className={`border font-mono text-[10px] ${STATUS_TONE[signal.status] ?? ""}`}
            data-testid="signal-status-badge"
          >
            {statusLabel(signal.status)}
          </Badge>
          <span className="font-mono text-[10px] text-slate-500" data-testid="signal-generated-at">
            {istDateTime(signal.created_at)} IST
          </span>
          <span className="font-mono text-[10px] text-slate-500" data-testid="signal-strategy-version">
            {signal.strategy_name} v{signal.strategy_version}
          </span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric
          label="Entry range"
          value={`${inr(signal.entry_min)}–${num(signal.entry_max)}`}
          testid="signal-entry-range"
        />
        <Metric label="Stop loss" value={inr(signal.stop_loss)} tone="text-rose-300" testid="signal-stop-loss" />
        <Metric label="Target 1" value={inr(signal.target1)} tone="text-emerald-300" testid="signal-target1" />
        <Metric label="Target 2" value={inr(signal.target2)} tone="text-emerald-200" testid="signal-target2" />
        <Metric
          label="Risk / reward"
          value={`1 : ${num(signal.risk_reward, 2)}`}
          sub={`risk ${inr(signal.risk_points)}/unit`}
          testid="signal-risk-reward"
        />
        <Metric
          label="Strength"
          value={`${signal.score}/100`}
          sub={signal.strength}
          tone={signal.score >= 80 ? "text-emerald-300" : "text-sky-300"}
          testid="signal-strength"
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Option LTP" value={inr(signal.option_ltp)} testid="signal-option-ltp" />
        <Metric
          label="Entry fill"
          value={signal.filled ? inr(signal.entry_price) : "Awaiting fill"}
          sub={signal.filled ? "inside range" : "must trade inside entry band"}
          testid="signal-entry-fill"
        />
        <Metric
          label="Max qty @ risk cap"
          value={signal.max_qty > 0 ? num(signal.max_qty, 0) : "—"}
          sub="risk ÷ (entry − SL), lot-adjusted"
          testid="signal-max-qty"
        />
        <Metric
          label="Result"
          value={statusLabel(signal.result)}
          sub={signal.pnl_points !== null ? `${signal.pnl_points >= 0 ? "+" : ""}${num(signal.pnl_points)} pts` : undefined}
          tone={signal.result === "WIN" ? "text-emerald-300" : signal.result === "LOSS" ? "text-rose-300" : undefined}
          testid="signal-result"
        />
      </div>

      <SignalLevelBar signal={signal} />

      {!compactView ? (
        <div className="mt-4">
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Why this signal fired
          </p>
          <FactorList factors={signal.reasons} testid="signal-factors" />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          onClick={() => execute.mutate(signal.id)}
          disabled={execute.isPending || signal.paper_executed || !["ACTIVE", "TARGET1_HIT"].includes(signal.status)}
          data-testid="execute-paper-trade-button"
        >
          {signal.paper_executed ? "Executed in paper account" : execute.isPending ? "Opening…" : "Execute in paper account"}
        </Button>
        <span className="font-mono text-[10px] text-slate-500">
          Virtual order only — the system never routes to a real broker.
        </span>
      </div>
    </div>
  );
}

export function SignalMiniRow({ signal, onSelect }: { signal: Signal; onSelect?: (s: Signal) => void }) {
  const isCall = signal.option_type === "CE";
  return (
    <button
      type="button"
      onClick={() => onSelect?.(signal)}
      className="flex w-full items-center justify-between gap-3 border-b border-slate-800/70 px-3 py-2 text-left transition-colors duration-150 last:border-0 hover:bg-slate-800/40"
      data-testid={`signal-mini-row-${signal.id}`}
    >
      <span className="flex min-w-0 items-center gap-2">
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${
            isCall ? "bg-emerald-900/60 text-emerald-300" : "bg-rose-900/60 text-rose-300"
          }`}
        >
          {signal.option_type}
        </span>
        <span className="truncate font-mono text-[11px] text-slate-200">
          {signal.symbol} {num(signal.strike, 0)}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-2 font-mono text-[10px]">
        <span className="text-slate-400">{signal.score}/100</span>
        <Badge className={`border text-[9px] ${STATUS_TONE[signal.status] ?? ""}`}>
          {statusLabel(signal.status)}
        </Badge>
      </span>
    </button>
  );
}

export function EmptySignals({ testid }: { testid?: string }) {
  return (
    <EmptyState
      title="No signals recorded yet"
      body="The engine evaluates the market continuously and only stores a signal when direction, option quality, risk/reward and risk limits all pass. NO TRADE is a valid outcome."
      testid={testid}
    />
  );
}
