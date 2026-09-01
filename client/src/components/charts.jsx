import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ReferenceLine, Cell,
} from 'recharts';
import { pct, hours, shortDate } from '../format.js';
import { tradeColor, isDark } from '../palette.js';

const AXIS = { fontSize: 11, fill: 'var(--muted)' };

/** Keeps early-project percentages legible without over-precising larger ones. */
const pctTick = (v) => `${Math.abs(v) < 10 && v !== 0 ? v.toFixed(2) : v.toFixed(0)}%`;

/** Re-renders charts when the viewer's theme changes, so series re-step. */
export function useThemeTick() {
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const sync = () => setDark(isDark());
    mq.addEventListener('change', sync);
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { mq.removeEventListener('change', sync); observer.disconnect(); };
  }, []);
  return dark;
}

function TooltipShell({ title, rows }) {
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ background: 'var(--raised)', border: '1px solid var(--border)', color: 'var(--ink)' }}
    >
      <p className="mb-1 font-medium">{title}</p>
      {rows.map((r) => (
        <p key={r.label} className="flex items-center gap-2 whitespace-nowrap">
          <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: r.color }} aria-hidden="true" />
          <span className="text-ink2">{r.label}</span>
          <span className="tabular ml-auto font-medium">{r.value}</span>
        </p>
      ))}
    </div>
  );
}

/** Planned versus earned progress over the life of the project. */
export function SCurve({ points, dataDate, height = 300 }) {
  useThemeTick();
  const data = points.map((p) => ({ ...p, plannedPct: p.planned * 100, earnedPct: p.earned === null ? null : p.earned * 100 }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--axis)' }}
          minTickGap={48} tickFormatter={(d) => shortDate(d).replace(/^\d+ /, '')}
        />
        <YAxis
          tick={AXIS} tickLine={false} axisLine={false} width={52}
          domain={[0, 100]} tickFormatter={(v) => `${v}%`}
        />
        {dataDate && (
          <ReferenceLine
            x={dataDate} stroke="var(--axis)" strokeDasharray="4 3"
            label={{ value: 'Data date', position: 'insideTopRight', fontSize: 10, fill: 'var(--muted)' }}
          />
        )}
        <Tooltip
          cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <TooltipShell
                title={shortDate(label)}
                rows={payload.filter((p) => p.value !== null).map((p) => ({
                  label: p.name, color: p.stroke, value: `${Number(p.value).toFixed(1)}%`,
                }))}
              />
            );
          }}
        />
        <Legend
          verticalAlign="top" align="right" height={28} iconType="plainline"
          wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }}
        />
        <Line
          type="monotone" dataKey="plannedPct" name="Planned" stroke="var(--series-1)"
          strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }}
        />
        <Line
          type="monotone" dataKey="earnedPct" name="Earned" stroke="var(--series-2)"
          strokeWidth={2} dot={false} connectNulls={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Earned against planned progress for each trade, as a share of that trade's own scope. */
export function TradeProgressChart({ trades, height = 260 }) {
  useThemeTick();
  const data = trades.map((t) => ({
    name: t.name,
    planned: t.planned_pct_of_trade * 100,
    earned: t.earned_pct_of_trade * 100,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }} barGap={2}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="name" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--axis)' }} interval={0} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={62} tickFormatter={pctTick} />
        <Tooltip
          cursor={{ fill: 'var(--grid)', fillOpacity: 0.4 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <TooltipShell
                title={label}
                rows={payload.map((p) => ({ label: p.name, color: p.fill, value: `${Number(p.value).toFixed(1)}%` }))}
              />
            );
          }}
        />
        <Legend verticalAlign="top" align="right" height={28} wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }} />
        <Bar dataKey="planned" name="Planned" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
        <Bar dataKey="earned" name="Earned" fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Hours booked against the budget for each trade.
 *
 * Trades are identified by the axis, so colour here carries the booked /
 * remaining / over distinction instead — encoding both at once would leave the
 * legend unable to name a single colour for "booked".
 */
export function BudgetChart({ trades, height = 260 }) {
  useThemeTick();
  const data = trades.map((t) => ({
    name: t.name,
    spent: t.spent_hours,
    remaining: Math.max(0, t.budget_hours - t.spent_hours),
    over: Math.max(0, t.spent_hours - t.budget_hours),
    budget: t.budget_hours,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--axis)' }} />
        <YAxis type="category" dataKey="name" tick={AXIS} tickLine={false} axisLine={false} width={120} />
        <Tooltip
          cursor={{ fill: 'var(--grid)', fillOpacity: 0.4 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return (
              <TooltipShell
                title={d.name}
                rows={[
                  { label: 'Budget', color: 'var(--muted)', value: hours(d.budget) },
                  { label: 'Booked', color: 'var(--series-1)', value: hours(d.spent) },
                  d.over > 0
                    ? { label: 'Over budget', color: 'var(--critical)', value: hours(d.over) }
                    : { label: 'Remaining', color: 'var(--grid)', value: hours(d.remaining) },
                ]}
              />
            );
          }}
        />
        <Legend verticalAlign="top" align="right" height={28} wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }} />
        {/* A 2px surface gap keeps the booked and remaining segments from touching. */}
        <Bar dataKey="spent" name="Booked" stackId="h" fill="var(--series-1)"
             maxBarSize={22} stroke="var(--surface)" strokeWidth={2} />
        <Bar dataKey="remaining" name="Remaining budget" stackId="h" fill="var(--grid)"
             radius={[0, 4, 4, 0]} maxBarSize={22} stroke="var(--surface)" strokeWidth={2} />
        <Bar dataKey="over" name="Over budget" stackId="h" fill="var(--critical)"
             radius={[0, 4, 4, 0]} maxBarSize={22} stroke="var(--surface)" strokeWidth={2} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Share of total project weight carried by each trade. */
export function TradeWeightChart({ trades, height = 200 }) {
  const dark = useThemeTick();
  const data = trades.map((t) => ({ name: t.name, weight: t.scope_weight_pct * 100, color: tradeColor(t.color, dark) }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 8 }}>
        <XAxis type="number" hide domain={[0, Math.max(...data.map((d) => d.weight), 1) * 1.15]} />
        <YAxis type="category" dataKey="name" tick={AXIS} tickLine={false} axisLine={false} width={120} />
        <Tooltip
          cursor={{ fill: 'var(--grid)', fillOpacity: 0.4 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return <TooltipShell title={d.name} rows={[{ label: 'Share of project weight', color: d.color, value: `${d.weight.toFixed(1)}%` }]} />;
          }}
        />
        <Bar
          dataKey="weight" radius={[0, 4, 4, 0]} maxBarSize={18}
          label={{ position: 'right', fontSize: 11, fill: 'var(--ink-2)', formatter: (v) => `${v.toFixed(1)}%` }}
        >
          {data.map((d) => <Cell key={d.name} fill={d.color} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export { pct };
