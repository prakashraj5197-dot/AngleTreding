import { useQuery } from "@tanstack/react-query";
import { Database, AlertTriangle, CheckCircle2 } from "lucide-react";
import { apiGet } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/layout/PageShell";
import type { DbStatus } from "@/lib/types";

/** Shows which store is active. Credentials are never sent to the browser — this
 *  reads a status projection only (host/db name, connectivity, object counts). */
export function DatabasePanel() {
  const { data } = useQuery({
    queryKey: ["db-status"],
    queryFn: () => apiGet<DbStatus>("/database/status"),
    refetchInterval: 30000,
  });

  const sql = data?.backend === "sqlserver";
  const ok = Boolean(data?.connected);

  return (
    <Panel title="Data store" testid="database-panel">
      <div className="flex flex-wrap items-center gap-3" data-testid="db-status-card">
        <Database className={`size-5 ${ok ? "text-emerald-400" : "text-amber-400"}`} />
        <span className="font-mono text-sm text-slate-100" data-testid="db-backend-label">
          {data?.label ?? "…"}
        </span>
        <Badge
          variant="outline"
          className={
            ok
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-amber-500/40 bg-amber-500/10 text-amber-300"
          }
          data-testid="db-status-state"
        >
          {ok ? "CONNECTED" : "NOT CONNECTED"}
        </Badge>
        {sql ? (
          <span className="font-mono text-xs text-slate-400" data-testid="db-object-counts">
            {data?.tables ?? "—"} tables · {data?.procedures ?? "—"} procedures
          </span>
        ) : null}
      </div>

      <p className="mt-3 text-xs leading-relaxed text-slate-400" data-testid="db-detail">
        {data?.detail || "—"}
      </p>

      {data?.missing_env?.length && sql ? (
        <p className="mt-2 font-mono text-[11px] text-amber-300/90" data-testid="db-missing-env">
          Missing in backend/.env: {data.missing_env.join(", ")}
        </p>
      ) : null}

      {sql && data?.store_tables_missing?.length ? (
        <div
          className="mt-3 flex items-start gap-2 rounded-md border border-rose-500/30 bg-rose-500/5 p-3"
          data-testid="db-pending-store-migration"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-rose-400" />
          <p className="text-xs leading-relaxed text-rose-200/90">
            Pending migration: <span className="font-mono">migrations/002_app_store.sql</span> —{" "}
            {data.store_tables_missing.length} of {data.store_tables_total} application tables are
            missing, so signals, candles, paper trades and backtests cannot be persisted. Run the
            script against <span className="font-mono">{data.database}</span>, then restart the
            backend.
          </p>
        </div>
      ) : null}

      {sql && data?.connected && data?.store_tables_missing?.length === 0 ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-emerald-300/90" data-testid="db-store-ok">
          <CheckCircle2 className="size-4" /> Application store ready — all {data.store_tables_total}{" "}
          tables present. Every read and write goes to SQL Server.
        </p>
      ) : null}

      {sql && data?.migration_001_applied === false ? (
        <div
          className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3"
          data-testid="db-pending-migration"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
          <p className="text-xs leading-relaxed text-amber-200/90">
            Pending migration: <span className="font-mono">migrations/001_backtest_reporting_columns.sql</span>.
            Backtests run and display fully, but gross/net P&amp;L, costs, profit factor, R multiple,
            dataset segment and market regime are not persisted until you run it.
          </p>
        </div>
      ) : null}

      {sql && data?.migration_001_applied ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-emerald-300/90" data-testid="db-migration-ok">
          <CheckCircle2 className="size-4" /> Migration 001 applied — full backtest metrics are persisted.
        </p>
      ) : null}

      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        The application never creates, drops, renames or alters a database object. It reads and
        writes only the additive <span className="font-mono">Fno*</span> tables created by
        <span className="font-mono"> migrations/002_app_store.sql</span> and calls your existing
        stored procedures — any schema change is delivered as a script in{" "}
        <span className="font-mono">/app/migrations</span> for you to run manually.
      </p>
    </Panel>
  );
}
