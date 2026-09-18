import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiGet, apiPost } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { FactorList } from "@/components/trading/SignalCardWidget";
import { expiryLabel, inr, istDateTime, num, statusLabel, STATUS_TONE } from "@/lib/format";
import type { Signal, SignalAnalytics } from "@/lib/types";

const ANY = "__any__";
const LABEL = (m: Record<string, string>) => (v: string) => m[v] ?? v;

const STATUS_OPTS: Record<string, string> = {
  [ANY]: "Any status",
  ACTIVE: "Active",
  TARGET1_HIT: "Target 1 hit",
  TARGET2_HIT: "Target 2 hit",
  STOP_LOSS: "Stop loss",
  EXPIRED: "Expired",
  CANCELLED: "Cancelled",
};
const RESULT_OPTS: Record<string, string> = {
  [ANY]: "Any result",
  OPEN: "Open",
  WIN: "Win",
  LOSS: "Loss",
  MISSED_ENTRY: "Missed entry",
  FLAT: "Flat",
};
const SYMBOL_OPTS: Record<string, string> = { [ANY]: "All symbols", NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY" };
const TYPE_OPTS: Record<string, string> = { [ANY]: "CE + PE", CE: "CALL (CE)", PE: "PUT (PE)" };

export default function Signals() {
  const qc = useQueryClient();
  const [status, setStatus] = useState(ANY);
  const [result, setResult] = useState(ANY);
  const [symbol, setSymbol] = useState(ANY);
  const [optionType, setOptionType] = useState(ANY);
  const [minScore, setMinScore] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [selected, setSelected] = useState<Signal | null>(null);

  const params = new URLSearchParams({ limit: "200" });
  if (status !== ANY) params.set("status", status);
  if (result !== ANY) params.set("result", result);
  if (symbol !== ANY) params.set("symbol", symbol);
  if (optionType !== ANY) params.set("option_type", optionType);
  if (minScore) params.set("min_score", minScore);
  if (fromDate) params.set("from_date", fromDate);

  const { data: signals, isLoading } = useQuery({
    queryKey: ["signals", params.toString()],
    queryFn: () => apiGet<Signal[]>(`/signals?${params.toString()}`),
    refetchInterval: 6000,
    retry: false,
  });
  const { data: stats } = useQuery({
    queryKey: ["signal-analytics"],
    queryFn: () => apiGet<SignalAnalytics>("/signals/analytics"),
    refetchInterval: 10000,
    retry: false,
  });

  const cancel = useMutation({
    mutationFn: (id: string) => apiPost<Signal>(`/signals/${id}/cancel`),
    onSuccess: () => {
      toast.success("Signal cancelled.");
      void qc.invalidateQueries({ queryKey: ["signals"] });
      void qc.invalidateQueries({ queryKey: ["active-signals"] });
      setSelected(null);
    },
    onError: () => toast.error("Could not cancel that signal."),
  });

  const rows = signals ?? [];

  return (
    <PageShell
      title="Live Signals & History"
      subtitle="Every signal the engine has ever generated, with its full lifecycle, stored market snapshot and strategy version. Records are immutable — changing strategy parameters never rewrites history."
      testid="signals-page"
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Total signals" value={num(stats?.total_signals ?? 0, 0)} testid="stat-total-signals" />
          <Metric label="Active" value={num(stats?.active ?? 0, 0)} testid="stat-active" />
          <Metric label="Closed" value={num(stats?.closed ?? 0, 0)} testid="stat-closed" />
          <Metric label="Win rate" value={`${num(stats?.win_rate ?? 0, 1)}%`} testid="stat-win-rate" />
          <Metric label="Avg R" value={num(stats?.avg_r ?? 0, 2)} testid="stat-avg-r" />
          <Metric label="Profit factor" value={num(stats?.profit_factor ?? 0, 2)} testid="stat-profit-factor" />
          <Metric
            label="Net points"
            value={num(stats?.total_points ?? 0, 2)}
            tone={(stats?.total_points ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
            testid="stat-net-points"
          />
          <Metric label="Missed entries" value={num(stats?.no_fill ?? 0, 0)} testid="stat-missed" />
        </div>

        <Panel title="Filters" testid="signal-filters-panel">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Field label="Status">
              <Select value={status} onValueChange={(v: string) => setStatus(v)}>
                <SelectTrigger size="sm" data-testid="filter-status">
                  <SelectValue>{LABEL(STATUS_OPTS)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(STATUS_OPTS).map(([v, l]) => (
                    <SelectItem key={v} value={v}>{l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Result">
              <Select value={result} onValueChange={(v: string) => setResult(v)}>
                <SelectTrigger size="sm" data-testid="filter-result">
                  <SelectValue>{LABEL(RESULT_OPTS)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(RESULT_OPTS).map(([v, l]) => (
                    <SelectItem key={v} value={v}>{l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Symbol">
              <Select value={symbol} onValueChange={(v: string) => setSymbol(v)}>
                <SelectTrigger size="sm" data-testid="filter-symbol">
                  <SelectValue>{LABEL(SYMBOL_OPTS)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(SYMBOL_OPTS).map(([v, l]) => (
                    <SelectItem key={v} value={v}>{l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="CALL / PUT">
              <Select value={optionType} onValueChange={(v: string) => setOptionType(v)}>
                <SelectTrigger size="sm" data-testid="filter-option-type">
                  <SelectValue>{LABEL(TYPE_OPTS)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(TYPE_OPTS).map(([v, l]) => (
                    <SelectItem key={v} value={v}>{l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Min strength">
              <Input
                type="number"
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                placeholder="70"
                data-testid="filter-min-score"
              />
            </Field>
            <Field label="From date (IST)">
              <Input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                data-testid="filter-from-date"
              />
            </Field>
          </div>
        </Panel>

        <Panel
          title={`Signals (${rows.length})`}
          testid="signals-table-panel"
          right={
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                setStatus(ANY);
                setResult(ANY);
                setSymbol(ANY);
                setOptionType(ANY);
                setMinScore("");
                setFromDate("");
              }}
              data-testid="clear-filters-button"
            >
              Clear filters
            </Button>
          }
        >
          {isLoading ? (
            <p className="py-6 text-center text-xs text-slate-500" data-testid="signals-loading">Loading signals…</p>
          ) : rows.length === 0 ? (
            <EmptyState
              title="No signals match these filters"
              body="The engine records a signal only when direction, option quality, risk/reward and risk limits all pass. Clear the filters or wait for the next qualifying setup."
              testid="signals-empty"
            />
          ) : (
            <Table data-testid="signals-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Generated (IST)</TableHead>
                  <TableHead>Contract</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">SL</TableHead>
                  <TableHead className="text-right">T1 / T2</TableHead>
                  <TableHead className="text-right">R:R</TableHead>
                  <TableHead className="text-right">Strength</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">P&L pts</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((s) => (
                  <TableRow key={s.id} className="font-mono text-xs" data-testid={`signal-row-${s.id}`}>
                    <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(s.created_at)}</TableCell>
                    <TableCell className="whitespace-nowrap text-slate-200">
                      {s.symbol} {num(s.strike, 0)} {s.option_type}
                      <span className="ml-1 text-[10px] text-slate-500">{expiryLabel(s.expiry)}</span>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                          s.option_type === "CE" ? "bg-emerald-900/60 text-emerald-300" : "bg-rose-900/60 text-rose-300"
                        }`}
                      >
                        {s.option_type === "CE" ? "CALL" : "PUT"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">{num(s.entry_min)}–{num(s.entry_max)}</TableCell>
                    <TableCell className="text-right text-rose-300">{num(s.stop_loss)}</TableCell>
                    <TableCell className="text-right text-emerald-300">
                      {num(s.target1)} / {num(s.target2)}
                    </TableCell>
                    <TableCell className="text-right">1:{num(s.risk_reward, 2)}</TableCell>
                    <TableCell className="text-right">{s.score}</TableCell>
                    <TableCell>
                      <Badge className={`border text-[10px] ${STATUS_TONE[s.status] ?? ""}`}>
                        {statusLabel(s.status)}
                      </Badge>
                    </TableCell>
                    <TableCell
                      className={`text-right ${
                        (s.pnl_points ?? 0) > 0 ? "text-emerald-300" : (s.pnl_points ?? 0) < 0 ? "text-rose-300" : "text-slate-400"
                      }`}
                    >
                      {s.pnl_points === null ? "—" : num(s.pnl_points)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() => setSelected(s)}
                        data-testid={`signal-detail-button-${s.id}`}
                      >
                        Detail
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Panel>

        {stats && stats.setups.length > 0 ? (
          <Panel title="Setup performance" testid="setup-performance-panel">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Setup</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead className="text-right">Wins</TableHead>
                  <TableHead className="text-right">Win rate</TableHead>
                  <TableHead className="text-right">Net points</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.setups.map((r) => (
                  <TableRow key={r.setup} className="font-mono text-xs" data-testid={`setup-row-${r.setup.replace(/\s/g, "-")}`}>
                    <TableCell className="text-slate-200">{r.setup}</TableCell>
                    <TableCell className="text-right">{r.trades}</TableCell>
                    <TableCell className="text-right">{r.wins}</TableCell>
                    <TableCell className="text-right">{num(r.win_rate, 1)}%</TableCell>
                    <TableCell className={`text-right ${r.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {num(r.pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Panel>
        ) : null}
      </div>

      <Sheet open={selected !== null} onOpenChange={(o: boolean) => !o && setSelected(null)}>
        <SheetContent className="w-full overflow-y-auto border-slate-800 bg-[#0D131C] sm:max-w-xl" data-testid="signal-detail-sheet">
          {selected ? <SignalDetail signal={selected} onCancel={() => cancel.mutate(selected.id)} /> : null}
        </SheetContent>
      </Sheet>
    </PageShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</Label>
      {children}
    </div>
  );
}

function SignalDetail({ signal, onCancel }: { signal: Signal; onCancel: () => void }) {
  const snap = signal.snapshot as Record<string, Record<string, unknown>>;
  const option = (snap.option ?? {}) as Record<string, number | string>;
  const fno = (snap.fno ?? {}) as Record<string, number | string>;
  const risk = (snap.risk ?? {}) as Record<string, number | string>;
  const indicators = (snap.indicators ?? {}) as Record<string, unknown>;
  const rejected = (snap.rejected_candidates ?? []) as unknown as Array<{ strike: number; reasons: string[] }>;

  return (
    <>
      <SheetHeader>
        <SheetTitle className="font-mono text-sm" data-testid="detail-contract">
          {signal.symbol} {num(signal.strike, 0)} {signal.option_type} · {expiryLabel(signal.expiry)}
        </SheetTitle>
        <SheetDescription className="font-mono text-[11px]">
          {istDateTime(signal.created_at)} IST · {signal.strategy_name} v{signal.strategy_version} ·
          signal id {signal.id.slice(0, 8)}
        </SheetDescription>
      </SheetHeader>
      <div className="space-y-4 px-4 pb-6">
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Entry range" value={`${inr(signal.entry_min)}–${num(signal.entry_max)}`} testid="detail-entry" />
          <Metric label="Stop loss" value={inr(signal.stop_loss)} tone="text-rose-300" testid="detail-sl" />
          <Metric label="Target 1" value={inr(signal.target1)} tone="text-emerald-300" testid="detail-t1" />
          <Metric label="Target 2" value={inr(signal.target2)} tone="text-emerald-200" testid="detail-t2" />
          <Metric label="Risk / reward" value={`1 : ${num(signal.risk_reward, 2)}`} testid="detail-rr" />
          <Metric label="Strength" value={`${signal.score}/100 · ${signal.strength}`} testid="detail-strength" />
          <Metric label="Status" value={statusLabel(signal.status)} testid="detail-status" />
          <Metric
            label="Result"
            value={`${statusLabel(signal.result)}${signal.pnl_points !== null ? ` · ${num(signal.pnl_points)} pts` : ""}`}
            testid="detail-result"
          />
        </div>

        <Section title="Decision factors (stored at signal time)">
          <FactorList factors={signal.reasons} testid="detail-factors" />
        </Section>

        <Section title="Option snapshot">
          <KV data={{
            LTP: inr(Number(option.ltp)),
            Bid: inr(Number(option.bid)),
            Ask: inr(Number(option.ask)),
            "Spread %": `${num(Number(option.spread_pct), 3)}%`,
            Volume: num(Number(option.volume), 0),
            "Open interest": num(Number(option.oi), 0),
            "Change in OI": num(Number(option.change_in_oi), 0),
            IV: `${num(Number(option.iv) * 100, 2)}%`,
            Delta: num(Number(option.delta), 3),
            Gamma: num(Number(option.gamma), 6),
            Theta: num(Number(option.theta), 2),
            Vega: num(Number(option.vega), 2),
            "Contract score": num(Number(option.score), 1),
          }} testid="detail-option-snapshot" />
        </Section>

        <Section title="F&O structure">
          <KV data={{
            PCR: num(Number(fno.pcr), 3),
            "Max pain": num(Number(fno.max_pain), 0),
            "Futures price": num(Number(fno.futures), 2),
            Basis: num(Number(fno.basis), 2),
            "Futures ΔOI": num(Number(fno.fut_oi_change), 0),
            Regime: String(fno.regime ?? "—"),
          }} testid="detail-fno-snapshot" />
        </Section>

        <Section title="Indicator values">
          <KV data={{
            Spot: num(Number(indicators.spot), 2),
            VWAP: num(Number(indicators.vwap), 2),
            "EMA 20": num(Number(indicators.ema_fast), 2),
            "EMA 50": num(Number(indicators.ema_slow), 2),
            RSI: num(Number(indicators.rsi), 1),
            "MACD hist": num(Number(indicators.macd_hist), 2),
            ATR: num(Number(indicators.atr), 2),
            "Rel. volume": num(Number(indicators.rel_volume), 2),
          }} testid="detail-indicators" />
        </Section>

        <Section title="Risk sizing at signal time">
          <KV data={{
            Capital: inr(Number(risk.capital), 0),
            "Max risk / trade": inr(Number(risk.max_risk_per_trade), 0),
            "Lot size": num(Number(risk.lot_size), 0),
            "Max qty": num(Number(risk.max_qty), 0),
            "Trades today": num(Number(risk.trades_today), 0),
            "Consecutive losses": num(Number(risk.consecutive_losses), 0),
          }} testid="detail-risk" />
        </Section>

        {rejected.length > 0 ? (
          <Section title="Contracts rejected by filters">
            <ul className="space-y-1" data-testid="detail-rejected">
              {rejected.map((r, i) => (
                <li key={`${r.strike}-${i}`} className="rounded border border-slate-800/70 bg-slate-900/40 px-2 py-1.5 font-mono text-[10px] text-slate-400">
                  <span className="text-slate-300">{num(r.strike, 0)}</span> — {r.reasons.join("; ")}
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        <Section title="Lifecycle log">
          <ul className="space-y-1" data-testid="detail-event-log">
            {signal.event_log.map((e, i) => (
              <li key={i} className="rounded border border-slate-800/70 bg-slate-900/40 px-2 py-1.5 font-mono text-[10px]">
                <span className="text-slate-500">{istDateTime(e.ts)}</span>{" "}
                <span className="text-sky-300">{statusLabel(e.event)}</span>{" "}
                <span className="text-slate-400">{e.detail}</span>
              </li>
            ))}
          </ul>
        </Section>

        {["ACTIVE", "TARGET1_HIT"].includes(signal.status) ? (
          <Button variant="destructive" size="sm" onClick={onCancel} data-testid="cancel-signal-button">
            Cancel signal
          </Button>
        ) : null}
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function KV({ data, testid }: { data: Record<string, string>; testid?: string }) {
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2" data-testid={testid}>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-slate-200">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
