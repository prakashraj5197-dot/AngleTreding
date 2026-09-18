import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { istDateTime, num, statusLabel, STATUS_TONE } from "@/lib/format";
import type { BacktestJob, BacktestTrade, DatasetEntry } from "@/lib/types";

const SYMBOL_OPTS: Record<string, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY" };
const TF_OPTS: Record<string, string> = { "5m": "5 minutes (signal)", "15m": "15 minutes", "1m": "1 minute" };
const STRATEGIES: Record<string, string> = { "QuantPulse Momentum": "QuantPulse Momentum (multi-factor)" };

export default function Backtesting() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("NIFTY");
  const [timeframe, setTimeframe] = useState("5m");
  const [strategy, setStrategy] = useState("QuantPulse Momentum");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [capital, setCapital] = useState("500000");
  const [riskPct, setRiskPct] = useState("1");
  const [slippage, setSlippage] = useState("0.10");
  const [brokerage, setBrokerage] = useState("20");
  const [charges, setCharges] = useState("0.05");
  const [conservative, setConservative] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: datasets } = useQuery({
    queryKey: ["backtest-dataset"],
    queryFn: () => apiGet<{ datasets: DatasetEntry[] }>("/backtest/dataset"),
    retry: false,
  });
  const { data: jobs } = useQuery({
    queryKey: ["backtest-jobs"],
    queryFn: () => apiGet<BacktestJob[]>("/backtest/jobs?limit=12"),
    refetchInterval: 3000,
    retry: false,
  });
  const activeJob = jobs?.find((j) => j.id === jobId) ?? jobs?.[0] ?? null;
  const { data: trades } = useQuery({
    queryKey: ["backtest-trades", activeJob?.id, activeJob?.status],
    queryFn: () => apiGet<BacktestTrade[]>(`/backtest/jobs/${activeJob?.id}/trades?limit=300`),
    enabled: !!activeJob && activeJob.status === "COMPLETED",
    retry: false,
  });

  const ds = datasets?.datasets.find((d) => d.symbol === symbol && d.timeframe === timeframe);
  const dsFrom = ds?.from?.slice(0, 10) ?? "";
  const dsTo = ds?.to?.slice(0, 10) ?? "";

  const run = useMutation({
    mutationFn: () =>
      apiPost<BacktestJob>("/backtest/run", {
        symbol,
        from_date: fromDate || dsFrom,
        to_date: toDate || dsTo,
        timeframe,
        strategy,
        initial_capital: Number(capital),
        risk_per_trade_pct: Number(riskPct),
        slippage_pct: Number(slippage),
        brokerage_per_order: Number(brokerage),
        charges_pct: Number(charges),
        conservative_same_candle_rule: conservative,
      }),
    onSuccess: (job) => {
      setJobId(job.id);
      toast.success("Backtest queued — running in the background.");
      void qc.invalidateQueries({ queryKey: ["backtest-jobs"] });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      toast.error(typeof detail === "string" ? detail : "Could not start the backtest.");
    },
  });

  const m = activeJob?.metrics ?? null;
  const equity = (activeJob?.equity_curve ?? []).map((p) => ({
    t: p.t.slice(0, 10),
    equity: p.equity,
  }));
  const split = (activeJob?.dataset_info?.split_60_20_20 ?? null) as Record<string, string[]> | null;

  return (
    <PageShell
      title="Backtesting Engine"
      subtitle="Replays the exact live strategy over stored history, candle close by candle close. Decisions at time T use only data ≤ T; option fills are modelled with slippage, brokerage and exchange charges, and gross vs net P&L is always reported separately."
      testid="backtesting-page"
    >
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-12">
          <Panel title="Configuration" className="lg:col-span-4" testid="backtest-config-panel">
            <div className="space-y-3">
              <Field label="Instrument">
                <Select value={symbol} onValueChange={(v: string) => setSymbol(v)}>
                  <SelectTrigger size="sm" data-testid="backtest-symbol">
                    <SelectValue>{(v) => SYMBOL_OPTS[v as string] ?? "Select"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SYMBOL_OPTS).map(([v, l]) => (
                      <SelectItem key={v} value={v}>{l}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Timeframe">
                <Select value={timeframe} onValueChange={(v: string) => setTimeframe(v)}>
                  <SelectTrigger size="sm" data-testid="backtest-timeframe">
                    <SelectValue>{(v) => TF_OPTS[v as string] ?? "Select"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(TF_OPTS).map(([v, l]) => (
                      <SelectItem key={v} value={v}>{l}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Strategy">
                <Select value={strategy} onValueChange={(v: string) => setStrategy(v)}>
                  <SelectTrigger size="sm" data-testid="backtest-strategy">
                    <SelectValue>{(v) => STRATEGIES[v as string] ?? "Select"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(STRATEGIES).map(([v, l]) => (
                      <SelectItem key={v} value={v}>{l}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="From (IST)">
                  <Input type="date" value={fromDate || dsFrom} onChange={(e) => setFromDate(e.target.value)} data-testid="backtest-from-date" />
                </Field>
                <Field label="To (IST)">
                  <Input type="date" value={toDate || dsTo} onChange={(e) => setToDate(e.target.value)} data-testid="backtest-to-date" />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Initial capital ₹">
                  <Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} data-testid="backtest-capital" />
                </Field>
                <Field label="Risk / trade %">
                  <Input type="number" step="0.1" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} data-testid="backtest-risk-pct" />
                </Field>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Field label="Slippage %">
                  <Input type="number" step="0.01" value={slippage} onChange={(e) => setSlippage(e.target.value)} data-testid="backtest-slippage" />
                </Field>
                <Field label="Brokerage ₹">
                  <Input type="number" value={brokerage} onChange={(e) => setBrokerage(e.target.value)} data-testid="backtest-brokerage" />
                </Field>
                <Field label="Charges %">
                  <Input type="number" step="0.01" value={charges} onChange={(e) => setCharges(e.target.value)} data-testid="backtest-charges" />
                </Field>
              </div>
              <label className="flex items-start gap-2 rounded-md border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                <Checkbox
                  checked={conservative}
                  onCheckedChange={(c: boolean) => setConservative(Boolean(c))}
                  data-testid="backtest-conservative-toggle"
                />
                <span className="text-[11px] leading-relaxed text-slate-400">
                  Conservative same-candle rule — when SL and target both fall inside one
                  candle, treat the stop-loss as hit first.
                </span>
              </label>
              <Button
                className="w-full"
                onClick={() => run.mutate()}
                disabled={run.isPending}
                data-testid="backtest-run-btn"
              >
                {run.isPending ? "Queuing…" : "Run backtest"}
              </Button>
              {ds ? (
                <p className="font-mono text-[10px] leading-relaxed text-slate-500" data-testid="dataset-availability">
                  Dataset: {num(ds.candles, 0)} {ds.timeframe} candles, {dsFrom} → {dsTo}
                </p>
              ) : (
                <p className="font-mono text-[10px] text-amber-400" data-testid="dataset-missing">
                  No stored history for this symbol/timeframe yet.
                </p>
              )}
            </div>
          </Panel>

          <div className="space-y-4 lg:col-span-8">
            <Panel
              title="Job status"
              testid="backtest-status-panel"
              right={
                activeJob ? (
                  <Badge className={`border font-mono text-[10px] ${STATUS_TONE[activeJob.status] ?? ""}`} data-testid="backtest-job-status">
                    {activeJob.status}
                  </Badge>
                ) : null
              }
            >
              {!activeJob ? (
                <EmptyState
                  title="No backtest run yet"
                  body="Configure the run on the left and press Run backtest. Large datasets execute in the background with live job status."
                  testid="backtest-empty"
                />
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[11px] text-slate-400">
                    <span data-testid="backtest-job-meta">
                      {String(activeJob.params.symbol)} · {String(activeJob.params.timeframe)} ·{" "}
                      {String(activeJob.params.from_date)} → {String(activeJob.params.to_date)}
                    </span>
                    <span>{istDateTime(activeJob.created_at)} IST</span>
                  </div>
                  {activeJob.status === "RUNNING" || activeJob.status === "QUEUED" ? (
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-800" data-testid="backtest-progress">
                      <div
                        className="h-full rounded-full bg-sky-500 transition-all duration-500"
                        style={{ width: `${Math.max(3, activeJob.progress)}%` }}
                      />
                    </div>
                  ) : null}
                  {activeJob.error ? (
                    <p className="rounded border border-rose-500/30 bg-rose-950/40 px-2.5 py-2 text-[11px] text-rose-300" data-testid="backtest-error">
                      {activeJob.error}
                    </p>
                  ) : null}
                  {activeJob.warnings.length > 0 ? (
                    <ul className="space-y-1" data-testid="backtest-assumptions">
                      {activeJob.warnings.map((w, i) => (
                        <li key={i} className="rounded border border-amber-500/20 bg-amber-950/20 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-200/80">
                          {w}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {split ? (
                    <div className="grid grid-cols-3 gap-2" data-testid="dataset-split-disclosure">
                      {Object.entries(split).map(([k, v]) => (
                        <Metric key={k} label={k.replace(/_/g, " ")} value={`${v[0]} → ${v[1]}`} testid={`split-${k}`} />
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </Panel>

            {m ? (
              <>
                <Panel title="Performance summary" testid="backtest-metrics-panel">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                    <Metric label="Total trades" value={num(m.total_trades, 0)} testid="metric-total-trades" />
                    <Metric label="Win rate" value={`${num(m.win_rate, 1)}%`} testid="metric-win-rate" />
                    <Metric label="Wins / losses" value={`${m.wins} / ${m.losses}`} testid="metric-wins-losses" />
                    <Metric label="Profit factor" value={num(m.profit_factor, 2)} testid="metric-profit-factor" />
                    <Metric label="Avg R" value={num(m.avg_r, 3)} testid="metric-avg-r" />
                    <Metric label="Max drawdown" value={`₹${num(m.max_drawdown, 0)} (${num(m.max_drawdown_pct, 2)}%)`} testid="metric-max-dd" />
                    <Metric label="Gross P&L" value={`₹${num(m.gross_pnl, 0)}`} tone={m.gross_pnl >= 0 ? "text-emerald-300" : "text-rose-300"} testid="metric-gross-pnl" />
                    <Metric label="Total costs" value={`₹${num(m.total_costs, 0)}`} tone="text-amber-300" testid="metric-costs" />
                    <Metric label="Net P&L" value={`₹${num(m.net_pnl, 0)}`} tone={m.net_pnl >= 0 ? "text-emerald-300" : "text-rose-300"} testid="metric-net-pnl" />
                    <Metric label="Avg profit" value={`₹${num(m.avg_profit, 0)}`} testid="metric-avg-profit" />
                    <Metric label="Avg loss" value={`₹${num(m.avg_loss, 0)}`} testid="metric-avg-loss" />
                    <Metric label="Largest win / loss" value={`₹${num(m.largest_win, 0)} / ₹${num(m.largest_loss, 0)}`} testid="metric-largest" />
                    <Metric label="CALL trades" value={`${m.call_trades} · ₹${num(m.call_pnl, 0)}`} testid="metric-call" />
                    <Metric label="PUT trades" value={`${m.put_trades} · ₹${num(m.put_pnl, 0)}`} testid="metric-put" />
                  </div>
                </Panel>

                <Panel title="Equity curve (net of costs)" testid="equity-curve-panel">
                  {equity.length > 1 ? (
                    <div className="h-[260px]" data-testid="equity-curve-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={equity} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                          <defs>
                            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#38BDF8" stopOpacity={0.45} />
                              <stop offset="100%" stopColor="#38BDF8" stopOpacity={0.02} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid stroke="#1E293B" strokeDasharray="2 4" vertical={false} />
                          <XAxis dataKey="t" tick={{ fill: "#64748B", fontSize: 10 }} stroke="#1E293B" interval={Math.max(0, Math.floor(equity.length / 8))} />
                          <YAxis tick={{ fill: "#64748B", fontSize: 10 }} stroke="#1E293B" tickFormatter={(v: number) => num(v, 0)} width={70} />
                          <Tooltip
                            contentStyle={{ background: "#161F30", border: "1px solid #334155", borderRadius: 6, fontSize: 11 }}
                            formatter={(value: number) => [`₹${num(value, 0)}`, "Equity"]}
                            labelFormatter={(label: string) => label}
                          />
                          <Area type="monotone" dataKey="equity" stroke="#38BDF8" strokeWidth={1.6} fill="url(#eq)" isAnimationActive={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <EmptyState title="No closed trades in this run" body="The strategy found no qualifying setup in the selected window — a valid outcome, not an error." testid="equity-empty" />
                  )}
                </Panel>

                {m.monthly.length > 0 ? (
                  <Panel title="Monthly performance" testid="monthly-panel">
                    <div className="h-[220px]" data-testid="monthly-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={m.monthly} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                          <CartesianGrid stroke="#1E293B" strokeDasharray="2 4" vertical={false} />
                          <XAxis dataKey="month" tick={{ fill: "#64748B", fontSize: 10 }} stroke="#1E293B" />
                          <YAxis tick={{ fill: "#64748B", fontSize: 10 }} stroke="#1E293B" tickFormatter={(v: number) => num(v, 0)} width={70} />
                          <Tooltip
                            contentStyle={{ background: "#161F30", border: "1px solid #334155", borderRadius: 6, fontSize: 11 }}
                            formatter={(value: number, name: string) => [name === "pnl" ? `₹${num(value, 0)}` : num(value, 0), name === "pnl" ? "Net P&L" : name]}
                            labelFormatter={(label: string) => label}
                          />
                          <Bar dataKey="pnl" isAnimationActive={false}>
                            {m.monthly.map((row, i) => (
                              <Cell key={i} fill={row.pnl >= 0 ? "#10B981" : "#EF4444"} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </Panel>
                ) : null}

                <div className="grid gap-4 lg:grid-cols-2">
                  <Panel title="Performance by market regime" testid="regime-panel">
                    <StatTable rows={m.regime_stats.map((r) => ({ key: r.regime, ...r }))} keyLabel="Regime" />
                  </Panel>
                  <Panel title="Dataset segment (60 / 20 / 20)" testid="segment-panel">
                    <StatTable rows={m.segment_stats.map((r) => ({ key: r.segment, ...r }))} keyLabel="Segment" />
                  </Panel>
                </div>

                <Panel title={`Trade log (${trades?.length ?? 0} of ${activeJob?.trades_count ?? 0})`} testid="trade-log-panel">
                  {trades && trades.length > 0 ? (
                    <div className="max-h-[420px] overflow-y-auto">
                      <Table data-testid="trade-log-table">
                        <TableHeader>
                          <TableRow>
                            <TableHead>#</TableHead>
                            <TableHead>Entry (IST)</TableHead>
                            <TableHead>Exit (IST)</TableHead>
                            <TableHead>Contract</TableHead>
                            <TableHead className="text-right">Qty</TableHead>
                            <TableHead className="text-right">Entry</TableHead>
                            <TableHead className="text-right">Exit</TableHead>
                            <TableHead className="text-right">SL / Target</TableHead>
                            <TableHead className="text-right">Net P&L</TableHead>
                            <TableHead className="text-right">R</TableHead>
                            <TableHead>Exit reason</TableHead>
                            <TableHead>Segment</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {trades.map((t) => (
                            <TableRow key={t.n} className="font-mono text-[11px]" data-testid={`trade-row-${t.n}`}>
                              <TableCell className="text-slate-500">{t.n}</TableCell>
                              <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(t.entry_ts)}</TableCell>
                              <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(t.exit_ts)}</TableCell>
                              <TableCell className="whitespace-nowrap text-slate-200">
                                {num(t.strike, 0)} {t.side}
                              </TableCell>
                              <TableCell className="text-right">{num(t.qty, 0)}</TableCell>
                              <TableCell className="text-right">{num(t.entry_price)}</TableCell>
                              <TableCell className="text-right">{num(t.exit_price)}</TableCell>
                              <TableCell className="text-right text-slate-400">
                                {num(t.sl)} / {num(t.target)}
                              </TableCell>
                              <TableCell className={`text-right ${t.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                                ₹{num(t.pnl, 0)}
                              </TableCell>
                              <TableCell className="text-right">{num(t.r_multiple, 2)}</TableCell>
                              <TableCell className="text-[10px] text-slate-400">{statusLabel(t.exit_reason)}</TableCell>
                              <TableCell className="text-[10px] text-slate-500">{t.segment}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : (
                    <EmptyState title="No trades to list" body="This run produced no completed trades." testid="trade-log-empty" />
                  )}
                </Panel>
              </>
            ) : null}

            <Panel title="Previous runs" testid="previous-runs-panel">
              {jobs && jobs.length > 0 ? (
                <Table data-testid="jobs-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Started (IST)</TableHead>
                      <TableHead>Instrument</TableHead>
                      <TableHead>Range</TableHead>
                      <TableHead className="text-right">Trades</TableHead>
                      <TableHead className="text-right">Net P&L</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {jobs.map((j) => (
                      <TableRow key={j.id} className="font-mono text-[11px]" data-testid={`job-row-${j.id}`}>
                        <TableCell className="text-slate-400">{istDateTime(j.created_at)}</TableCell>
                        <TableCell className="text-slate-200">
                          {String(j.params.symbol)} {String(j.params.timeframe)}
                        </TableCell>
                        <TableCell className="text-slate-400">
                          {String(j.params.from_date)} → {String(j.params.to_date)}
                        </TableCell>
                        <TableCell className="text-right">{num(j.trades_count, 0)}</TableCell>
                        <TableCell className={`text-right ${(j.metrics?.net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                          {j.metrics ? `₹${num(j.metrics.net_pnl, 0)}` : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge className={`border text-[10px] ${STATUS_TONE[j.status] ?? ""}`}>{j.status}</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button size="xs" variant="ghost" onClick={() => setJobId(j.id)} data-testid={`view-job-${j.id}`}>
                            View
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState title="No previous runs" testid="jobs-empty" />
              )}
            </Panel>
          </div>
        </div>
      </div>
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

function StatTable({
  rows,
  keyLabel,
}: {
  rows: Array<{ key: string; trades: number; wins: number; pnl: number; win_rate: number }>;
  keyLabel: string;
}) {
  if (rows.length === 0) return <EmptyState title="No data" testid="stat-table-empty" />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{keyLabel}</TableHead>
          <TableHead className="text-right">Trades</TableHead>
          <TableHead className="text-right">Win rate</TableHead>
          <TableHead className="text-right">Net P&L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key} className="font-mono text-[11px]" data-testid={`stat-row-${r.key}`}>
            <TableCell className="text-slate-200">{r.key.replace(/_/g, " ")}</TableCell>
            <TableCell className="text-right">{r.trades}</TableCell>
            <TableCell className="text-right">{num(r.win_rate, 1)}%</TableCell>
            <TableCell className={`text-right ${r.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
              ₹{num(r.pnl, 0)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
