import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { compact, expiryLabel, inr, istTime, num, REGIME_LABEL } from "@/lib/format";
import type { ScannerResult, ScannerRow } from "@/lib/types";

const SYMBOL_OPTS: Record<string, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY" };

export default function OptionScanner() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState<string>("");
  const [strikes, setStrikes] = useState("10");
  const [sortByScore, setSortByScore] = useState(false);

  const query = new URLSearchParams({ strikes: strikes || "10" });
  if (expiry) query.set("expiry", expiry);

  const { data, isLoading } = useQuery({
    queryKey: ["scanner", symbol, query.toString()],
    queryFn: () => apiGet<ScannerResult>(`/scanner/${symbol}?${query.toString()}`),
    refetchInterval: 5000,
    retry: false,
  });

  const rows = data?.rows ?? [];
  const strikeList = [...new Set(rows.map((r) => r.strike))].sort((a, b) => a - b);
  const byStrike = new Map<number, { ce?: ScannerRow; pe?: ScannerRow }>();
  rows.forEach((r) => {
    const rec = byStrike.get(r.strike) ?? {};
    if (r.option_type === "CE") rec.ce = r;
    else rec.pe = r;
    byStrike.set(r.strike, rec);
  });

  return (
    <PageShell
      title="Option Chain Scanner"
      subtitle="Full CE/PE chain around the dynamic ATM strike with the engine's contract score. Contracts failing the configured liquidity, spread or premium floors are rejected and can never be selected for a signal."
      testid="option-scanner-page"
      actions={
        <>
          <Select value={symbol} onValueChange={(v: string) => { setSymbol(v); setExpiry(""); }}>
            <SelectTrigger className="w-[150px]" data-testid="scanner-symbol-selector">
              <SelectValue>{(v) => SYMBOL_OPTS[v as string] ?? "Select"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {Object.entries(SYMBOL_OPTS).map(([v, l]) => (
                <SelectItem key={v} value={v} data-testid={`scanner-symbol-${v}`}>{l}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={expiry || (data?.expiry ?? "")} onValueChange={(v: string) => setExpiry(v)}>
            <SelectTrigger className="w-[170px]" data-testid="expiry-selector">
              <SelectValue>{(v) => (v ? expiryLabel(v as string) : "Nearest expiry")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {(data?.expiries ?? []).map((e) => (
                <SelectItem key={e} value={e} data-testid={`expiry-option-${e}`}>
                  {expiryLabel(e)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-1.5">
            <Label className="font-mono text-[10px] uppercase text-slate-500">ATM ±</Label>
            <Input
              type="number"
              value={strikes}
              onChange={(e) => setStrikes(e.target.value)}
              className="w-16"
              data-testid="strike-range-input"
            />
          </div>
          <button
            type="button"
            onClick={() => setSortByScore((s) => !s)}
            className={`rounded-md border px-2.5 py-1.5 font-mono text-[11px] transition-colors duration-150 ${
              sortByScore
                ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
                : "border-slate-800 bg-slate-900/60 text-slate-400 hover:text-slate-200"
            }`}
            data-testid="toggle-rank-button"
          >
            {sortByScore ? "Ranked by score" : "Strike ladder"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Spot" value={num(data?.spot)} testid="scanner-spot" />
          <Metric label="ATM strike" value={num(data?.atm_strike, 0)} testid="scanner-atm" />
          <Metric
            label="PCR (OI)"
            value={num(data?.pcr, 3)}
            tone={(data?.pcr ?? 1) >= 1.1 ? "text-emerald-300" : (data?.pcr ?? 1) <= 0.9 ? "text-rose-300" : undefined}
            testid="scanner-pcr"
          />
          <Metric label="Max pain" value={num(data?.max_pain, 0)} testid="scanner-max-pain" />
          <Metric label="Futures" value={num(data?.futures_price)} sub={`basis ${num(data?.basis)}`} testid="scanner-futures" />
          <Metric label="Eligible" value={num(data?.eligible_count ?? 0, 0)} tone="text-emerald-300" testid="scanner-eligible-count" />
          <Metric label="Rejected" value={num(data?.rejected_count ?? 0, 0)} tone="text-rose-300" testid="scanner-rejected-count" />
          <Metric
            label="Regime"
            value={REGIME_LABEL[data?.regime ?? ""] ?? "—"}
            sub={`${istTime(data?.ts)} IST`}
            testid="scanner-regime"
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <RecommendedCard row={data?.recommended_ce ?? null} label="Top-ranked CALL" testid="recommended-ce-card" />
          <RecommendedCard row={data?.recommended_pe ?? null} label="Top-ranked PUT" testid="recommended-pe-card" />
        </div>

        <Panel
          title="Liquidity thresholds in force"
          testid="thresholds-panel"
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Metric label="Min OI" value={num(data?.thresholds.min_oi ?? 0, 0)} testid="threshold-min-oi" />
            <Metric label="Min volume" value={num(data?.thresholds.min_volume ?? 0, 0)} testid="threshold-min-volume" />
            <Metric label="Max spread" value={`${num(data?.thresholds.max_spread_pct ?? 0, 2)}%`} testid="threshold-max-spread" />
            <Metric label="Min premium" value={inr(data?.thresholds.min_premium ?? 0, 0)} testid="threshold-min-premium" />
            <Metric label="Min contract score" value={num(data?.thresholds.min_option_score ?? 0, 0)} testid="threshold-min-score" />
            <Metric label="Strike universe" value={`ATM ± ${num(data?.thresholds.atm_range ?? 0, 0)}`} testid="threshold-atm-range" />
          </div>
        </Panel>

        <Panel title={sortByScore ? "Ranked contracts" : "Option chain — CE | strike | PE"} testid="option-chain-panel">
          {isLoading ? (
            <p className="py-6 text-center text-xs text-slate-500" data-testid="scanner-loading">Loading option chain…</p>
          ) : rows.length === 0 ? (
            <EmptyState title="No contracts available" body="The provider returned no contracts for this expiry and strike window." testid="scanner-empty" />
          ) : sortByScore ? (
            <Table data-testid="ranked-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Rank</TableHead>
                  <TableHead>Contract</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">Spread</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">OI</TableHead>
                  <TableHead className="text-right">IV</TableHead>
                  <TableHead className="text-right">Delta</TableHead>
                  <TableHead>Verdict</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...rows]
                  .sort((a, b) => b.score - a.score)
                  .map((r, i) => (
                    <TableRow key={`${r.strike}-${r.option_type}`} className="font-mono text-xs" data-testid={`ranked-row-${r.strike}-${r.option_type}`}>
                      <TableCell className="text-slate-500">{i + 1}</TableCell>
                      <TableCell className="whitespace-nowrap text-slate-200">
                        {num(r.strike, 0)} {r.option_type}
                        <span className="ml-1 text-[10px] text-slate-500">{r.moneyness}</span>
                      </TableCell>
                      <TableCell className="text-right font-semibold text-sky-300">{num(r.score, 1)}</TableCell>
                      <TableCell className="text-right">{num(r.ltp)}</TableCell>
                      <TableCell className="text-right">{num(r.spread_pct, 2)}%</TableCell>
                      <TableCell className="text-right">{compact(r.volume)}</TableCell>
                      <TableCell className="text-right">{compact(r.open_interest)}</TableCell>
                      <TableCell className="text-right">{num(r.iv * 100, 1)}%</TableCell>
                      <TableCell className="text-right">{num(r.delta, 3)}</TableCell>
                      <TableCell>
                        <Verdict row={r} />
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-mono text-[11px]" data-testid="option-chain-table">
                <thead>
                  <tr className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500">
                    <th className="px-2 py-1.5 text-right">CE Score</th>
                    <th className="px-2 py-1.5 text-right">CE OI</th>
                    <th className="px-2 py-1.5 text-right">CE ΔOI</th>
                    <th className="px-2 py-1.5 text-right">CE Vol</th>
                    <th className="px-2 py-1.5 text-right">CE IV</th>
                    <th className="px-2 py-1.5 text-right">CE δ</th>
                    <th className="px-2 py-1.5 text-right">CE LTP</th>
                    <th className="px-2 py-1.5 text-center">Strike</th>
                    <th className="px-2 py-1.5 text-left">PE LTP</th>
                    <th className="px-2 py-1.5 text-left">PE δ</th>
                    <th className="px-2 py-1.5 text-left">PE IV</th>
                    <th className="px-2 py-1.5 text-left">PE Vol</th>
                    <th className="px-2 py-1.5 text-left">PE ΔOI</th>
                    <th className="px-2 py-1.5 text-left">PE OI</th>
                    <th className="px-2 py-1.5 text-left">PE Score</th>
                  </tr>
                </thead>
                <tbody>
                  {strikeList.map((strike) => {
                    const rec = byStrike.get(strike) ?? {};
                    const isAtm = strike === data?.atm_strike;
                    return (
                      <tr
                        key={strike}
                        className={`border-b border-slate-800/60 transition-colors duration-150 hover:bg-slate-800/30 ${
                          isAtm ? "bg-sky-500/5" : ""
                        }`}
                        data-testid={`chain-row-${strike}`}
                      >
                        <Td align="right" tone={rec.ce?.rejected ? "text-rose-400/70" : "text-sky-300"}>
                          {rec.ce ? num(rec.ce.score, 1) : "—"}
                        </Td>
                        <Td align="right">{rec.ce ? compact(rec.ce.open_interest) : "—"}</Td>
                        <Td align="right" tone={(rec.ce?.change_in_oi ?? 0) >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}>
                          {rec.ce ? compact(rec.ce.change_in_oi) : "—"}
                        </Td>
                        <Td align="right">{rec.ce ? compact(rec.ce.volume) : "—"}</Td>
                        <Td align="right">{rec.ce ? `${num(rec.ce.iv * 100, 1)}%` : "—"}</Td>
                        <Td align="right">{rec.ce ? num(rec.ce.delta, 2) : "—"}</Td>
                        <Td align="right" tone="text-emerald-300">{rec.ce ? num(rec.ce.ltp) : "—"}</Td>
                        <td className={`px-2 py-1.5 text-center font-semibold ${isAtm ? "text-sky-300" : "text-slate-200"}`}>
                          {num(strike, 0)}
                          {isAtm ? <span className="ml-1 text-[9px] text-sky-400">ATM</span> : null}
                        </td>
                        <Td tone="text-rose-300">{rec.pe ? num(rec.pe.ltp) : "—"}</Td>
                        <Td>{rec.pe ? num(rec.pe.delta, 2) : "—"}</Td>
                        <Td>{rec.pe ? `${num(rec.pe.iv * 100, 1)}%` : "—"}</Td>
                        <Td>{rec.pe ? compact(rec.pe.volume) : "—"}</Td>
                        <Td tone={(rec.pe?.change_in_oi ?? 0) >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}>
                          {rec.pe ? compact(rec.pe.change_in_oi) : "—"}
                        </Td>
                        <Td>{rec.pe ? compact(rec.pe.open_interest) : "—"}</Td>
                        <Td tone={rec.pe?.rejected ? "text-rose-400/70" : "text-sky-300"}>
                          {rec.pe ? num(rec.pe.score, 1) : "—"}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </PageShell>
  );
}

function Td({
  children,
  align = "left",
  tone,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  tone?: string;
}) {
  return (
    <td className={`px-2 py-1.5 ${align === "right" ? "text-right" : "text-left"} ${tone ?? "text-slate-300"}`}>
      {children}
    </td>
  );
}

function Verdict({ row }: { row: ScannerRow }) {
  if (row.rejected) {
    return (
      <span className="text-[10px] text-rose-400" title={row.reject_reasons.join("; ")}>
        REJECTED — {row.reject_reasons[0]}
      </span>
    );
  }
  if (row.below_min_score) {
    return <span className="text-[10px] text-amber-400">Below min score</span>;
  }
  return <span className="text-[10px] text-emerald-400">ELIGIBLE</span>;
}

function RecommendedCard({
  row,
  label,
  testid,
}: {
  row: ScannerRow | null;
  label: string;
  testid: string;
}) {
  const isCall = label.includes("CALL");
  if (!row) {
    return (
      <div className="rounded-lg border border-slate-800/80 bg-[#111722] px-4 py-3" data-testid={testid}>
        <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
        <p className="mt-2 text-xs text-slate-400" data-testid={`${testid}-empty`}>
          No contract on this side currently passes the liquidity, spread, premium and score
          thresholds — the engine would return NO TRADE.
        </p>
      </div>
    );
  }
  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        isCall ? "border-emerald-500/30 bg-emerald-950/20" : "border-rose-500/30 bg-rose-950/20"
      }`}
      data-testid={testid}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
          <p className="mt-1 font-mono text-base font-bold text-slate-100" data-testid={`${testid}-contract`}>
            {num(row.strike, 0)} {row.option_type}
          </p>
          <p className="font-mono text-[10px] text-slate-500">{row.moneyness} · {expiryLabel(row.expiry)}</p>
        </div>
        <Badge className="border border-sky-500/40 bg-sky-950/60 font-mono text-[11px] text-sky-300">
          score {num(row.score, 1)}
        </Badge>
      </div>
      <dl className="mt-2.5 grid grid-cols-4 gap-2 border-t border-slate-800/70 pt-2 font-mono text-[10px]">
        <div><dt className="text-slate-500">LTP</dt><dd className="text-slate-200">{num(row.ltp)}</dd></div>
        <div><dt className="text-slate-500">Spread</dt><dd className="text-slate-200">{num(row.spread_pct, 2)}%</dd></div>
        <div><dt className="text-slate-500">OI</dt><dd className="text-slate-200">{compact(row.open_interest)}</dd></div>
        <div><dt className="text-slate-500">IV</dt><dd className="text-slate-200">{num(row.iv * 100, 1)}%</dd></div>
      </dl>
    </div>
  );
}
