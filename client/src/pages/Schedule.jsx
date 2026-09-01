import { useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, signedPct, shortDate, todayISO, num } from '../format.js';
import { Card, StatTile, Badge, Spinner, ErrorNote, Empty, Field, ProgressBar } from '../components/ui.jsx';

const HORIZONS = [7, 14, 30, 60, 90];

export default function Schedule() {
  const { id } = useParams();
  const [dataDate, setDataDate] = useState(todayISO());
  const [horizon, setHorizon] = useState(30);

  const { data, error, loading, reload } = useAsync(
    () => api.schedule(id, { data_date: dataDate, horizon }), [id, dataDate, horizon]
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { late, upcoming, behind, totals } = data;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Schedule</h1>
          <p className="mt-0.5 text-sm text-muted">
            What is overdue, what is slipping, and what is coming up
          </p>
        </div>
        <div className="flex items-end gap-2">
          <Field label="Data date" className="w-40">
            <input type="date" className="field" value={dataDate} onChange={(e) => setDataDate(e.target.value)} />
          </Field>
          <Field label="Look ahead" className="w-32">
            <select className="field" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {HORIZONS.map((h) => <option key={h} value={h}>{h} days</option>)}
            </select>
          </Field>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Late" value={totals.late_count} hint="past due, not complete"
                  state={totals.late_count ? 'critical' : 'good'}
                  stateLabel={totals.late_count ? `${pct(totals.weight_at_risk)} of weight` : 'None'} />
        <StatTile label="Due soon" value={totals.upcoming_count} hint={`within ${horizon} days`}
                  state={totals.upcoming_count ? 'serious' : 'good'} stateLabel="Upcoming" />
        <StatTile label="Behind plan" value={totals.behind_count} hint="actual below planned"
                  state={totals.behind_count ? 'warning' : 'good'}
                  stateLabel={totals.behind_count ? 'Slipping' : 'On plan'} />
        <StatTile label="Complete" value={totals.complete_count} hint={`of ${totals.task_count} deliverables`}
                  state="good" stateLabel={pct(totals.task_count ? totals.complete_count / totals.task_count : 0, 0)} />
      </div>

      <TaskGroup
        title="Late deliverables"
        subtitle="Past their submission date and not complete"
        tasks={late}
        emptyTitle="Nothing overdue"
        emptyBody="Every deliverable past its submission date is complete."
        badge={(t) => <Badge state="critical">{t.days_late} day{t.days_late === 1 ? '' : 's'} late</Badge>}
      />

      <TaskGroup
        title={`Due in the next ${horizon} days`}
        subtitle="Upcoming submissions, soonest first"
        tasks={upcoming}
        emptyTitle="Nothing due in this window"
        emptyBody="Widen the look-ahead to see submissions further out."
        badge={(t) => <Badge state={t.days_to_due <= 7 ? 'serious' : 'neutral'}>in {t.days_to_due} days</Badge>}
      />

      <TaskGroup
        title="Behind plan"
        subtitle="Not yet late, but reporting less progress than the schedule expects"
        tasks={behind}
        emptyTitle="Nothing behind plan"
        emptyBody="Reported progress is at or above the planned curve on every deliverable."
        badge={(t) => <Badge state="warning">{signedPct(t.variance, 2)}</Badge>}
      />
    </div>
  );
}

function TaskGroup({ title, subtitle, tasks, badge, emptyTitle, emptyBody }) {
  return (
    <Card title={title} subtitle={`${tasks.length} · ${subtitle}`} bodyClass="p-0">
      {tasks.length === 0 ? (
        <Empty title={emptyTitle}>{emptyBody}</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-xs text-muted">
                <th className="px-3 py-2 font-medium">WBS</th>
                <th className="px-3 py-2 font-medium">Deliverable</th>
                <th className="px-3 py-2 font-medium">Section</th>
                <th className="px-3 py-2 text-right font-medium">Weight</th>
                <th className="px-3 py-2 text-right font-medium">Planned start</th>
                <th className="px-3 py-2 text-right font-medium">Due</th>
                <th className="px-3 py-2 font-medium" style={{ minWidth: 150 }}>Progress</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td className="tabular whitespace-nowrap px-3 py-2 text-xs text-muted">{t.wbs}</td>
                  <td className="px-3 py-2 text-ink">{t.name}</td>
                  <td className="px-3 py-2 text-xs text-muted">{t.section_name || '—'}</td>
                  <td className="tabular px-3 py-2 text-right text-ink2">{pct(t.weight_pct, 2)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-ink2">{shortDate(t.planned_start)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-ink2">{shortDate(t.due_date)}</td>
                  <td className="px-3 py-2">
                    <div className="mb-1 flex items-baseline justify-between text-xs">
                      <span className="tabular font-medium text-ink">{pct(t.actual_pct, 0)}</span>
                      <span className="text-muted">plan {pct(t.planned_pct, 0)}</span>
                    </div>
                    <ProgressBar
                      value={t.actual_pct} planned={t.planned_pct} height={6}
                      color={t.is_late ? 'var(--critical)' : t.is_behind ? 'var(--warning)' : 'var(--series-1)'}
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">{badge(t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
