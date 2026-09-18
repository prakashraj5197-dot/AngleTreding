import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { agoSeconds, istTime, num, pct, REGIME_LABEL } from "@/lib/format";
import type { Health, MarketStatus, Quote } from "@/lib/types";

export function MarketStatusBar({ symbols = "NIFTY,BANKNIFTY" }: { symbols?: string }) {
  const { data: quotes } = useQuery({
    queryKey: ["quotes", symbols],
    queryFn: () => apiGet<Quote[]>(`/market/quotes?symbols=${symbols}`),
    refetchInterval: 2000,
    retry: false,
  });
  const { data: status } = useQuery({
    queryKey: ["market-status"],
    queryFn: () => apiGet<MarketStatus>("/market/status"),
    refetchInterval: 3000,
    retry: false,
  });
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<Health>("/health"),
    refetchInterval: 5000,
    retry: false,
  });

  const fresh = health?.data_freshness;
  const age = agoSeconds(quotes?.[0]?.ts);

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_auto]" data-testid="market-status-bar">
      <div className="grid gap-3 sm:grid-cols-2">
        {(quotes ?? []).map((q) => (
          <QuoteTile key={q.symbol} quote={q} />
        ))}
        {!quotes ? (
          <>
            <QuoteSkeleton label="NIFTY" />
            <QuoteSkeleton label="BANK NIFTY" />
          </>
        ) : null}
      </div>

      <div className="flex min-w-[240px] flex-col justify-center gap-2 rounded-lg border border-slate-800/80 bg-[#111722] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Market status
          </span>
          <Badge
            className={`border font-mono text-[10px] ${
              status?.status === "OPEN"
                ? "border-emerald-500/30 bg-emerald-950/80 text-emerald-400"
                : "border-amber-500/30 bg-amber-950/80 text-amber-400"
            }`}
            data-testid="market-status-value"
          >
            {status?.status === "OPEN" ? "OPEN" : "MARKET CLOSED"}
          </Badge>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Feed</span>
          <span
            className={`font-mono text-[11px] ${
              health?.provider === "connected" ? "text-emerald-400" : "text-rose-400"
            }`}
            data-testid="feed-state-value"
          >
            {health?.provider === "connected" ? "CONNECTED" : "DISCONNECTED"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Last update
          </span>
          <span
            className={`font-mono text-[11px] ${fresh?.stale ? "text-rose-400" : "text-slate-300"}`}
            data-testid="last-update-value"
          >
            {istTime(quotes?.[0]?.ts)} IST
            {age !== null ? ` · ${age.toFixed(1)}s ago` : ""}
          </span>
        </div>
        {fresh?.stale ? (
          <p
            className="rounded border border-rose-500/30 bg-rose-950/40 px-2 py-1 font-mono text-[10px] leading-relaxed text-rose-300"
            data-testid="data-stale-banner"
          >
            🔴 DATA STALE — SIGNAL GENERATION PAUSED
          </p>
        ) : null}
        <p className="font-mono text-[10px] leading-relaxed text-slate-500" data-testid="session-mode-note">
          {status?.note || `Session mode: ${status?.session_mode ?? "—"}`}
        </p>
      </div>
    </div>
  );
}

function QuoteTile({ quote }: { quote: Quote }) {
  const up = quote.change >= 0;
  return (
    <article
      className="rounded-lg border border-slate-800/80 bg-[#111722] px-4 py-3 transition-colors duration-200 hover:border-slate-700"
      data-testid={`quote-tile-${quote.symbol}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-heading text-xs font-semibold uppercase tracking-wider text-slate-400">
            {quote.name}
          </p>
          <p
            className="mt-1 font-mono text-2xl font-bold tabular-nums text-slate-50"
            data-testid={`quote-ltp-${quote.symbol}`}
          >
            {num(quote.ltp)}
          </p>
        </div>
        <div className="text-right">
          <p
            className={`font-mono text-sm font-semibold tabular-nums ${up ? "text-emerald-400" : "text-rose-400"}`}
            data-testid={`quote-change-${quote.symbol}`}
          >
            {up ? "▲" : "▼"} {num(Math.abs(quote.change))}
          </p>
          <p className={`font-mono text-[11px] ${up ? "text-emerald-400/80" : "text-rose-400/80"}`}>
            {pct(quote.change_pct)}
          </p>
        </div>
      </div>
      <dl className="mt-2.5 grid grid-cols-4 gap-2 border-t border-slate-800/70 pt-2 font-mono text-[10px]">
        <Cell label="Open" value={num(quote.open)} />
        <Cell label="High" value={num(quote.high)} />
        <Cell label="Low" value={num(quote.low)} />
        <Cell label="VWAP" value={num(quote.vwap)} />
      </dl>
      <p className="mt-1.5 font-mono text-[10px] text-slate-500" data-testid={`quote-regime-${quote.symbol}`}>
        Prev close {num(quote.prev_close)} · {REGIME_LABEL[quote.regime] ?? quote.regime}
      </p>
    </article>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-300">{value}</dd>
    </div>
  );
}

function QuoteSkeleton({ label }: { label: string }) {
  return (
    <article className="rounded-lg border border-slate-800/80 bg-[#111722] px-4 py-3" data-testid={`quote-skeleton-${label}`}>
      <p className="font-heading text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <div className="running-sheen mt-2 h-7 w-36 rounded bg-slate-800/60" />
      <div className="mt-3 h-8 rounded bg-slate-800/40" />
    </article>
  );
}
