import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plug, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiGet, apiPost, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/layout/PageShell";
import type { ProviderStatus, ProviderTestResult } from "@/lib/types";

const PROVIDERS: Record<string, { label: string; blurb: string }> = {
  simulated: {
    label: "Built-in simulator",
    blurb: "Deterministic synthetic NSE feed. Always available — used for demos and backtest replay.",
  },
  angelone: {
    label: "Angel One SmartAPI",
    blurb: "Live NSE/NFO feed. Needs API key, client code, MPIN and TOTP secret in backend/.env.",
  },
};

export function ProviderPanel({ signedIn }: { signedIn: boolean }) {
  const qc = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["provider-status"],
    queryFn: () => apiGet<ProviderStatus>("/provider/status"),
    refetchInterval: 20000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["provider-status"] });
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["health"] });
  };

  const switchTo = useMutation({
    mutationFn: (provider: string) =>
      apiPost<ProviderStatus>(`/provider/select/${provider}`, {}),
    onSuccess: (res) => {
      invalidate();
      toast[res.connected ? "success" : "warning"](
        res.connected ? `Switched to ${res.label}` : `Selected ${res.label} — not connected`,
        { description: res.detail || res.last_error || undefined },
      );
    },
    onError: (e: ApiError) => toast.error("Could not switch provider", { description: e.message }),
  });

  const test = useMutation({
    mutationFn: () => apiPost<ProviderTestResult>("/provider/test", {}),
    onSuccess: (res) => {
      invalidate();
      const contracts = Object.entries(res.option_contracts)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
      toast[res.ok ? "success" : "error"](res.ok ? "Broker feed reachable" : "Connection failed", {
        description: [res.message, contracts && `Contracts → ${contracts}`]
          .filter(Boolean)
          .join(" · "),
      });
    },
    onError: (e: ApiError) => toast.error("Connection test failed", { description: e.message }),
  });

  const refresh = useMutation({
    mutationFn: () => apiPost<ProviderTestResult>("/provider/instruments/refresh", {}),
    onSuccess: (res) => {
      invalidate();
      const contracts = Object.entries(res.option_contracts)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
      toast[res.ok ? "success" : "error"](res.ok ? "Instrument master refreshed" : "Refresh failed", {
        description: [res.message, contracts && `Contracts → ${contracts}`].filter(Boolean).join(" · "),
      });
    },
    onError: (e: ApiError) => toast.error("Refresh failed", { description: e.message }),
  });

  const active = status?.provider ?? "simulated";
  const live = active === "angelone";

  return (
    <Panel title="Market-data provider" testid="provider-panel">
      <div className="grid gap-2.5 sm:grid-cols-2">
        {Object.entries(PROVIDERS).map(([key, meta]) => {
          const selected = active === key;
          return (
            <button
              key={key}
              type="button"
              disabled={!signedIn || switchTo.isPending}
              onClick={() => switchTo.mutate(key)}
              data-testid={`provider-option-${key}`}
              className={`rounded-lg border px-3 py-2.5 text-left transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${
                selected
                  ? "border-sky-500/60 bg-sky-500/10"
                  : "border-slate-800/70 bg-slate-900/40 hover:border-slate-700"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] uppercase tracking-wider text-slate-200">
                  {meta.label}
                </span>
                {selected ? (
                  <Badge variant="outline" className="border-sky-500/50 text-[9px] text-sky-300">
                    ACTIVE
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{meta.blurb}</p>
            </button>
          );
        })}
      </div>

      <div
        className="mt-3 rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2.5"
        data-testid="provider-status-card"
      >
        <div className="flex flex-wrap items-center gap-2">
          {status?.connected ? (
            <CheckCircle2 className="size-3.5 text-emerald-400" />
          ) : (
            <AlertTriangle className="size-3.5 text-amber-400" />
          )}
          <span
            className="font-mono text-[11px] uppercase tracking-wider text-slate-200"
            data-testid="provider-status-state"
          >
            {status?.connected ? "CONNECTED" : "DISCONNECTED"}
          </span>
          <Badge variant="outline" className="text-[9px] text-slate-400">
            {status?.simulated ? "SIMULATED" : "LIVE BROKER"}
          </Badge>
          {status?.last_login_ist ? (
            <span className="font-mono text-[10px] text-slate-500">
              session {status.last_login_ist} IST
            </span>
          ) : null}
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400" data-testid="provider-detail">
          {status?.detail || "—"}
        </p>
        {status?.last_error ? (
          <p className="mt-1 text-[11px] leading-relaxed text-rose-300" data-testid="provider-last-error">
            {status.last_error}
          </p>
        ) : null}
        {status && status.missing_env.length > 0 ? (
          <p className="mt-1.5 font-mono text-[10px] text-amber-300" data-testid="provider-missing-env">
            Missing in backend/.env → {status.missing_env.join(", ")}
          </p>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={!signedIn || test.isPending}
          onClick={() => test.mutate()}
          data-testid="provider-test-button"
        >
          <Plug className="mr-1.5 size-3.5" />
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!signedIn || !live || refresh.isPending}
          onClick={() => refresh.mutate()}
          data-testid="provider-refresh-instruments"
        >
          <RefreshCw className="mr-1.5 size-3.5" />
          {refresh.isPending ? "Refreshing…" : "Refresh instruments"}
        </Button>
      </div>

      <p className="mt-2.5 text-[11px] leading-relaxed text-slate-500">
        Credentials live only in <span className="font-mono text-slate-400">backend/.env</span> and are
        never sent to the browser. If the live feed drops, the dashboard shows DATA STALE and signal
        generation pauses — it never silently substitutes simulated prices.
      </p>
    </Panel>
  );
}
