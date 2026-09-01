import { useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, hours, index, num, todayISO } from '../format.js';
import { Card, StatTile, Badge, Spinner, ErrorNote, Field, ProgressBar } from '../components/ui.jsx';
import { BudgetChart, useThemeTick } from '../components/charts.jsx';
import { tradeColor } from '../palette.js';

const statusState = (status) => ({
  'Under / on budget': 'good',
  'Slightly over-burning': 'warning',
  'Over-burning': 'critical',
  'Over budget': 'critical',
  'No spend booked': 'neutral',
}[status] || 'neutral');

export default function Budget() {
  const { id } = useParams();
  const [dataDate, setDataDate] = useState(todayISO());
  const dark = useThemeTick();

  const { data, error, loading, reload } = useAsync(
    () => api.budget(id, { data_date: dataDate }), [id, dataDate]
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { budget: b, trades } = data;
  const perMonth = b.hours_per_month || 176;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Budget control</h1>
          <p className="mt-0.5 text-sm text-muted">
            Hours booked against budget, and against the progress those hours earned
          </p>
        </div>
        <Field label="Data date" className="w-40">
          <input type="date" className="field" value={dataDate} onChange={(e) => setDataDate(e.target.value)} />
        </Field>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Hours booked"
          value={hours(b.spent_hours)}
          hint={`of ${hours(b.budget_hours)} budget`}
          state={b.hours_used_pct > 1 ? 'critical' : b.hours_used_pct > 0.9 ? 'warning' : 'good'}
          stateLabel={`${pct(b.hours_used_pct, 0)} used`}
        />
        <StatTile
          label="Hours earned by progress"
          value={hours(b.earned_hours)}
          hint="budget × progress achieved"
          state={b.hours_over_under <= 0 ? 'good' : 'warning'}
          stateLabel={b.hours_over_under > 0
            ? `${hours(b.hours_over_under)} ahead of earned`
            : `${hours(-b.hours_over_under)} under earned`}
        />
        <StatTile
          label="Cost performance"
          value={index(b.cpi)}
          hint={b.cpi === null ? 'no hours booked yet' : 'earned ÷ booked'}
          state={statusState(b.budget_status)}
          stateLabel={b.budget_status}
        />
        <StatTile
          label="Forecast at completion"
          value={hours(b.eac_hours)}
          hint={`${num(b.eac_hours / perMonth, 1)} man-months`}
          state={b.vac_hours >= 0 ? 'good' : 'critical'}
          stateLabel={b.vac_hours >= 0
            ? `${hours(b.vac_hours)} under budget`
            : `${hours(-b.vac_hours)} over budget`}
        />
      </div>

      <Card title="Hours against budget by trade" subtitle="Booked hours, remaining budget, and any overrun">
        <BudgetChart trades={trades} />
      </Card>

      <Card
        title="Trade budget control"
        subtitle={`Man-month equivalents use ${perMonth} hours per month`}
        bodyClass="p-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-xs text-muted">
                <th className="px-3 py-2 font-medium">Trade</th>
                <th className="px-3 py-2 text-right font-medium">Budget</th>
                <th className="px-3 py-2 text-right font-medium">Man-months</th>
                <th className="px-3 py-2 text-right font-medium">Booked</th>
                <th className="px-3 py-2 font-medium" style={{ minWidth: 130 }}>Used</th>
                <th className="px-3 py-2 text-right font-medium">Earned</th>
                <th className="px-3 py-2 text-right font-medium">Over / (under)</th>
                <th className="px-3 py-2 text-right font-medium">CPI</th>
                <th className="px-3 py-2 text-right font-medium">Forecast</th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {trades.map((t) => (
                <tr key={t.id}>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-sm" aria-hidden="true"
                            style={{ background: tradeColor(t.color, dark) }} />
                      <span className="font-medium text-ink">{t.name}</span>
                    </span>
                  </td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{hours(t.budget_hours)}</td>
                  <td className="tabular px-3 py-2 text-right text-muted">{num(t.budget_months, 1)}</td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{hours(t.spent_hours)}</td>
                  <td className="px-3 py-2">
                    <div className="mb-1 text-right text-xs tabular text-muted">{pct(t.hours_used_pct, 0)}</div>
                    <ProgressBar
                      value={Math.min(1, t.hours_used_pct)} height={6}
                      color={t.hours_used_pct > 1 ? 'var(--critical)' : tradeColor(t.color, dark)}
                    />
                  </td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{hours(t.earned_hours, 1)}</td>
                  <td className="tabular px-3 py-2 text-right"
                      style={{ color: t.hours_over_under > 0 ? 'var(--critical)' : 'var(--good-ink)' }}>
                    {t.hours_over_under > 0 ? hours(t.hours_over_under, 1) : `(${hours(-t.hours_over_under, 1)})`}
                  </td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{index(t.cpi)}</td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{hours(t.eac_hours)}</td>
                  <td className="px-3 py-2"><Badge state={statusState(t.budget_status)}>{t.budget_status}</Badge></td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-hairline font-medium">
                <td className="px-3 py-2 text-ink">Total</td>
                <td className="tabular px-3 py-2 text-right text-ink">{hours(b.budget_hours)}</td>
                <td className="tabular px-3 py-2 text-right text-ink2">{num(b.budget_hours / perMonth, 1)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{hours(b.spent_hours)}</td>
                <td className="tabular px-3 py-2 text-right text-ink2">{pct(b.hours_used_pct, 0)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{hours(b.earned_hours, 1)}</td>
                <td className="tabular px-3 py-2 text-right"
                    style={{ color: b.hours_over_under > 0 ? 'var(--critical)' : 'var(--good-ink)' }}>
                  {b.hours_over_under > 0 ? hours(b.hours_over_under, 1) : `(${hours(-b.hours_over_under, 1)})`}
                </td>
                <td className="tabular px-3 py-2 text-right text-ink">{index(b.cpi)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{hours(b.eac_hours)}</td>
                <td className="px-3 py-2"><Badge state={statusState(b.budget_status)}>{b.budget_status}</Badge></td>
              </tr>
            </tfoot>
          </table>
        </div>
        {b.unallocated_hours > 0 && (
          <p className="border-t border-hairline px-3 py-2 text-xs text-muted">
            {hours(b.unallocated_hours)} booked without a trade are included in the project total but not in any trade row.
          </p>
        )}
      </Card>

      <Card title="How these figures are built">
        <ul className="space-y-1.5 text-xs text-ink2">
          <li><strong className="text-ink">Earned hours</strong> = a trade&apos;s budget × the progress achieved on its share of the scope.</li>
          <li><strong className="text-ink">CPI</strong> = earned ÷ booked. Above 1.00 means progress is outrunning the hours spent.</li>
          <li><strong className="text-ink">Forecast (EAC)</strong> = budget ÷ CPI — what the trade lands at if it keeps burning at the current rate.</li>
          <li><strong className="text-ink">Over / (under)</strong> = booked − earned. A positive number is hours spent ahead of progress delivered.</li>
        </ul>
      </Card>
    </div>
  );
}
