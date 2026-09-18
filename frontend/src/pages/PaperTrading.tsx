import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { SignalCardWidget } from "@/components/trading/SignalCardWidget";
import { expiryLabel, inr, istDateTime, num, statusLabel, STATUS_TONE } from "@/lib/format";
import type { PaperAccount, PaperPosition, Signal } from "@/lib/types";

export default function PaperTrading() {
  const qc = useQueryClient();
  const { data: account } = useQuery({
    queryKey: ["paper-account"],
    queryFn: () => apiGet<PaperAccount>("/paper/account"),
    refetchInterval: 4000,
    retry: false,
  });
  const { data: open } = useQuery({
    queryKey: ["paper-positions", "OPEN"],
    queryFn: () => apiGet<PaperPosition[]>("/paper/positions?status=OPEN"),
    refetchInterval: 4000,
    retry: false,
  });
  const { data: closed } = useQuery({
    queryKey: ["paper-positions", "CLOSED"],
    queryFn: () => apiGet<PaperPosition[]>("/paper/positions?status=CLOSED&limit=100"),
    refetchInterval: 8000,
    retry: false,
  });
  const { data: active } = useQuery({
    queryKey: ["active-signals"],
    queryFn: () => apiGet<Signal[]>("/signals/active"),
    refetchInterval: 5000,
    retry: false,
  });

  const closePos = useMutation({
    mutationFn: (id: string) => apiPost<{ ok: boolean; message: string }>(`/paper/close/${id}`),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["paper-positions"] });
      void qc.invalidateQueries({ queryKey: ["paper-account"] });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      toast.error(detail ?? "Could not close the position.");
    },
  });
  const reset = useMutation({
    mutationFn: () => apiPost<{ ok: boolean; message: string }>("/paper/reset"),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["paper-positions"] });
      void qc.invalidateQueries({ queryKey: ["paper-account"] });
      void qc.invalidateQueries({ queryKey: ["signals"] });
    },
    onError: () => toast.error("Could not reset the paper account."),
  });

  return (
    <PageShell
      title="Paper Trading Terminal"
      subtitle="Virtual execution of live signals against simulated capital. Position size follows the configured max risk per trade and exchange lot size. No order is ever routed to a real broker or exchange."
      testid="paper-trading-page"
      actions={
        <Button
          size="sm"
          variant="outline"
          onClick={() => reset.mutate()}
          disabled={reset.isPending}
          data-testid="paper-reset-button"
        >
          Reset virtual account
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Start capital" value={inr(account?.start_capital ?? 0, 0)} testid="paper-start-capital" />
          <Metric label="Equity" value={inr(account?.equity ?? 0, 0)} testid="paper-equity-metric" />
          <Metric label="Cash" value={inr(account?.cash ?? 0, 0)} testid="paper-cash" />
          <Metric
            label="Realized P&L"
            value={inr(account?.realized_pnl ?? 0, 0)}
            tone={(account?.realized_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
            testid="paper-realized"
          />
          <Metric
            label="Unrealized P&L"
            value={inr(account?.unrealized_pnl ?? 0, 0)}
            tone={(account?.unrealized_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
            testid="paper-unrealized"
          />
          <Metric
            label="Day P&L"
            value={inr(account?.daily_pnl ?? 0, 0)}
            tone={(account?.daily_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}
            testid="paper-day-pnl"
          />
          <Metric
            label="Drawdown"
            value={`${inr(account?.drawdown ?? 0, 0)} (${num(account?.drawdown_pct ?? 0, 2)}%)`}
            testid="paper-drawdown-metric"
          />
          <Metric
            label="Consecutive losses"
            value={num(account?.consecutive_losses ?? 0, 0)}
            tone={(account?.consecutive_losses ?? 0) >= 3 ? "text-rose-300" : undefined}
            testid="paper-consecutive-losses"
          />
        </div>

        {account?.risk_blocked_reason ? (
          <p
            className="rounded-md border border-rose-500/40 bg-rose-950/40 px-4 py-3 font-mono text-xs leading-relaxed text-rose-300"
            data-testid="paper-risk-block-banner"
          >
            {account.risk_blocked_reason}
          </p>
        ) : null}

        <Panel title="Execute an active signal" testid="paper-execute-panel">
          {active && active.length > 0 ? (
            <div className="space-y-3">
              {active.map((s) => (
                <SignalCardWidget key={s.id} signal={s} compactView />
              ))}
            </div>
          ) : (
            <EmptyState
              title="No active signal to execute"
              body="When the engine generates a qualifying signal it appears here with a one-click virtual execution button."
              testid="paper-no-active-signal"
            />
          )}
        </Panel>

        <Panel title={`Open positions (${open?.length ?? 0})`} testid="open-positions-panel">
          {open && open.length > 0 ? (
            <Table data-testid="open-positions-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Opened (IST)</TableHead>
                  <TableHead>Contract</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">SL / Target</TableHead>
                  <TableHead className="text-right">Unrealized</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {open.map((p) => (
                  <TableRow key={p.id} className="font-mono text-xs" data-testid={`open-position-${p.id}`}>
                    <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(p.entry_time)}</TableCell>
                    <TableCell className="whitespace-nowrap text-slate-200">
                      {p.symbol} {num(p.strike, 0)} {p.option_type}
                      <span className="ml-1 text-[10px] text-slate-500">{expiryLabel(p.expiry)}</span>
                    </TableCell>
                    <TableCell className="text-right">{num(p.qty, 0)}</TableCell>
                    <TableCell className="text-right">{num(p.entry_price)}</TableCell>
                    <TableCell className="text-right text-slate-200">{num(p.last_price)}</TableCell>
                    <TableCell className="text-right text-slate-400">
                      {num(p.stop_loss)} / {num(p.target)}
                    </TableCell>
                    <TableCell
                      className={`text-right ${(p.unrealized ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}
                    >
                      {inr(p.unrealized ?? 0, 0)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="xs"
                        variant="outline"
                        onClick={() => closePos.mutate(p.id)}
                        disabled={closePos.isPending}
                        data-testid={`close-position-button-${p.id}`}
                      >
                        Close
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              title="No open virtual positions"
              body="Execute an active signal above to open one. SL and target are then tracked automatically against the live feed."
              testid="open-positions-empty"
            />
          )}
        </Panel>

        <Panel title={`Closed positions (${closed?.length ?? 0})`} testid="closed-positions-panel">
          {closed && closed.length > 0 ? (
            <div className="max-h-[420px] overflow-y-auto">
              <Table data-testid="closed-positions-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Opened</TableHead>
                    <TableHead>Closed</TableHead>
                    <TableHead>Contract</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Exit</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {closed.map((p) => (
                    <TableRow key={p.id} className="font-mono text-xs" data-testid={`closed-position-${p.id}`}>
                      <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(p.entry_time)}</TableCell>
                      <TableCell className="whitespace-nowrap text-slate-400">{istDateTime(p.exit_time)}</TableCell>
                      <TableCell className="whitespace-nowrap text-slate-200">
                        {p.symbol} {num(p.strike, 0)} {p.option_type}
                      </TableCell>
                      <TableCell className="text-right">{num(p.qty, 0)}</TableCell>
                      <TableCell className="text-right">{num(p.entry_price)}</TableCell>
                      <TableCell className="text-right">{num(p.exit_price)}</TableCell>
                      <TableCell
                        className={`text-right ${(p.realized_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}
                      >
                        {inr(p.realized_pnl ?? 0, 0)}
                      </TableCell>
                      <TableCell>
                        <Badge className={`border text-[10px] ${STATUS_TONE[p.close_reason?.includes("TARGET") ? "WIN" : p.close_reason === "STOP_LOSS" ? "LOSS" : "FLAT"] ?? ""}`}>
                          {statusLabel(p.close_reason || "—")}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState title="No closed positions yet" testid="closed-positions-empty" />
          )}
        </Panel>
      </div>
    </PageShell>
  );
}
