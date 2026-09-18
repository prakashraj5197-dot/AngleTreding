import { useMemo } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { istTime, num } from "@/lib/format";
import type { Candle, Signal } from "@/lib/types";

/** Candles are drawn as a high-low wick bar plus an open-close body bar (recharts has no
 *  native candlestick), overlaid with VWAP, EMA20/50, support/resistance and the active
 *  signal's entry / SL / target levels. */
export function LiveChartWidget({
  candles,
  vwap,
  ema20,
  ema50,
  supports = [],
  resistances = [],
  signal,
  height = 340,
  testid = "live-chart",
}: {
  candles: Candle[];
  vwap?: (number | null)[];
  ema20?: (number | null)[];
  ema50?: (number | null)[];
  supports?: number[];
  resistances?: number[];
  signal?: Signal | null;
  height?: number;
  testid?: string;
}) {
  const rows = useMemo(
    () =>
      candles.map((c, i) => ({
        t: istTime(c.ts).slice(0, 5),
        low: c.l,
        high: c.h,
        wickBase: c.l,
        wick: c.h - c.l,
        bodyBase: Math.min(c.o, c.c),
        body: Math.max(Math.abs(c.c - c.o), 0.01),
        up: c.c >= c.o,
        close: c.c,
        open: c.o,
        vwap: vwap?.[i] ?? null,
        ema20: ema20?.[i] ?? null,
        ema50: ema50?.[i] ?? null,
      })),
    [candles, vwap, ema20, ema50],
  );

  if (rows.length === 0) {
    return (
      <div
        className="grid h-[340px] place-items-center rounded-md border border-dashed border-slate-700/70 text-xs text-slate-500"
        data-testid={`${testid}-empty`}
      >
        Waiting for candle data from the market feed…
      </div>
    );
  }

  const lows = rows.map((r) => r.low);
  const highs = rows.map((r) => r.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const pad = (max - min) * 0.08 || 10;

  return (
    <div style={{ height }} data-testid={testid}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 56, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#1E293B" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="t"
            tick={{ fill: "#64748B", fontSize: 10, fontFamily: "JetBrains Mono Variable" }}
            stroke="#1E293B"
            interval={Math.max(0, Math.floor(rows.length / 9))}
          />
          <YAxis
            domain={[min - pad, max + pad]}
            allowDataOverflow
            tick={{ fill: "#64748B", fontSize: 10, fontFamily: "JetBrains Mono Variable" }}
            stroke="#1E293B"
            orientation="right"
            width={62}
            tickFormatter={(v: number) => num(v, 0)}
          />
          <Tooltip
            contentStyle={{
              background: "#161F30",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 11,
              fontFamily: "JetBrains Mono Variable",
            }}
            labelStyle={{ color: "#94A3B8" }}
            formatter={(value: number, name: string) => {
              if (name === "wick" || name === "body" || name === "wickBase" || name === "bodyBase") return [];
              return [num(value, 2), name.toUpperCase()];
            }}
            labelFormatter={(label: string) => `${label} IST`}
          />
          {/* wick */}
          <Bar dataKey="wickBase" stackId="wick" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="wick" stackId="wick" barSize={1.5} isAnimationActive={false}>
            {rows.map((r, i) => (
              <Cell key={`w-${i}`} fill={r.up ? "#10B981" : "#EF4444"} />
            ))}
          </Bar>
          {/* body */}
          <Bar dataKey="bodyBase" stackId="body" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="body" stackId="body" barSize={5} isAnimationActive={false}>
            {rows.map((r, i) => (
              <Cell key={`b-${i}`} fill={r.up ? "#10B981" : "#EF4444"} />
            ))}
          </Bar>
          <Line dataKey="vwap" stroke="#F59E0B" dot={false} strokeWidth={1.4} name="vwap" isAnimationActive={false} connectNulls />
          <Line dataKey="ema20" stroke="#38BDF8" dot={false} strokeWidth={1.2} name="ema20" isAnimationActive={false} connectNulls />
          <Line dataKey="ema50" stroke="#EC4899" dot={false} strokeWidth={1.2} name="ema50" isAnimationActive={false} connectNulls />
          {supports.slice(0, 2).map((s) => (
            <ReferenceLine
              key={`s-${s}`}
              y={s}
              stroke="#10B981"
              strokeDasharray="5 5"
              strokeOpacity={0.5}
              label={{ value: `S ${num(s, 0)}`, fill: "#10B981", fontSize: 9, position: "insideLeft" }}
            />
          ))}
          {resistances.slice(0, 2).map((r) => (
            <ReferenceLine
              key={`r-${r}`}
              y={r}
              stroke="#F87171"
              strokeDasharray="5 5"
              strokeOpacity={0.5}
              label={{ value: `R ${num(r, 0)}`, fill: "#F87171", fontSize: 9, position: "insideLeft" }}
            />
          ))}
          {signal ? (
            <ReferenceLine
              y={signal.spot_at_signal}
              stroke="#60A5FA"
              strokeWidth={1.2}
              label={{
                value: `SIGNAL ${num(signal.spot_at_signal, 0)}`,
                fill: "#60A5FA",
                fontSize: 9,
                position: "insideTopLeft",
              }}
            />
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[10px] text-slate-500">
        <Legend color="#10B981" label="Bull candle" />
        <Legend color="#EF4444" label="Bear candle" />
        <Legend color="#F59E0B" label="VWAP" />
        <Legend color="#38BDF8" label="EMA 20" />
        <Legend color="#EC4899" label="EMA 50" />
        <Legend color="#10B981" label="Support" dashed />
        <Legend color="#F87171" label="Resistance" dashed />
      </div>
    </div>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-0.5 w-4"
        style={{
          background: dashed
            ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 7px)`
            : color,
        }}
      />
      {label}
    </span>
  );
}

/** Premium-level chart for an option signal: entry band, SL and targets against LTP. */
export function SignalLevelBar({ signal }: { signal: Signal }) {
  const lo = Math.min(signal.stop_loss, signal.option_ltp, signal.entry_min) * 0.96;
  const hi = Math.max(signal.target2, signal.option_ltp, signal.entry_max) * 1.04;
  const place = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="pt-6" data-testid="signal-level-bar">
      <div className="relative h-2 rounded-full bg-slate-800">
        <div
          className="absolute h-2 rounded-full bg-sky-500/30"
          style={{ left: place(signal.entry_min), width: `${((signal.entry_max - signal.entry_min) / (hi - lo)) * 100}%` }}
        />
        <Marker at={place(signal.stop_loss)} color="#EF4444" label="SL" />
        <Marker at={place(signal.target1)} color="#10B981" label="T1" />
        <Marker at={place(signal.target2)} color="#34D399" label="T2" />
        <Marker at={place(signal.option_ltp)} color="#F8FAFC" label="LTP" emphasis />
      </div>
    </div>
  );
}

function Marker({
  at,
  color,
  label,
  emphasis,
}: {
  at: string;
  color: string;
  label: string;
  emphasis?: boolean;
}) {
  return (
    <span className="absolute -top-5 flex -translate-x-1/2 flex-col items-center" style={{ left: at }}>
      <span className="font-mono text-[9px] leading-none" style={{ color }}>
        {label}
      </span>
      <span
        className="mt-1 block rounded-full"
        style={{
          background: color,
          width: emphasis ? 3 : 2,
          height: emphasis ? 14 : 10,
        }}
      />
    </span>
  );
}
