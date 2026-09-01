import { Link } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, signedPct, hours, index, shortDate, varianceState, todayISO } from '../format.js';
import { Card, StatTile, Badge, ProgressBar, Spinner, ErrorNote, Empty } from '../components/ui.jsx';

export default function Portfolio() {
  const { data, error, loading, reload } = useAsync(() => api.portfolio(), []);

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { projects, totals } = data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Portfolio</h1>
          <p className="mt-0.5 text-sm text-muted">
            {totals.project_count} project{totals.project_count === 1 ? '' : 's'} · {totals.active_count} active ·
            {' '}progress at {shortDate(todayISO())}
          </p>
        </div>
        <Link to="/projects/new" className="btn btn-primary">New project</Link>
      </div>

      {projects.length === 0 ? (
        <Card>
          <Empty title="No projects yet">
            Create your first project, then add its deliverables with weights and a schedule.
            Progress, lateness and hours spent are all measured from there.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Portfolio earned"
              value={pct(totals.earned_progress)}
              hint={`vs ${pct(totals.planned_progress)} planned`}
              state={varianceState(totals.variance)}
              stateLabel={`${signedPct(totals.variance)} variance`}
            />
            <StatTile
              label="Late deliverables"
              value={totals.late_count}
              hint="past due, not complete"
              state={totals.late_count > 0 ? 'critical' : 'good'}
              stateLabel={totals.late_count > 0 ? 'Needs attention' : 'None late'}
            />
            <StatTile
              label="Behind plan"
              value={totals.behind_count}
              hint={`${totals.upcoming_count} due in 30 days`}
              state={totals.behind_count > 0 ? 'warning' : 'good'}
              stateLabel={totals.behind_count > 0 ? 'Slipping' : 'On plan'}
            />
            <StatTile
              label="Hours booked"
              value={hours(totals.spent_hours)}
              hint={`of ${hours(totals.budget_hours)} budget`}
              state={totals.hours_used_pct > 1 ? 'critical' : totals.hours_used_pct > 0.9 ? 'warning' : 'good'}
              stateLabel={`${pct(totals.hours_used_pct, 0)} used`}
            />
          </div>

          <Card title="Projects" subtitle="Earned progress against plan, with hours booked against budget"
                bodyClass="p-0">
            <div className="divide-y divide-hairline">
              {projects.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function ProjectRow({ project: p }) {
  const state = varianceState(p.variance);
  return (
    <Link to={`/projects/${p.id}`} className="block px-4 py-3.5 transition hover:bg-[var(--raised)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-[240px] flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">{p.name}</h3>
            <span className="rounded px-1.5 py-0.5 text-xs text-muted" style={{ background: 'var(--plane)' }}>
              {p.code}
            </span>
            {p.status !== 'active' && <Badge>{p.status.replace('_', ' ')}</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {p.client || 'No client set'} · NTP {shortDate(p.ntp_date)} · {p.task_count} deliverables
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {p.late_count > 0 && <Badge state="critical">{p.late_count} late</Badge>}
          {p.behind_count > 0 && <Badge state="warning">{p.behind_count} behind plan</Badge>}
          {p.upcoming_count > 0 && <Badge>{p.upcoming_count} due soon</Badge>}
          {p.late_count === 0 && p.behind_count === 0 && <Badge state="good">On plan</Badge>}
        </div>
      </div>

      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="sm:col-span-2">
          <div className="mb-1 flex items-baseline justify-between text-xs">
            <span className="text-muted">Progress</span>
            <span className="tabular text-ink2">
              <span className="font-medium text-ink">{pct(p.earned_progress)}</span> earned ·
              {' '}{pct(p.planned_progress)} planned
            </span>
          </div>
          <ProgressBar value={p.earned_progress} planned={p.planned_progress} />
          <p className="mt-1 text-xs" style={{ color: `var(--${state === 'good' ? 'good-ink' : state})` }}>
            {signedPct(p.variance)} against plan
          </p>
        </div>

        <Metric label="Hours booked" value={hours(p.spent_hours)} sub={`of ${hours(p.budget_hours)}`} />
        <Metric
          label="Cost performance"
          value={index(p.cpi)}
          sub={p.cpi === null ? 'no hours booked yet' : p.cpi >= 1 ? 'earning more than spending' : 'spending faster than earning'}
        />
      </div>
    </Link>
  );
}

const Metric = ({ label, value, sub }) => (
  <div>
    <p className="text-xs text-muted">{label}</p>
    <p className="tabular mt-0.5 text-sm font-medium text-ink">{value}</p>
    <p className="text-xs text-muted">{sub}</p>
  </div>
);
