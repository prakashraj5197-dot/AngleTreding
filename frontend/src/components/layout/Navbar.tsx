import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, FlaskConical, Layers, LineChart, Settings as SettingsIcon, Signal as SignalIcon, Wallet } from "lucide-react";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import { istTime } from "@/lib/format";
import type { Health, MarketStatus } from "@/lib/types";
import { NotificationBell } from "@/components/trading/NotificationBell";

const NAV = [
  { to: "/", label: "Dashboard", icon: BarChart3, testid: "nav-dashboard" },
  { to: "/signals", label: "Live Signals", icon: SignalIcon, testid: "nav-signals" },
  { to: "/option-scanner", label: "Option Scanner", icon: Layers, testid: "nav-option-scanner" },
  { to: "/market-analysis", label: "Market Analysis", icon: LineChart, testid: "nav-market-analysis" },
  { to: "/backtesting", label: "Backtesting", icon: FlaskConical, testid: "nav-backtesting" },
  { to: "/paper-trading", label: "Paper Trading", icon: Wallet, testid: "nav-paper-trading" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "nav-settings" },
];

export function Navbar() {
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

  const stale = health?.data_freshness?.stale ?? false;
  const closed = status?.status === "CLOSED";
  const feedDown = health?.provider === "disconnected";

  return (
    <header
      className="sticky top-0 z-40 border-b border-[#1E293B] bg-[#0B0E14]/92 backdrop-blur-xl"
      data-testid="app-header"
    >
      <div className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6 lg:px-8">
        <NavLink to="/" className="flex items-center gap-2.5" data-testid="brand-home-link">
          <span className="grid size-8 place-items-center rounded-md bg-sky-600/15 ring-1 ring-sky-500/40">
            <Activity className="size-4 text-sky-400" />
          </span>
          <span className="leading-tight">
            <span className="block font-heading text-sm font-bold tracking-tight text-slate-50">
              QuantPulse
            </span>
            <span className="block font-mono text-[10px] uppercase tracking-widest text-slate-500">
              F&amp;O Signal Engine
            </span>
          </span>
        </NavLink>

        <nav className="order-3 flex w-full flex-wrap items-center gap-1 lg:order-none lg:w-auto">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              data-testid={item.testid}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors duration-150",
                  isActive
                    ? "bg-sky-500/12 text-sky-300 ring-1 ring-sky-500/30"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200",
                )
              }
            >
              <item.icon className="size-3.5" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          {feedDown ? (
            <span
              className="flex items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-950/70 px-2 py-0.5 font-mono text-[11px] text-rose-300"
              data-testid="feed-disconnected-badge"
            >
              <span className="size-1.5 rounded-full bg-rose-400" />
              FEED DISCONNECTED
            </span>
          ) : stale ? (
            <span
              className="flex items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-950/70 px-2 py-0.5 font-mono text-[11px] text-rose-300"
              data-testid="data-stale-badge"
            >
              <span className="size-1.5 rounded-full bg-rose-400" />
              DATA STALE
            </span>
          ) : closed ? (
            <span
              className="flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-950/80 px-2 py-0.5 font-mono text-[11px] text-amber-400"
              data-testid="market-closed-badge"
            >
              <span className="size-1.5 rounded-full bg-amber-400" />
              MARKET CLOSED
            </span>
          ) : (
            <span
              className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/80 px-2 py-0.5 font-mono text-[11px] text-emerald-400"
              data-testid="market-live-badge"
            >
              <span className="size-1.5 animate-live-pulse rounded-full bg-emerald-400" />
              LIVE · SIMULATED
            </span>
          )}
          <span className="hidden font-mono text-[11px] text-slate-500 sm:inline" data-testid="ist-clock">
            {status?.ist_time ?? istTime(health?.server_time_utc)} IST
          </span>
          <NotificationBell />
        </div>
      </div>
    </header>
  );
}
