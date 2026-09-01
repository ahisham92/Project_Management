import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../api.js';
import { Card, Field, ErrorNote } from '../components/ui.jsx';
import { SERIES } from '../palette.js';

const DEFAULT_TRADES = ['Design', 'Engineering', 'Delivery'];

export default function NewProject() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    code: '', name: '', client: '', description: '',
    ntp_date: new Date().toISOString().slice(0, 10),
    duration_months: 12, days_per_month: 30.4375, hours_per_month: 176,
    elapsed_day_offset: 0,
  });
  const [trades, setTrades] = useState(DEFAULT_TRADES.map((name, i) => ({ name, budget_hours: '' , color: SERIES[i].light })));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const { project } = await api.createProject({
        ...form,
        duration_months: Number(form.duration_months),
        days_per_month: Number(form.days_per_month),
        hours_per_month: Number(form.hours_per_month),
        elapsed_day_offset: Number(form.elapsed_day_offset),
      });
      for (const [i, t] of trades.entries()) {
        if (!t.name.trim()) continue;
        await api.createTrade(project.id, {
          name: t.name.trim(),
          budget_hours: Number(t.budget_hours) || 0,
          color: t.color,
          sort_order: i + 1,
        });
      }
      navigate(`/projects/${project.id}/settings`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const setTrade = (i, key, value) =>
    setTrades((list) => list.map((t, idx) => (idx === i ? { ...t, [key]: value } : t)));

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <Link to="/" className="text-xs text-muted hover:text-ink">← Portfolio</Link>
        <h1 className="mt-1 text-lg font-semibold text-ink">New project</h1>
        <p className="mt-0.5 text-sm text-muted">
          Set the contract dates and the trades that carry the budget. Deliverables come next.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-4">
        <Card title="Project">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Project code" hint="Short unique reference, e.g. SIBLINE-PORT">
              <input className="field" value={form.code} onChange={set('code')} required />
            </Field>
            <Field label="Client">
              <input className="field" value={form.client} onChange={set('client')} />
            </Field>
            <Field label="Project name" className="sm:col-span-2">
              <input className="field" value={form.name} onChange={set('name')} required />
            </Field>
            <Field label="Description" className="sm:col-span-2">
              <textarea className="field" rows={2} value={form.description} onChange={set('description')} />
            </Field>
          </div>
        </Card>

        <Card title="Programme" subtitle="Every planned date is measured from the notice to proceed">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Notice to proceed (NTP)">
              <input type="date" className="field" value={form.ntp_date} onChange={set('ntp_date')} required />
            </Field>
            <Field label="Duration (months)">
              <input type="number" min="0.5" step="0.5" className="field"
                     value={form.duration_months} onChange={set('duration_months')} required />
            </Field>
            <Field label="Days per month" hint="Programme basis for turning elapsed months into dates">
              <input type="number" min="1" step="0.0001" className="field"
                     value={form.days_per_month} onChange={set('days_per_month')} />
            </Field>
            <Field label="Hours per man-month" hint="Used to show hour budgets as man-months">
              <input type="number" min="1" step="1" className="field"
                     value={form.hours_per_month} onChange={set('hours_per_month')} />
            </Field>
            <Field
              label="Elapsed time convention"
              className="sm:col-span-2"
              hint="Affects planned progress only. Use the second option to match a spreadsheet that measures elapsed time as data date − NTP + 1."
            >
              <select className="field" value={form.elapsed_day_offset} onChange={set('elapsed_day_offset')}>
                <option value={0}>No elapsed time on the NTP date (month 0 = NTP)</option>
                <option value={1}>Count the NTP day as one day worked</option>
              </select>
            </Field>
          </div>
        </Card>

        <Card title="Trades" subtitle="Disciplines that carry the hour budget; each deliverable is split between them">
          <div className="space-y-2">
            {trades.map((t, i) => (
              <div key={i} className="flex items-end gap-2">
                <Field label={i === 0 ? 'Trade' : ''} className="flex-1">
                  <input className="field" value={t.name} onChange={(e) => setTrade(i, 'name', e.target.value)}
                         placeholder="Trade name" />
                </Field>
                <Field label={i === 0 ? 'Budget (hours)' : ''} className="w-40">
                  <input type="number" min="0" step="1" className="field" value={t.budget_hours}
                         onChange={(e) => setTrade(i, 'budget_hours', e.target.value)} placeholder="0" />
                </Field>
                <button
                  type="button"
                  className="btn btn-ghost mb-0 px-2 py-2"
                  onClick={() => setTrades((l) => l.filter((_, idx) => idx !== i))}
                  aria-label={`Remove ${t.name || 'trade'}`}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setTrades((l) => [...l, { name: '', budget_hours: '', color: SERIES[l.length % SERIES.length].light }])}
            >
              Add trade
            </button>
          </div>
        </Card>

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex justify-end gap-2">
          <Link to="/" className="btn btn-ghost">Cancel</Link>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create project'}
          </button>
        </div>
      </form>
    </div>
  );
}
