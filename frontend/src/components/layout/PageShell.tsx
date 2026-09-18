import type { ReactNode } from "react";
import { Navbar } from "@/components/layout/Navbar";

export function PageShell({
  title,
  subtitle,
  actions,
  children,
  testid,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  testid?: string;
}) {
  return (
    <div className="min-h-svh bg-[#0B0E14]">
      <Navbar />
      <main
        className="mx-auto max-w-[1720px] px-4 py-5 sm:px-6 lg:px-8"
        data-testid={testid ?? "page-main"}
      >
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div>
            <h1
              className="font-heading text-xl font-bold tracking-tight text-slate-50 sm:text-2xl"
              data-testid="page-title"
            >
              {title}
            </h1>
            {subtitle ? (
              <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400" data-testid="page-subtitle">
                {subtitle}
              </p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {children}
        <footer
          className="mt-8 rounded-md border border-amber-500/20 bg-amber-950/20 px-4 py-3 text-[11px] leading-relaxed text-amber-200/80"
          data-testid="risk-disclaimer"
        >
          <strong className="font-semibold text-amber-300">Probability-based system.</strong>{" "}
          All output is algorithmic analysis on a simulated market feed for study and paper
          trading only — not investment advice, and never a guarantee of profit. Backtested
          results are hypothetical and do not represent future performance. No real broker
          order is ever placed by this application.
        </footer>
      </main>
    </div>
  );
}

export function Panel({
  title,
  right,
  children,
  className,
  testid,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  testid?: string;
}) {
  return (
    <section
      className={`grid-panel rounded-lg border border-slate-800/80 bg-[#111722] ${className ?? ""}`}
      data-testid={testid}
    >
      {title ? (
        <header className="flex items-center justify-between gap-3 border-b border-slate-800/80 px-4 py-2.5">
          <h2 className="font-heading text-xs font-semibold uppercase tracking-wider text-slate-400">
            {title}
          </h2>
          {right}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone,
  testid,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: string;
  testid?: string;
}) {
  return (
    <div
      className="rounded-md border border-slate-800/80 bg-[#161F30] px-3 py-2.5 transition-colors duration-200 hover:border-slate-700"
      data-testid={testid}
    >
      <div className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-sm font-semibold tabular-nums ${tone ?? "text-slate-100"}`}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 font-mono text-[10px] text-slate-500">{sub}</div> : null}
    </div>
  );
}

export function EmptyState({ title, body, testid }: { title: string; body?: string; testid?: string }) {
  return (
    <div
      className="rounded-md border border-dashed border-slate-700/70 bg-slate-900/30 px-4 py-8 text-center"
      data-testid={testid}
    >
      <p className="font-heading text-sm font-semibold text-slate-300">{title}</p>
      {body ? <p className="mx-auto mt-1.5 max-w-lg text-xs leading-relaxed text-slate-500">{body}</p> : null}
    </div>
  );
}
