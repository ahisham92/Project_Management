import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, signedPct, hours, index, shortDate, num, varianceState, todayISO } from '../format.js';
import { Card, StatTile, Badge, ProgressBar, Spinner, ErrorNote, Field } from '../components/ui.jsx';
import { SCurve, TradeProgressChart, TradeWeightChart, useThemeTick } from '../components/charts.jsx';
import { tradeColor } from '../palette.js';

export default function Dashboard() {
  const { id } = useParams();
  const [dataDate, setDataDate] = useState(todayISO());
  const dark = useThemeTick();

  const { data, error, loading, reload } = useAsync(
    async () => {
      const [detail, curve] = await Promise.all([
        api.project(id, { data_date: dataDate }),
        api.sCurve(id, { data_date: dataDate, steps: 40 }),
      ]);
      return { ...detail, points: curve.points };
    },
    [id, dataDate]
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { project, snapshot, points } = data;
  const t = snapshot.totals;
  const b = snapshot.budget;
  const state = varianceState(t.variance);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">{project.name}</h1>
          <p className="mt-0.5 text-sm text-muted">
            {project.client || 'No client set'} · NTP {shortDate(project.ntp_date)} ·
            {' '}{num(snapshot.elapsed_months, 2)} months elapsed of {project.duration_months}
          </p>
        </div>
        <Field label="Data date" className="w-40">
          <input type="date" className="field" value={dataDate} onChange={(e) => setDataDate(e.target.value)} />
        </Field>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Earned progress"
          value={pct(t.earned_progress, 2)}
          hint={`vs ${pct(t.planned_progress, 2)} planned`}
          state={state}
          stateLabel={`${signedPct(t.variance, 2)} variance`}
        />
        <StatTile
          label="Schedule performance"
          value={index(t.spi)}
          hint={t.spi === null ? 'no planned work yet' : t.spi >= 1 ? 'ahead of plan' : 'behind plan'}
          state={t.spi === null ? 'neutral' : t.spi >= 1 ? 'good' : t.spi >= 0.9 ? 'warning' : 'critical'}
          stateLabel="SPI"
        />
        <StatTile
          label="Hours booked"
          value={hours(b.spent_hours)}
          hint={`of ${hours(b.budget_hours)} · ${num(b.budget_hours / b.hours_per_month, 1)} man-months`}
          state={b.hours_used_pct > 1 ? 'critical' : b.hours_used_pct > 0.9 ? 'warning' : 'good'}
          stateLabel={`${pct(b.hours_used_pct, 0)} used`}
        />
        <StatTile
          label="Late deliverables"
          value={t.late_count}
          hint={`${t.upcoming_count} due within ${snapshot.horizon_days} days`}
          state={t.late_count > 0 ? 'critical' : 'good'}
          stateLabel={t.late_count > 0 ? `${pct(t.weight_at_risk, 1)} of weight at risk` : 'Nothing overdue'}
        />
      </div>

      <Card
        title="Progress S-curve"
        subtitle="Planned progress from the schedule; earned progress reconstructed from what was reported"
      >
        <SCurve points={points} dataDate={snapshot.data_date} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Progress by trade" subtitle="Each trade measured against its own share of the scope">
          <TradeProgressChart trades={snapshot.trades} />
        </Card>
        <Card title="Scope weight by trade" subtitle="Share of total project weight carried by each trade">
          <TradeWeightChart trades={snapshot.trades} />
        </Card>
      </div>

      <Card title="Trade summary" subtitle="The same figures as a table" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-xs text-muted">
                <th className="px-4 py-2 font-medium">Trade</th>
                <th className="px-4 py-2 text-right font-medium">Scope weight</th>
                <th className="px-4 py-2 text-right font-medium">Planned</th>
                <th className="px-4 py-2 text-right font-medium">Earned</th>
                <th className="px-4 py-2 text-right font-medium">Variance</th>
                <th className="px-4 py-2 text-right font-medium">Budget</th>
                <th className="px-4 py-2 text-right font-medium">Booked</th>
                <th className="px-4 py-2 text-right font-medium">CPI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {snapshot.trades.map((tr) => (
                <tr key={tr.id}>
                  <td className="px-4 py-2">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-sm" aria-hidden="true"
                            style={{ background: tradeColor(tr.color, dark) }} />
                      <span className="font-medium text-ink">{tr.name}</span>
                    </span>
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink2">{pct(tr.scope_weight_pct)}</td>
                  <td className="tabular px-4 py-2 text-right text-ink2">{pct(tr.planned_pct_of_trade, 2)}</td>
                  <td className="tabular px-4 py-2 text-right font-medium text-ink">{pct(tr.earned_pct_of_trade, 2)}</td>
                  <td className="tabular px-4 py-2 text-right"
                      style={{ color: tr.schedule_variance_pct >= 0 ? 'var(--good-ink)' : 'var(--critical)' }}>
                    {signedPct(tr.schedule_variance_pct, 2)}
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink2">{hours(tr.budget_hours)}</td>
                  <td className="tabular px-4 py-2 text-right text-ink2">{hours(tr.spent_hours)}</td>
                  <td className="tabular px-4 py-2 text-right text-ink2">{index(tr.cpi)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-hairline font-medium">
                <td className="px-4 py-2 text-ink">Total</td>
                <td className="tabular px-4 py-2 text-right text-ink">100.0%</td>
                <td className="tabular px-4 py-2 text-right text-ink">{pct(t.planned_progress, 2)}</td>
                <td className="tabular px-4 py-2 text-right text-ink">{pct(t.earned_progress, 2)}</td>
                <td className="tabular px-4 py-2 text-right"
                    style={{ color: t.variance >= 0 ? 'var(--good-ink)' : 'var(--critical)' }}>
                  {signedPct(t.variance, 2)}
                </td>
                <td className="tabular px-4 py-2 text-right text-ink">{hours(b.budget_hours)}</td>
                <td className="tabular px-4 py-2 text-right text-ink">{hours(b.spent_hours)}</td>
                <td className="tabular px-4 py-2 text-right text-ink">{index(b.cpi)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Needs attention"
          subtitle={`${t.late_count} late · ${t.behind_count} behind plan`}
          action={<Link to={`/projects/${id}/schedule`} className="btn btn-ghost">Open schedule</Link>}
          bodyClass="p-0"
        >
          <AttentionList tasks={snapshot.tasks.filter((x) => x.is_late || x.is_behind).slice(0, 8)} projectId={id} />
        </Card>

        <Card
          title="Status of deliverables"
          subtitle={`${t.task_count} deliverables · ${t.weighted_count} carry weight`}
        >
          <div className="space-y-3">
            <StatusRow label="Complete" count={t.complete_count} total={t.task_count} color="var(--good)" />
            <StatusRow label="In progress" count={t.in_progress_count} total={t.task_count} color="var(--series-1)" />
            <StatusRow label="Not started" count={t.not_started_count} total={t.task_count} color="var(--grid)" />
            <div className="border-t border-hairline pt-3">
              <StatusRow label="Late" count={t.late_count} total={t.task_count} color="var(--critical)" />
              <div className="h-3" />
              <StatusRow label="Behind plan" count={t.behind_count} total={t.task_count} color="var(--warning)" />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function StatusRow({ label, count, total, color }) {
  const share = total > 0 ? count / total : 0;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-ink2">{label}</span>
        <span className="tabular text-muted">{count} · {pct(share, 0)}</span>
      </div>
      <ProgressBar value={share} color={color} height={6} />
    </div>
  );
}

function AttentionList({ tasks, projectId }) {
  if (!tasks.length) {
    return <p className="px-4 py-8 text-center text-sm text-muted">Nothing late or behind plan.</p>;
  }
  return (
    <ul className="divide-y divide-hairline">
      {tasks.map((task) => (
        <li key={task.id} className="px-4 py-2.5">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm text-ink" title={task.name}>
                <span className="tabular mr-1.5 text-muted">{task.wbs}</span>{task.name}
              </p>
              <p className="mt-0.5 text-xs text-muted">
                Due {shortDate(task.due_date)} · {pct(task.actual_pct, 0)} done of {pct(task.planned_pct, 0)} planned
              </p>
            </div>
            {task.is_late
              ? <Badge state="critical">{task.days_late}d late</Badge>
              : <Badge state="warning">Behind</Badge>}
          </div>
        </li>
      ))}
      <li className="px-4 py-2">
        <Link to={`/projects/${projectId}/tasks`} className="text-xs text-accent hover:underline">
          Update progress →
        </Link>
      </li>
    </ul>
  );
}
