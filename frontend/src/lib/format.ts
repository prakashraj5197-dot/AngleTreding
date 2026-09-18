/** Formatting + shared display helpers for the trading UI. */

export const inr = (v: number | null | undefined, dp = 2): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

export const num = (v: number | null | undefined, dp = 2): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const compact = (v: number | null | undefined): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
};

export const pct = (v: number | null | undefined, dp = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;

export const signed = (v: number | null | undefined, dp = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}`;

/** IST time-of-day for a UTC ISO timestamp — the app's single display timezone. */
export const istTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
};

export const istDateTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
};

export const expiryLabel = (d: string): string => {
  if (!d) return "—";
  const dt = new Date(`${d}T00:00:00+05:30`);
  return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

export const agoSeconds = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return Math.max(0, (Date.now() - d.getTime()) / 1000);
};

export const DIRECTION_COPY: Record<string, { label: string; tone: string; icon: string }> = {
  BULLISH: { label: "BULLISH", tone: "text-emerald-400", icon: "▲" },
  BEARISH: { label: "BEARISH", tone: "text-rose-400", icon: "▼" },
  SIDEWAYS: { label: "SIDEWAYS", tone: "text-slate-400", icon: "◆" },
  NO_TRADE: { label: "NO TRADE", tone: "text-amber-400", icon: "●" },
};

export const STATUS_TONE: Record<string, string> = {
  ACTIVE: "bg-sky-950/70 text-sky-300 border-sky-500/40",
  TARGET1_HIT: "bg-emerald-950/70 text-emerald-300 border-emerald-500/40",
  TARGET2_HIT: "bg-emerald-900/80 text-emerald-200 border-emerald-400/50",
  STOP_LOSS: "bg-rose-950/70 text-rose-300 border-rose-500/40",
  EXPIRED: "bg-slate-800/70 text-slate-300 border-slate-500/40",
  MISSED_ENTRY: "bg-amber-950/70 text-amber-300 border-amber-500/40",
  CANCELLED: "bg-slate-800/70 text-slate-400 border-slate-600/40",
  DATA_ERROR: "bg-rose-950/70 text-rose-300 border-rose-500/40",
  OPEN: "bg-sky-950/70 text-sky-300 border-sky-500/40",
  CLOSED: "bg-slate-800/70 text-slate-300 border-slate-500/40",
  WIN: "bg-emerald-950/70 text-emerald-300 border-emerald-500/40",
  LOSS: "bg-rose-950/70 text-rose-300 border-rose-500/40",
  FLAT: "bg-slate-800/70 text-slate-300 border-slate-500/40",
  QUEUED: "bg-slate-800/70 text-slate-300 border-slate-500/40",
  RUNNING: "bg-sky-950/70 text-sky-300 border-sky-500/40",
  COMPLETED: "bg-emerald-950/70 text-emerald-300 border-emerald-500/40",
  FAILED: "bg-rose-950/70 text-rose-300 border-rose-500/40",
};

export const statusLabel = (s: string): string => s.replace(/_/g, " ");

export const REGIME_LABEL: Record<string, string> = {
  trend_up: "Trending up",
  trend_down: "Trending down",
  range: "Range-bound",
  high_vol: "High volatility",
  low_vol: "Low volatility",
};
