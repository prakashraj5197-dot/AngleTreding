import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lock, LogOut } from "lucide-react";
import { apiGet, apiPost, apiPut, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProviderPanel } from "@/components/trading/ProviderPanel";
import { DatabasePanel } from "@/components/trading/DatabasePanel";
import { Metric, Panel, PageShell } from "@/components/layout/PageShell";
import { istDateTime, num } from "@/lib/format";
import type { AppSettings, AuthState } from "@/lib/types";

const SESSION_MODES: Record<string, string> = {
  always_on: "Always-on simulated session",
  market_hours: "Follow NSE clock (09:15–15:30 IST)",
};

export default function Settings() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [email, setEmail] = useState("admin@quantpulse.in");
  const [password, setPassword] = useState("");

  const { data: auth } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => apiGet<AuthState>("/auth/me"),
    retry: false,
  });
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet<AppSettings>("/settings"),
    retry: false,
  });

  // Re-seed the form whenever the server copy changes (our own save, a provider switch that
  // adjusts session mode, or another admin editing concurrently) so the inputs never show a
  // value the backend has already moved past.
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  useEffect(() => {
    if (!settings) return;
    const stamp = settings.updated_at ?? "initial";
    if (!draft || stamp !== syncedAt) {
      setDraft(structuredClone(settings));
      setSyncedAt(stamp);
    }
  }, [settings, draft, syncedAt]);

  const login = useMutation({
    mutationFn: () => apiPost<AuthState>("/auth/login", { email, password }),
    onSuccess: () => {
      toast.success("Signed in as administrator.");
      setPassword("");
      void qc.invalidateQueries({ queryKey: ["auth-me"] });
    },
    onError: () => toast.error("Invalid email or password."),
  });
  const logout = useMutation({
    mutationFn: () => apiPost<AuthState>("/auth/logout"),
    onSuccess: () => {
      toast.success("Signed out.");
      qc.clear();
      void qc.invalidateQueries({ queryKey: ["auth-me"] });
    },
  });
  const save = useMutation({
    mutationFn: (payload: AppSettings) => apiPut<AppSettings>("/settings", payload),
    onSuccess: (res) => {
      toast.success(`Configuration saved — strategy version ${res.strategy.version}.`);
      setDraft(structuredClone(res));
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["engine-state"] });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      toast.error(typeof detail === "string" ? detail : "Settings rejected by validation.");
    },
  });
  const resetDefaults = useMutation({
    mutationFn: () => apiPost<AppSettings>("/settings/reset"),
    onSuccess: (res) => {
      toast.success("Restored engineering defaults.");
      setDraft(structuredClone(res));
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: () => toast.error("Could not reset settings."),
  });

  const signedIn = auth?.ok ?? false;

  if (!draft) {
    return (
      <PageShell title="Settings" testid="settings-page">
        <p className="text-xs text-slate-500" data-testid="settings-loading">Loading configuration…</p>
      </PageShell>
    );
  }

  const s = draft.strategy;
  const o = draft.option_selection;
  const r = draft.risk;
  const d = draft.data;

  const setStrategy = (patch: Partial<typeof s>) =>
    setDraft({ ...draft, strategy: { ...s, ...patch } });
  const setOption = (patch: Partial<typeof o>) =>
    setDraft({ ...draft, option_selection: { ...o, ...patch } });
  const setRisk = (patch: Partial<typeof r>) => setDraft({ ...draft, risk: { ...r, ...patch } });
  const setData = (patch: Partial<typeof d>) => setDraft({ ...draft, data: { ...d, ...patch } });

  return (
    <PageShell
      title="Strategy, Risk & Data Settings"
      subtitle="Every threshold the engine uses is configurable here — no code changes. Saving a strategy change automatically mints a new strategy version so historical signals stay traceable."
      testid="settings-page"
      actions={
        signedIn ? (
          <>
            <Badge variant="outline" className="font-mono text-[10px]" data-testid="admin-email-badge">
              {auth?.email}
            </Badge>
            <Button size="sm" variant="ghost" onClick={() => logout.mutate()} data-testid="logout-button">
              <LogOut className="size-3.5" />
              Sign out
            </Button>
          </>
        ) : null
      }
    >
      <div className="space-y-4">
        <Panel title="Active strategy version" testid="version-panel">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Metric label="Strategy" value={settings?.strategy.name ?? "—"} testid="version-name" />
            <Metric label="Version" value={`v${settings?.strategy.version ?? "—"}`} testid="version-value" />
            <Metric label="Signal timeframe" value={settings?.strategy.signal_timeframe ?? "—"} testid="version-timeframe" />
            <Metric label="Last updated" value={istDateTime(settings?.updated_at)} testid="version-updated" />
          </div>
        </Panel>

        {!signedIn ? (
          <Panel title="Administrator sign-in required" testid="login-panel">
            <div className="grid max-w-md gap-3">
              <p className="text-xs leading-relaxed text-slate-400">
                Thresholds are readable by anyone, but changing strategy, risk or data
                configuration requires an authenticated administrator. Provider credentials
                live only in the backend environment and are never sent to the browser.
              </p>
              <div className="space-y-1">
                <Label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Email</Label>
                <Input value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email-input" />
              </div>
              <div className="space-y-1">
                <Label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">Password</Label>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && login.mutate()}
                  data-testid="login-password-input"
                />
              </div>
              <Button onClick={() => login.mutate()} disabled={login.isPending} data-testid="login-submit-button">
                <Lock className="size-3.5" />
                {login.isPending ? "Signing in…" : "Sign in"}
              </Button>
            </div>
          </Panel>
        ) : null}

        <Tabs defaultValue="strategy" data-testid="settings-tabs">
          <TabsList variant="line">
            <TabsTrigger value="strategy" data-testid="tab-strategy">Strategy</TabsTrigger>
            <TabsTrigger value="options" data-testid="tab-options">Option selection</TabsTrigger>
            <TabsTrigger value="risk" data-testid="tab-risk">Risk</TabsTrigger>
            <TabsTrigger value="data" data-testid="tab-data">Data & notifications</TabsTrigger>
          </TabsList>

          <TabsContent value="strategy">
            <Panel title="Signal thresholds & indicator parameters" testid="strategy-settings-panel">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <NumField label="Min signal score" value={s.min_signal_score} onChange={(v) => setStrategy({ min_signal_score: v })} testid="setting-min-signal-score" disabled={!signedIn} />
                <NumField label="Min risk / reward" step={0.1} value={s.min_risk_reward} onChange={(v) => setStrategy({ min_risk_reward: v })} testid="setting-min-risk-reward" disabled={!signedIn} />
                <NumField label="EMA fast" value={s.ema_fast} onChange={(v) => setStrategy({ ema_fast: v })} testid="setting-ema-fast" disabled={!signedIn} />
                <NumField label="EMA slow" value={s.ema_slow} onChange={(v) => setStrategy({ ema_slow: v })} testid="setting-ema-slow" disabled={!signedIn} />
                <NumField label="RSI period" value={s.rsi_period} onChange={(v) => setStrategy({ rsi_period: v })} testid="setting-rsi-period" disabled={!signedIn} />
                <NumField label="ATR period" value={s.atr_period} onChange={(v) => setStrategy({ atr_period: v })} testid="setting-atr-period" disabled={!signedIn} />
                <NumField label="Volume multiplier" step={0.1} value={s.volume_multiplier} onChange={(v) => setStrategy({ volume_multiplier: v })} testid="setting-volume-multiplier" disabled={!signedIn} />
                <NumField label="Breakout lookback (bars)" value={s.breakout_lookback} onChange={(v) => setStrategy({ breakout_lookback: v })} testid="setting-breakout-lookback" disabled={!signedIn} />
                <NumField label="Conflict tolerance" value={s.conflict_tolerance} onChange={(v) => setStrategy({ conflict_tolerance: v })} testid="setting-conflict-tolerance" disabled={!signedIn} />
                <NumField label="Signal validity (min)" value={s.signal_validity_min} onChange={(v) => setStrategy({ signal_validity_min: v })} testid="setting-signal-validity" disabled={!signedIn} />
                <NumField label="Cooldown (min)" value={s.cooldown_min} onChange={(v) => setStrategy({ cooldown_min: v })} testid="setting-cooldown" disabled={!signedIn} />
                <NumField label="Max re-entries / day" value={s.max_reentries_per_day} onChange={(v) => setStrategy({ max_reentries_per_day: v })} testid="setting-max-reentries" disabled={!signedIn} />
                <NumField label="Max signals / symbol / day" value={s.max_signals_per_symbol_day} onChange={(v) => setStrategy({ max_signals_per_symbol_day: v })} testid="setting-max-signals-symbol" disabled={!signedIn} />
                <NumField label="Opening filter (min)" value={s.opening_filter_min} onChange={(v) => setStrategy({ opening_filter_min: v })} testid="setting-opening-filter" disabled={!signedIn} />
                <NumField label="Closing filter (min)" value={s.closing_filter_min} onChange={(v) => setStrategy({ closing_filter_min: v })} testid="setting-closing-filter" disabled={!signedIn} />
                <NumField label="Expiry-day filter (min)" value={s.expiry_day_filter_min} onChange={(v) => setStrategy({ expiry_day_filter_min: v })} testid="setting-expiry-filter" disabled={!signedIn} />
                <NumField label="SL % of premium" value={s.sl_pct_of_premium} onChange={(v) => setStrategy({ sl_pct_of_premium: v })} testid="setting-sl-pct" disabled={!signedIn} />
                <NumField label="Target 1 (R multiple)" step={0.1} value={s.t1_rr} onChange={(v) => setStrategy({ t1_rr: v })} testid="setting-t1-rr" disabled={!signedIn} />
                <NumField label="Target 2 (R multiple)" step={0.1} value={s.t2_rr} onChange={(v) => setStrategy({ t2_rr: v })} testid="setting-t2-rr" disabled={!signedIn} />
                <NumField label="Entry range ±%" step={0.1} value={s.entry_range_pct} onChange={(v) => setStrategy({ entry_range_pct: v })} testid="setting-entry-range" disabled={!signedIn} />
              </div>
              <h3 className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-wider text-slate-500">
                Direction factor weights (total defines the 100-point scale)
              </h3>
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                {(Object.keys(s.weights) as Array<keyof typeof s.weights>).map((k) => (
                  <NumField
                    key={k}
                    label={k.toUpperCase()}
                    value={s.weights[k]}
                    onChange={(v) => setStrategy({ weights: { ...s.weights, [k]: v } })}
                    testid={`setting-weight-${k}`}
                    disabled={!signedIn}
                  />
                ))}
              </div>
            </Panel>
          </TabsContent>

          <TabsContent value="options">
            <Panel title="Option selection & liquidity filters" testid="option-settings-panel">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <NumField label="ATM ± strikes" value={o.atm_range} onChange={(v) => setOption({ atm_range: v })} testid="setting-atm-range" disabled={!signedIn} />
                <NumField label="Minimum open interest" value={o.min_oi} onChange={(v) => setOption({ min_oi: v })} testid="setting-min-oi" disabled={!signedIn} />
                <NumField label="Minimum volume" value={o.min_volume} onChange={(v) => setOption({ min_volume: v })} testid="setting-min-volume" disabled={!signedIn} />
                <NumField label="Max bid/ask spread %" step={0.1} value={o.max_spread_pct} onChange={(v) => setOption({ max_spread_pct: v })} testid="setting-max-spread" disabled={!signedIn} />
                <NumField label="Minimum premium ₹" value={o.min_premium} onChange={(v) => setOption({ min_premium: v })} testid="setting-min-premium" disabled={!signedIn} />
                <NumField label="Minimum contract score" value={o.min_option_score} onChange={(v) => setOption({ min_option_score: v })} testid="setting-min-option-score" disabled={!signedIn} />
              </div>
              <h3 className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-wider text-slate-500">
                Contract score weights
              </h3>
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {(Object.keys(o.weights) as Array<keyof typeof o.weights>).map((k) => (
                  <NumField
                    key={k}
                    label={k.replace(/_/g, " ").toUpperCase()}
                    value={o.weights[k]}
                    onChange={(v) => setOption({ weights: { ...o.weights, [k]: v } })}
                    testid={`setting-option-weight-${k}`}
                    disabled={!signedIn}
                  />
                ))}
              </div>
            </Panel>
          </TabsContent>

          <TabsContent value="risk">
            <Panel title="Risk management limits" testid="risk-settings-panel">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <NumField label="Capital ₹" value={r.capital} onChange={(v) => setRisk({ capital: v })} testid="setting-capital" disabled={!signedIn} />
                <NumField label="Max risk / trade ₹" value={r.max_risk_per_trade} onChange={(v) => setRisk({ max_risk_per_trade: v })} testid="setting-max-risk-trade" disabled={!signedIn} />
                <NumField label="Daily loss limit ₹" value={r.daily_loss_limit} onChange={(v) => setRisk({ daily_loss_limit: v })} testid="setting-daily-loss-limit" disabled={!signedIn} />
                <NumField label="Consecutive loss limit" value={r.consecutive_loss_limit} onChange={(v) => setRisk({ consecutive_loss_limit: v })} testid="setting-consecutive-loss-limit" disabled={!signedIn} />
                <NumField label="Max trades / day" value={r.max_trades_per_day} onChange={(v) => setRisk({ max_trades_per_day: v })} testid="setting-max-trades-day" disabled={!signedIn} />
                <NumField label="Paper start capital ₹" value={draft.paper.start_capital} onChange={(v) => setDraft({ ...draft, paper: { ...draft.paper, start_capital: v } })} testid="setting-paper-capital" disabled={!signedIn} />
              </div>
              <label className="mt-3 flex items-start gap-2 rounded-md border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                <Checkbox
                  checked={r.enforce}
                  onCheckedChange={(c: boolean) => setRisk({ enforce: Boolean(c) })}
                  disabled={!signedIn}
                  data-testid="setting-enforce-risk"
                />
                <span className="text-[11px] leading-relaxed text-slate-400">
                  Enforce risk limits — when enabled, a setup that breaches the daily loss,
                  consecutive-loss or trade-count limits is blocked and never becomes a signal.
                </span>
              </label>
            </Panel>
          </TabsContent>

          <TabsContent value="data">
            <DatabasePanel />
            <ProviderPanel signedIn={signedIn} />
            <Panel title="Market data, freshness & notifications" testid="data-settings-panel">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-1">
                  <Label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
                    Session mode
                  </Label>
                  <Select
                    value={d.session_mode}
                    onValueChange={(v: string) => setData({ session_mode: v as "always_on" | "market_hours" })}
                  >
                    <SelectTrigger size="sm" disabled={!signedIn} data-testid="setting-session-mode">
                      <SelectValue>{(v) => SESSION_MODES[v as string] ?? "Select"}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(SESSION_MODES).map(([v, l]) => (
                        <SelectItem key={v} value={v}>{l}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <NumField label="Price freshness (s)" value={d.price_fresh_s} onChange={(v) => setData({ price_fresh_s: v })} testid="setting-price-fresh" disabled={!signedIn} />
                <NumField label="Option freshness (s)" value={d.option_fresh_s} onChange={(v) => setData({ option_fresh_s: v })} testid="setting-option-fresh" disabled={!signedIn} />
                <NumField label="Chain freshness (s)" value={d.chain_fresh_s} onChange={(v) => setData({ chain_fresh_s: v })} testid="setting-chain-fresh" disabled={!signedIn} />
                <NumField label="Candle retention (days)" value={d.retention_candle_days} onChange={(v) => setData({ retention_candle_days: v })} testid="setting-retention-candles" disabled={!signedIn} />
                <NumField label="Chain snapshot retention (days)" value={d.retention_option_snapshot_days} onChange={(v) => setData({ retention_option_snapshot_days: v })} testid="setting-retention-snapshots" disabled={!signedIn} />
              </div>
              <div className="mt-3 space-y-2">
                <label className="flex items-start gap-2 rounded-md border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                  <Checkbox
                    checked={d.force_stale}
                    onCheckedChange={(c: boolean) => setData({ force_stale: Boolean(c) })}
                    disabled={!signedIn}
                    data-testid="setting-force-stale"
                  />
                  <span className="text-[11px] leading-relaxed text-slate-400">
                    Simulate a provider disconnect (freeze the feed timestamp) — the UI shows
                    DATA STALE / FEED DISCONNECTED and signal generation pauses. Use this to
                    verify the stale-data safety path.
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-md border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                  <Checkbox
                    checked={d.stale_block_signals}
                    onCheckedChange={(c: boolean) => setData({ stale_block_signals: Boolean(c) })}
                    disabled={!signedIn}
                    data-testid="setting-stale-blocks"
                  />
                  <span className="text-[11px] leading-relaxed text-slate-400">
                    Block signal generation whenever any mandatory input is stale.
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-md border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                  <Checkbox
                    checked={draft.notifications.enabled}
                    onCheckedChange={(c: boolean) =>
                      setDraft({ ...draft, notifications: { ...draft.notifications, enabled: Boolean(c) } })
                    }
                    disabled={!signedIn}
                    data-testid="setting-notifications-enabled"
                  />
                  <span className="text-[11px] leading-relaxed text-slate-400">
                    Web notifications for new signals, target hits, stop-losses and expiries.
                  </span>
                </label>
              </div>
            </Panel>
          </TabsContent>
        </Tabs>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => save.mutate(draft)}
            disabled={!signedIn || save.isPending}
            data-testid="save-settings-button"
          >
            {save.isPending ? "Saving…" : "Save configuration"}
          </Button>
          <Button
            variant="outline"
            onClick={() => setDraft(settings ? structuredClone(settings) : null)}
            disabled={!signedIn}
            data-testid="discard-settings-button"
          >
            Discard changes
          </Button>
          <Button
            variant="ghost"
            onClick={() => resetDefaults.mutate()}
            disabled={!signedIn || resetDefaults.isPending}
            data-testid="reset-defaults-button"
          >
            Restore engineering defaults
          </Button>
          {!signedIn ? (
            <span className="font-mono text-[10px] text-amber-400" data-testid="settings-locked-note">
              Sign in above to modify configuration.
            </span>
          ) : null}
        </div>

        <p className="text-[11px] leading-relaxed text-slate-500" data-testid="settings-note">
          All values here are engineering defaults, not claims of profitability. Every change
          is recorded with a new strategy version, must be validated on historical data, and
          reviewed again in paper trading before being trusted.
        </p>
      </div>
    </PageShell>
  );
}

function NumField({
  label,
  value,
  onChange,
  step,
  testid,
  disabled,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  testid: string;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-1">
      <Label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</Label>
      <Input
        type="number"
        step={step ?? 1}
        value={String(value)}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        data-testid={testid}
      />
    </div>
  );
}
