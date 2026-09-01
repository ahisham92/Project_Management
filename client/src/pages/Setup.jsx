import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { pct, num, hours } from '../format.js';
import { Card, Field, Spinner, ErrorNote, Badge, Empty } from '../components/ui.jsx';
import { SERIES, tradeColor } from '../palette.js';
import { useThemeTick } from '../components/charts.jsx';

export default function Setup() {
  const { id } = useParams();
  const navigate = useNavigate();
  const dark = useThemeTick();
  const [notice, setNotice] = useState('');

  const { data, error, loading, reload } = useAsync(
    async () => {
      const [detail, tradeList, memberList] = await Promise.all([
        api.project(id), api.trades(id), api.members(id),
      ]);
      return { detail, trades: tradeList.trades, members: memberList };
    },
    [id]
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { detail, trades, members } = data;
  const { project, sections, snapshot } = detail;
  const canEdit = ['owner', 'manager'].includes(detail.role);

  const flash = (msg) => { setNotice(msg); setTimeout(() => setNotice(''), 2500); };

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Project setup</h1>
          <p className="mt-0.5 text-sm text-muted">
            Deliverables, weights, schedule and trade split — the basis of every figure in this project
          </p>
        </div>
        {notice && <Badge state="good">{notice}</Badge>}
      </header>

      {!canEdit && (
        <p className="rounded-lg px-3 py-2 text-xs text-ink2" style={{ background: 'var(--surface)' }}>
          You need manager access to change the project setup.
        </p>
      )}

      <ProjectForm project={project} canEdit={canEdit} onSaved={() => { reload(); flash('Project saved'); }} />

      <TradesEditor
        projectId={id} trades={trades} snapshot={snapshot} dark={dark} canEdit={canEdit}
        onChange={() => { reload(); flash('Trades updated'); }}
      />

      <SectionsEditor
        projectId={id} sections={sections} canEdit={canEdit}
        onChange={() => { reload(); flash('Sections updated'); }}
      />

      <DeliverablesEditor
        projectId={id} snapshot={snapshot} sections={sections} trades={trades} canEdit={canEdit}
        onChange={() => { reload(); flash('Deliverables updated'); }}
      />

      <TeamEditor
        projectId={id} members={members} canEdit={canEdit}
        onChange={() => { reload(); flash('Team updated'); }}
      />

      {detail.role === 'owner' && (
        <Card title="Delete project" subtitle="Removes the project and every deliverable, progress record and timesheet entry">
          <button
            type="button"
            className="btn btn-danger"
            onClick={async () => {
              if (!window.confirm(`Delete "${project.name}" and all of its data? This cannot be undone.`)) return;
              await api.deleteProject(id);
              navigate('/');
            }}
          >
            Delete this project
          </button>
        </Card>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ project */

function ProjectForm({ project, canEdit, onSaved }) {
  const [form, setForm] = useState({
    name: project.name, code: project.code, client: project.client, description: project.description,
    ntp_date: project.ntp_date, duration_months: project.duration_months,
    days_per_month: project.days_per_month, hours_per_month: project.hours_per_month,
    elapsed_day_offset: project.elapsed_day_offset ?? 0, status: project.status,
  });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await api.updateProject(project.id, {
        ...form,
        duration_months: Number(form.duration_months),
        days_per_month: Number(form.days_per_month),
        hours_per_month: Number(form.hours_per_month),
        elapsed_day_offset: Number(form.elapsed_day_offset),
      });
      onSaved();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <Card title="Project details">
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        <Field label="Project name" className="sm:col-span-2">
          <input className="field" value={form.name} onChange={set('name')} disabled={!canEdit} />
        </Field>
        <Field label="Code"><input className="field" value={form.code} onChange={set('code')} disabled={!canEdit} /></Field>
        <Field label="Client"><input className="field" value={form.client} onChange={set('client')} disabled={!canEdit} /></Field>
        <Field label="Notice to proceed">
          <input type="date" className="field" value={form.ntp_date} onChange={set('ntp_date')} disabled={!canEdit} />
        </Field>
        <Field label="Duration (months)">
          <input type="number" min="0.5" step="0.5" className="field" value={form.duration_months}
                 onChange={set('duration_months')} disabled={!canEdit} />
        </Field>
        <Field label="Days per month">
          <input type="number" min="1" step="0.0001" className="field" value={form.days_per_month}
                 onChange={set('days_per_month')} disabled={!canEdit} />
        </Field>
        <Field label="Hours per man-month">
          <input type="number" min="1" step="1" className="field" value={form.hours_per_month}
                 onChange={set('hours_per_month')} disabled={!canEdit} />
        </Field>
        <Field label="Status">
          <select className="field" value={form.status} onChange={set('status')} disabled={!canEdit}>
            <option value="active">Active</option>
            <option value="on_hold">On hold</option>
            <option value="complete">Complete</option>
            <option value="archived">Archived</option>
          </select>
        </Field>
        <Field
          label="Elapsed time convention"
          hint="Affects planned progress only, not earned progress."
        >
          <select className="field" value={form.elapsed_day_offset} onChange={set('elapsed_day_offset')} disabled={!canEdit}>
            <option value={0}>Month 0 = NTP (no elapsed time on day one)</option>
            <option value={1}>Count the NTP day as one day worked</option>
          </select>
        </Field>
        <Field label="Description" className="sm:col-span-2">
          <textarea className="field" rows={2} value={form.description} onChange={set('description')} disabled={!canEdit} />
        </Field>
        {error && <div className="sm:col-span-2"><ErrorNote>{error}</ErrorNote></div>}
        {canEdit && (
          <div className="sm:col-span-2 flex justify-end">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? 'Saving…' : 'Save project'}
            </button>
          </div>
        )}
      </form>
    </Card>
  );
}

/* ------------------------------------------------------------------- trades */

function TradesEditor({ projectId, trades, snapshot, dark, canEdit, onChange }) {
  const [draft, setDraft] = useState({ name: '', budget_hours: '', color: SERIES[0].light });
  const [error, setError] = useState('');
  const budgetOf = (id) => snapshot.trades.find((t) => t.id === id) || {};

  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await api.createTrade(projectId, {
        name: draft.name.trim(),
        budget_hours: Number(draft.budget_hours) || 0,
        color: draft.color,
      });
      setDraft({ name: '', budget_hours: '', color: SERIES[trades.length % SERIES.length].light });
      onChange();
    } catch (err) { setError(err.message); }
  };

  const update = async (trade, patch) => {
    setError('');
    try { await api.updateTrade(projectId, trade.id, patch); onChange(); }
    catch (err) { setError(err.message); }
  };

  return (
    <Card title="Trades" subtitle="Disciplines that carry the hour budget" bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">Colour</th>
              <th className="px-4 py-2 font-medium">Trade</th>
              <th className="px-4 py-2 text-right font-medium">Budget (hours)</th>
              <th className="px-4 py-2 text-right font-medium">Scope weight</th>
              <th className="px-4 py-2 text-right font-medium">Booked</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {trades.map((t) => (
              <tr key={t.id}>
                <td className="px-4 py-2">
                  <select
                    className="field w-28" value={t.color} disabled={!canEdit}
                    onChange={(e) => update(t, { color: e.target.value })}
                    style={{ color: tradeColor(t.color, dark) }}
                  >
                    {SERIES.map((s) => <option key={s.light} value={s.light}>{s.name}</option>)}
                  </select>
                </td>
                <td className="px-4 py-2">
                  <input
                    className="field" defaultValue={t.name} disabled={!canEdit}
                    onBlur={(e) => e.target.value.trim() !== t.name && update(t, { name: e.target.value.trim() })}
                  />
                </td>
                <td className="px-4 py-2 text-right">
                  <input
                    type="number" min="0" step="1" className="field w-32 text-right"
                    defaultValue={t.budget_hours} disabled={!canEdit}
                    onBlur={(e) => Number(e.target.value) !== t.budget_hours &&
                      update(t, { budget_hours: Number(e.target.value) || 0 })}
                  />
                </td>
                <td className="tabular px-4 py-2 text-right text-ink2">{pct(budgetOf(t.id).scope_weight_pct)}</td>
                <td className="tabular px-4 py-2 text-right text-ink2">{hours(budgetOf(t.id).spent_hours)}</td>
                <td className="px-4 py-2 text-right">
                  {canEdit && (
                    <button
                      type="button" className="btn btn-danger px-2 py-0.5 text-xs"
                      onClick={async () => {
                        if (!window.confirm(`Remove the "${t.name}" trade? Its share of each deliverable is removed too.`)) return;
                        await api.deleteTrade(projectId, t.id);
                        onChange();
                      }}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2 border-t border-hairline p-4">
          <Field label="New trade" className="min-w-[180px] flex-1">
            <input className="field" value={draft.name} required
                   onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          </Field>
          <Field label="Budget (hours)" className="w-36">
            <input type="number" min="0" step="1" className="field" value={draft.budget_hours}
                   onChange={(e) => setDraft((d) => ({ ...d, budget_hours: e.target.value }))} />
          </Field>
          <Field label="Colour" className="w-32">
            <select className="field" value={draft.color}
                    onChange={(e) => setDraft((d) => ({ ...d, color: e.target.value }))}>
              {SERIES.map((s) => <option key={s.light} value={s.light}>{s.name}</option>)}
            </select>
          </Field>
          <button type="submit" className="btn btn-primary">Add trade</button>
          {error && <div className="w-full"><ErrorNote>{error}</ErrorNote></div>}
        </form>
      )}
    </Card>
  );
}

/* ----------------------------------------------------------------- sections */

function SectionsEditor({ projectId, sections, canEdit, onChange }) {
  const [draft, setDraft] = useState({ code: '', name: '' });
  const [error, setError] = useState('');

  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await api.createSection(projectId, { code: draft.code.trim(), name: draft.name.trim() });
      setDraft({ code: '', name: '' });
      onChange();
    } catch (err) { setError(err.message); }
  };

  return (
    <Card title="Sections" subtitle="Groups of deliverables, mirroring your scope document" bodyClass="p-0">
      {sections.length === 0 ? (
        <Empty title="No sections yet">Sections group the deliverable list; add one below.</Empty>
      ) : (
        <ul className="divide-y divide-hairline">
          {sections.map((s) => (
            <li key={s.id} className="flex items-center gap-2 px-4 py-2">
              <input
                className="field w-20" defaultValue={s.code} disabled={!canEdit} placeholder="code"
                onBlur={(e) => e.target.value !== s.code && api.updateSection(projectId, s.id, { code: e.target.value }).then(onChange)}
              />
              <input
                className="field flex-1" defaultValue={s.name} disabled={!canEdit}
                onBlur={(e) => e.target.value.trim() && e.target.value !== s.name &&
                  api.updateSection(projectId, s.id, { name: e.target.value.trim() }).then(onChange)}
              />
              {canEdit && (
                <button
                  type="button" className="btn btn-danger px-2 py-1 text-xs"
                  onClick={async () => {
                    if (!window.confirm(`Remove section "${s.name}"? Its deliverables stay but become unassigned.`)) return;
                    await api.deleteSection(projectId, s.id);
                    onChange();
                  }}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2 border-t border-hairline p-4">
          <Field label="Code" className="w-24">
            <input className="field" value={draft.code}
                   onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))} placeholder="1.0" />
          </Field>
          <Field label="New section" className="min-w-[200px] flex-1">
            <input className="field" value={draft.name} required
                   onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          </Field>
          <button type="submit" className="btn btn-primary">Add section</button>
          {error && <div className="w-full"><ErrorNote>{error}</ErrorNote></div>}
        </form>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------- deliverables */

const emptyTask = (sections) => ({
  wbs: '', name: '', weight_points: '', start_month: 0, finish_month: 1,
  section_id: sections[0]?.id ?? '', remarks: '',
});

function DeliverablesEditor({ projectId, snapshot, sections, trades, canEdit, onChange }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(() => emptyTask(sections));
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState('');

  const tasks = snapshot.tasks;
  const totalPoints = snapshot.total_weight_points;

  const evenSplit = () => {
    if (!trades.length) return {};
    const share = 1 / trades.length;
    return Object.fromEntries(trades.map((t) => [t.id, share]));
  };

  const create = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await api.createTask(projectId, {
        wbs: draft.wbs.trim(),
        name: draft.name.trim(),
        weight_points: Number(draft.weight_points) || 0,
        start_month: Number(draft.start_month) || 0,
        finish_month: Number(draft.finish_month) || 0,
        section_id: draft.section_id ? Number(draft.section_id) : null,
        remarks: draft.remarks,
        allocations: evenSplit(),
      });
      setDraft(emptyTask(sections));
      setAdding(false);
      onChange();
    } catch (err) { setError(err.message); }
  };

  return (
    <Card
      title="Deliverables"
      subtitle={`${tasks.length} lines · ${num(totalPoints, 1)} weight points · weights are relative, so they always total 100%`}
      action={canEdit && (
        <button type="button" className="btn btn-primary" onClick={() => setAdding((v) => !v)}>
          {adding ? 'Cancel' : 'Add deliverable'}
        </button>
      )}
      bodyClass="p-0"
    >
      {adding && (
        <form onSubmit={create} className="grid gap-3 border-b border-hairline p-4 sm:grid-cols-6">
          <Field label="WBS" className="sm:col-span-1">
            <input className="field" value={draft.wbs} placeholder="1.1"
                   onChange={(e) => setDraft((d) => ({ ...d, wbs: e.target.value }))} />
          </Field>
          <Field label="Deliverable" className="sm:col-span-5">
            <input className="field" value={draft.name} required
                   onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          </Field>
          <Field label="Section" className="sm:col-span-2">
            <select className="field" value={draft.section_id}
                    onChange={(e) => setDraft((d) => ({ ...d, section_id: e.target.value }))}>
              <option value="">— unassigned —</option>
              {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Weight points" className="sm:col-span-1">
            <input type="number" min="0" step="0.1" className="field" value={draft.weight_points} required
                   onChange={(e) => setDraft((d) => ({ ...d, weight_points: e.target.value }))} />
          </Field>
          <Field label="Start (month)" className="sm:col-span-1">
            <input type="number" min="0" step="0.5" className="field" value={draft.start_month}
                   onChange={(e) => setDraft((d) => ({ ...d, start_month: e.target.value }))} />
          </Field>
          <Field label="Finish (month)" className="sm:col-span-1" >
            <input type="number" min="0" step="0.5" className="field" value={draft.finish_month}
                   onChange={(e) => setDraft((d) => ({ ...d, finish_month: e.target.value }))} />
          </Field>
          <Field label="Remarks" className="sm:col-span-6">
            <input className="field" value={draft.remarks}
                   onChange={(e) => setDraft((d) => ({ ...d, remarks: e.target.value }))} />
          </Field>
          <p className="text-xs text-muted sm:col-span-4">
            Finish at or before start makes the line a milestone: it steps from 0% to 100% on its date.
            The trade split starts even and can be set per line below.
          </p>
          <div className="flex items-end justify-end sm:col-span-2">
            <button type="submit" className="btn btn-primary">Add deliverable</button>
          </div>
          {error && <div className="sm:col-span-6"><ErrorNote>{error}</ErrorNote></div>}
        </form>
      )}

      {tasks.length === 0 ? (
        <Empty title="No deliverables yet">
          Add the measurable lines of your scope, each with a weight and a start/finish month.
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-xs text-muted">
                <th className="px-3 py-2 font-medium">WBS</th>
                <th className="px-3 py-2 font-medium">Deliverable</th>
                <th className="px-3 py-2 text-right font-medium">Points</th>
                <th className="px-3 py-2 text-right font-medium">Weight</th>
                <th className="px-3 py-2 text-right font-medium">Start</th>
                <th className="px-3 py-2 text-right font-medium">Finish</th>
                <th className="px-3 py-2 font-medium">Trade split</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {tasks.map((task) => (
                <TaskRow
                  key={task.id} task={task} trades={trades} sections={sections} canEdit={canEdit}
                  expanded={editingId === task.id}
                  onToggle={() => setEditingId(editingId === task.id ? null : task.id)}
                  onChange={onChange}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function TaskRow({ task, trades, sections, canEdit, expanded, onToggle, onChange }) {
  const dark = useThemeTick();
  const [alloc, setAlloc] = useState(() =>
    Object.fromEntries(trades.map((t) => [t.id, Math.round((task.allocations?.[t.id] ?? 0) * 100)])));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const total = Object.values(alloc).reduce((s, v) => s + (Number(v) || 0), 0);

  const saveField = async (patch) => {
    try { await api.updateTask(task.id, patch); onChange(); }
    catch (err) { setError(err.message); }
  };

  const saveAlloc = async () => {
    if (Math.abs(total - 100) > 0.5) { setError('The trade split must add up to 100%'); return; }
    setBusy(true); setError('');
    try {
      await api.updateTask(task.id, {
        allocations: Object.fromEntries(Object.entries(alloc).map(([k, v]) => [k, (Number(v) || 0) / 100])),
      });
      onChange();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <>
      <tr>
        <td className="px-3 py-2 align-top">
          <input className="field w-16 text-xs" defaultValue={task.wbs} disabled={!canEdit}
                 onBlur={(e) => e.target.value !== task.wbs && saveField({ wbs: e.target.value })} />
        </td>
        <td className="px-3 py-2 align-top" style={{ minWidth: 280 }}>
          <input className="field" defaultValue={task.name} disabled={!canEdit}
                 onBlur={(e) => e.target.value.trim() && e.target.value !== task.name && saveField({ name: e.target.value.trim() })} />
          {canEdit && (
            <select
              className="field mt-1 text-xs" defaultValue={task.section_id ?? ''}
              onChange={(e) => saveField({ section_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">— unassigned —</option>
              {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </td>
        <td className="px-3 py-2 align-top text-right">
          <input type="number" min="0" step="0.1" className="field w-20 text-right"
                 defaultValue={task.weight_points} disabled={!canEdit}
                 onBlur={(e) => Number(e.target.value) !== task.weight_points &&
                   saveField({ weight_points: Number(e.target.value) || 0 })} />
        </td>
        <td className="tabular px-3 py-2 align-top text-right text-ink2">{pct(task.weight_pct, 2)}</td>
        <td className="px-3 py-2 align-top text-right">
          <input type="number" min="0" step="0.5" className="field w-16 text-right"
                 defaultValue={task.start_month} disabled={!canEdit}
                 onBlur={(e) => Number(e.target.value) !== task.start_month &&
                   saveField({ start_month: Number(e.target.value) || 0 })} />
        </td>
        <td className="px-3 py-2 align-top text-right">
          <input type="number" min="0" step="0.5" className="field w-16 text-right"
                 defaultValue={task.finish_month} disabled={!canEdit}
                 onBlur={(e) => Number(e.target.value) !== task.finish_month &&
                   saveField({ finish_month: Number(e.target.value) || 0 })} />
        </td>
        <td className="px-3 py-2 align-top">
          <button type="button" onClick={onToggle} className="flex flex-wrap items-center gap-1">
            {trades.map((t) => {
              const share = task.allocations?.[t.id] ?? 0;
              if (!share) return null;
              return (
                <span key={t.id} className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs"
                      style={{ background: 'var(--plane)', color: 'var(--ink-2)' }}>
                  <span className="h-2 w-2 rounded-sm" aria-hidden="true"
                        style={{ background: tradeColor(t.color, dark) }} />
                  {Math.round(share * 100)}%
                </span>
              );
            })}
            <span className="text-xs text-accent">{expanded ? 'close' : 'edit'}</span>
          </button>
        </td>
        <td className="px-3 py-2 align-top text-right">
          {canEdit && (
            <button
              type="button" className="btn btn-danger px-2 py-0.5 text-xs"
              onClick={async () => {
                if (!window.confirm(`Delete "${task.name}"?`)) return;
                await api.deleteTask(task.id);
                onChange();
              }}
            >
              Delete
            </button>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} className="px-3 pb-3" style={{ background: 'var(--raised)' }}>
            <p className="mb-2 text-xs text-muted">
              How this deliverable&apos;s weight is shared between trades. Must total 100%.
            </p>
            <div className="flex flex-wrap items-end gap-2">
              {trades.map((t) => (
                <Field key={t.id} label={t.name} className="w-32">
                  <input
                    type="number" min="0" max="100" step="1" className="field text-right"
                    value={alloc[t.id] ?? 0} disabled={!canEdit}
                    onChange={(e) => setAlloc((a) => ({ ...a, [t.id]: e.target.value }))}
                  />
                </Field>
              ))}
              <div className="pb-1 text-xs" style={{ color: Math.abs(total - 100) > 0.5 ? 'var(--critical)' : 'var(--good-ink)' }}>
                Total {total.toFixed(0)}%
              </div>
              {canEdit && (
                <button type="button" className="btn btn-primary mb-0.5" disabled={busy} onClick={saveAlloc}>
                  {busy ? 'Saving…' : 'Save split'}
                </button>
              )}
            </div>
            {error && <div className="mt-2"><ErrorNote>{error}</ErrorNote></div>}
          </td>
        </tr>
      )}
    </>
  );
}

/* --------------------------------------------------------------------- team */

function TeamEditor({ projectId, members, canEdit, onChange }) {
  const [draft, setDraft] = useState({ email: '', role: 'member' });
  const [error, setError] = useState('');

  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await api.addMember(projectId, { email: draft.email.trim(), role: draft.role });
      setDraft({ email: '', role: 'member' });
      onChange();
    } catch (err) { setError(err.message); }
  };

  return (
    <Card title="Team" subtitle="Who can see and update this project" bodyClass="p-0">
      <ul className="divide-y divide-hairline">
        <li className="flex items-center justify-between px-4 py-2">
          <div>
            <p className="text-sm text-ink">{members.owner?.name}</p>
            <p className="text-xs text-muted">{members.owner?.email}</p>
          </div>
          <Badge state="good">Owner</Badge>
        </li>
        {members.members.map((m) => (
          <li key={m.id} className="flex items-center justify-between px-4 py-2">
            <div>
              <p className="text-sm text-ink">{m.name}</p>
              <p className="text-xs text-muted">{m.email}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge>{m.role}</Badge>
              {canEdit && (
                <button type="button" className="btn btn-danger px-2 py-0.5 text-xs"
                        onClick={async () => { await api.removeMember(projectId, m.id); onChange(); }}>
                  Remove
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {canEdit && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2 border-t border-hairline p-4">
          <Field label="Add by email" className="min-w-[220px] flex-1"
                 hint="They need an account on this platform first">
            <input type="email" className="field" value={draft.email} required
                   onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))} />
          </Field>
          <Field label="Access" className="w-36">
            <select className="field" value={draft.role}
                    onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}>
              <option value="viewer">Viewer</option>
              <option value="member">Member</option>
              <option value="manager">Manager</option>
            </select>
          </Field>
          <button type="submit" className="btn btn-primary">Add</button>
          {error && <div className="w-full"><ErrorNote>{error}</ErrorNote></div>}
        </form>
      )}
    </Card>
  );
}
