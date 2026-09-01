import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, signedPct, shortDate, todayISO, num } from '../format.js';
import { Card, Badge, ProgressBar, Spinner, ErrorNote, Field, Empty } from '../components/ui.jsx';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'late', label: 'Late' },
  { key: 'behind', label: 'Behind plan' },
  { key: 'open', label: 'In progress' },
  { key: 'notstarted', label: 'Not started' },
  { key: 'complete', label: 'Complete' },
];

export default function Tasks() {
  const { id } = useParams();
  const [dataDate, setDataDate] = useState(todayISO());
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState(null);   // task id being updated
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [draft, setDraft] = useState({ actual: '', note: '' });

  const { data, error, loading, reload } = useAsync(
    () => api.project(id, { data_date: dataDate }), [id, dataDate]
  );

  const grouped = useMemo(() => {
    if (!data) return [];
    const term = search.trim().toLowerCase();
    const keep = (t) => {
      if (term && !`${t.wbs} ${t.name}`.toLowerCase().includes(term)) return false;
      switch (filter) {
        case 'late': return t.is_late;
        case 'behind': return t.is_behind;
        case 'open': return t.actual_pct > 0 && t.actual_pct < 1;
        case 'notstarted': return t.actual_pct <= 0;
        case 'complete': return t.is_complete;
        default: return true;
      }
    };
    const bySection = new Map();
    for (const task of data.snapshot.tasks) {
      if (!keep(task)) continue;
      const key = task.section_id ?? 'none';
      if (!bySection.has(key)) {
        bySection.set(key, {
          id: key,
          name: task.section_name || 'Unassigned',
          code: task.section_code || '',
          tasks: [],
        });
      }
      bySection.get(key).tasks.push(task);
    }
    return [...bySection.values()];
  }, [data, filter, search]);

  const startEdit = (task) => {
    setEditing(task.id);
    setSaveError('');
    setDraft({ actual: String(Math.round(task.actual_pct * 100)), note: '' });
  };

  const save = async (task) => {
    const value = Number(draft.actual);
    if (Number.isNaN(value) || value < 0 || value > 100) {
      setSaveError('Enter a percentage between 0 and 100');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      await api.recordProgress(task.id, {
        actual_pct: value / 100,
        note: draft.note,
        data_date: dataDate,
      });
      setEditing(null);
      await reload();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { snapshot, project } = data;
  const readOnly = data.role === 'viewer';
  const shown = grouped.reduce((s, g) => s + g.tasks.length, 0);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Progress update</h1>
          <p className="mt-0.5 text-sm text-muted">
            {project.name} · {pct(snapshot.totals.earned_progress, 2)} earned of
            {' '}{pct(snapshot.totals.planned_progress, 2)} planned
            {' '}({signedPct(snapshot.totals.variance, 2)})
          </p>
        </div>
        <Field label="Report progress as at" className="w-44">
          <input type="date" className="field" value={dataDate} onChange={(e) => setDataDate(e.target.value)} />
        </Field>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-lg p-1" style={{ background: 'var(--surface)' }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className="rounded-md px-2.5 py-1 text-xs font-medium transition"
              style={filter === f.key
                ? { background: 'var(--series-1)', color: '#fff' }
                : { color: 'var(--ink-2)' }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          className="field max-w-xs flex-1"
          placeholder="Search deliverables…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-xs text-muted">{shown} shown</span>
      </div>

      {readOnly && (
        <p className="rounded-lg px-3 py-2 text-xs text-ink2" style={{ background: 'var(--surface)' }}>
          You have view-only access to this project, so progress cannot be changed here.
        </p>
      )}

      {grouped.length === 0 ? (
        <Card><Empty title="Nothing matches this filter">Try a different filter or clear the search.</Empty></Card>
      ) : (
        grouped.map((section) => (
          <Card
            key={section.id}
            title={section.name}
            subtitle={`${section.tasks.length} deliverable${section.tasks.length === 1 ? '' : 's'} · ${
              pct(section.tasks.reduce((s, t) => s + t.weight_pct, 0), 1)} of project weight`}
            bodyClass="p-0"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-xs text-muted">
                    <th className="px-3 py-2 font-medium">WBS</th>
                    <th className="px-3 py-2 font-medium">Deliverable</th>
                    <th className="px-3 py-2 text-right font-medium">Weight</th>
                    <th className="px-3 py-2 text-right font-medium">Due</th>
                    <th className="px-3 py-2 text-right font-medium">Planned</th>
                    <th className="px-3 py-2 font-medium" style={{ minWidth: 190 }}>Actual</th>
                    <th className="px-3 py-2 text-right font-medium">Variance</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {section.tasks.map((task) => (
                    <tr key={task.id} className={editing === task.id ? 'bg-[var(--raised)]' : undefined}>
                      <td className="tabular whitespace-nowrap px-3 py-2 align-top text-xs text-muted">{task.wbs}</td>
                      <td className="px-3 py-2 align-top">
                        <p className="text-ink">{task.name}</p>
                        {task.remarks && <p className="mt-0.5 text-xs text-muted">{task.remarks}</p>}
                        {editing === task.id && (
                          <div className="mt-2 space-y-2">
                            <input
                              className="field"
                              placeholder="Note for this update (optional)"
                              value={draft.note}
                              onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))}
                            />
                            {saveError && <ErrorNote>{saveError}</ErrorNote>}
                          </div>
                        )}
                      </td>
                      <td className="tabular px-3 py-2 align-top text-right text-ink2">
                        {pct(task.weight_pct, 2)}
                        <span className="block text-xs text-muted">{num(task.weight_points, 1)} pts</span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 align-top text-right text-xs text-ink2">
                        {shortDate(task.due_date)}
                        <span className="block text-muted">
                          {task.is_milestone ? 'milestone' : `mo ${num(task.start_month, 1)}–${num(task.finish_month, 1)}`}
                        </span>
                      </td>
                      <td className="tabular px-3 py-2 align-top text-right text-ink2">{pct(task.planned_pct, 0)}</td>
                      <td className="px-3 py-2 align-top">
                        {editing === task.id ? (
                          <div className="flex items-center gap-1.5">
                            <input
                              type="number" min="0" max="100" step="1" autoFocus
                              className="field w-20 text-right"
                              value={draft.actual}
                              onChange={(e) => setDraft((d) => ({ ...d, actual: e.target.value }))}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') save(task);
                                if (e.key === 'Escape') setEditing(null);
                              }}
                            />
                            <span className="text-xs text-muted">%</span>
                          </div>
                        ) : (
                          <div className="min-w-[150px]">
                            <div className="mb-1 flex items-baseline justify-between text-xs">
                              <span className="tabular font-medium text-ink">{pct(task.actual_pct, 0)}</span>
                              <span className="text-muted">plan {pct(task.planned_pct, 0)}</span>
                            </div>
                            <ProgressBar
                              value={task.actual_pct}
                              planned={task.planned_pct}
                              color={task.is_late ? 'var(--critical)' : task.is_behind ? 'var(--warning)' : 'var(--series-1)'}
                              height={6}
                            />
                          </div>
                        )}
                      </td>
                      <td className="tabular px-3 py-2 align-top text-right"
                          style={{ color: task.variance >= 0 ? 'var(--good-ink)' : 'var(--critical)' }}>
                        {signedPct(task.variance, 2)}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <TaskStatus task={task} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 align-top text-right">
                        {editing === task.id ? (
                          <span className="flex gap-1">
                            <button type="button" className="btn btn-primary px-2 py-1"
                                    disabled={saving} onClick={() => save(task)}>
                              {saving ? 'Saving…' : 'Save'}
                            </button>
                            <button type="button" className="btn btn-ghost px-2 py-1"
                                    disabled={saving} onClick={() => setEditing(null)}>
                              Cancel
                            </button>
                          </span>
                        ) : (
                          !readOnly && (
                            <button type="button" className="btn btn-ghost px-2 py-1"
                                    onClick={() => startEdit(task)}>
                              Update
                            </button>
                          )
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}

function TaskStatus({ task }) {
  if (task.is_late) return <Badge state="critical" title={`Due ${task.due_date}`}>{task.days_late}d late</Badge>;
  if (task.is_complete) return <Badge state="good">Complete</Badge>;
  if (task.is_behind) return <Badge state="warning">Behind plan</Badge>;
  if (task.is_upcoming) return <Badge state="serious">Due in {task.days_to_due}d</Badge>;
  if (task.actual_pct > 0) return <Badge state="good">On plan</Badge>;
  return <Badge>Not started</Badge>;
}
