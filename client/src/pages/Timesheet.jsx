import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api.js';
import { useAsync } from '../hooks.js';
import { hours, shortDate, todayISO, num } from '../format.js';
import { Card, Spinner, ErrorNote, Field, Empty } from '../components/ui.jsx';
import { useThemeTick } from '../components/charts.jsx';
import { tradeColor } from '../palette.js';

const blank = () => ({ entry_date: todayISO(), trade_id: '', task_id: '', hours: '', description: '' });

export default function Timesheet() {
  const { id } = useParams();
  const [form, setForm] = useState(blank);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const dark = useThemeTick();

  const { data, error, loading, reload } = useAsync(
    async () => {
      const [detail, list] = await Promise.all([
        api.project(id),
        api.timeEntries(id, { limit: 500 }),
      ]);
      return { detail, entries: list.entries };
    },
    [id]
  );

  const totals = useMemo(() => {
    if (!data) return { total: 0, byTrade: new Map() };
    const byTrade = new Map();
    let total = 0;
    for (const e of data.entries) {
      total += e.hours;
      const key = e.trade_id ?? 'none';
      byTrade.set(key, (byTrade.get(key) || 0) + e.hours);
    }
    return { total, byTrade };
  }, [data]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setFormError('');
    const value = Number(form.hours);
    if (!value || value <= 0) { setFormError('Enter the number of hours worked'); return; }
    setSaving(true);
    try {
      await api.addTimeEntry(id, {
        entry_date: form.entry_date,
        trade_id: form.trade_id ? Number(form.trade_id) : null,
        task_id: form.task_id ? Number(form.task_id) : null,
        hours: value,
        description: form.description,
      });
      setForm((f) => ({ ...blank(), entry_date: f.entry_date, trade_id: f.trade_id }));
      await reload();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entryId) => {
    try {
      await api.deleteTimeEntry(id, entryId);
      await reload();
    } catch (err) {
      setFormError(err.message);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorNote onRetry={reload}>{error}</ErrorNote>;

  const { detail, entries } = data;
  const trades = detail.snapshot.trades;
  const tasks = detail.snapshot.tasks;
  const readOnly = detail.role === 'viewer';

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold text-ink">Timesheet</h1>
        <p className="mt-0.5 text-sm text-muted">
          {hours(totals.total)} booked across {entries.length} entr{entries.length === 1 ? 'y' : 'ies'} ·
          {' '}feeds straight into budget control
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        {!readOnly && (
          <Card title="Book hours" className="lg:col-span-1">
            <form onSubmit={submit} className="space-y-3">
              <Field label="Date">
                <input type="date" className="field" value={form.entry_date} onChange={set('entry_date')} required />
              </Field>
              <Field label="Trade" hint="Hours booked without a trade count to the project total only">
                <select className="field" value={form.trade_id} onChange={set('trade_id')}>
                  <option value="">— none —</option>
                  {trades.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </Field>
              <Field label="Deliverable (optional)">
                <select className="field" value={form.task_id} onChange={set('task_id')}>
                  <option value="">— none —</option>
                  {tasks.map((t) => (
                    <option key={t.id} value={t.id}>{t.wbs} · {t.name.slice(0, 60)}</option>
                  ))}
                </select>
              </Field>
              <Field label="Hours">
                <input type="number" min="0.25" step="0.25" className="field" value={form.hours}
                       onChange={set('hours')} placeholder="7.5" required />
              </Field>
              <Field label="Note (optional)">
                <input className="field" value={form.description} onChange={set('description')}
                       placeholder="What the time went on" />
              </Field>
              {formError && <ErrorNote>{formError}</ErrorNote>}
              <button type="submit" className="btn btn-primary w-full" disabled={saving}>
                {saving ? 'Saving…' : 'Book hours'}
              </button>
            </form>
          </Card>
        )}

        <div className={`space-y-4 ${readOnly ? 'lg:col-span-3' : 'lg:col-span-2'}`}>
          <Card title="Booked by trade" bodyClass="p-0">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-hairline">
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td className="px-4 py-2">
                      <span className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-sm" aria-hidden="true"
                              style={{ background: tradeColor(t.color, dark) }} />
                        <span className="text-ink">{t.name}</span>
                      </span>
                    </td>
                    <td className="tabular px-4 py-2 text-right text-ink2">{hours(totals.byTrade.get(t.id) || 0)}</td>
                    <td className="tabular px-4 py-2 text-right text-xs text-muted">of {hours(t.budget_hours)}</td>
                  </tr>
                ))}
                {totals.byTrade.get('none') > 0 && (
                  <tr>
                    <td className="px-4 py-2 text-muted">No trade</td>
                    <td className="tabular px-4 py-2 text-right text-ink2">{hours(totals.byTrade.get('none'))}</td>
                    <td />
                  </tr>
                )}
              </tbody>
              <tfoot>
                <tr className="border-t border-hairline font-medium">
                  <td className="px-4 py-2 text-ink">Total</td>
                  <td className="tabular px-4 py-2 text-right text-ink">{hours(totals.total)}</td>
                  <td className="tabular px-4 py-2 text-right text-xs text-muted">
                    {num(totals.total / (detail.snapshot.budget.hours_per_month || 176), 2)} man-months
                  </td>
                </tr>
              </tfoot>
            </table>
          </Card>

          <Card title="Recent entries" bodyClass="p-0">
            {entries.length === 0 ? (
              <Empty title="No hours booked yet">
                Book time against a trade to see it in budget control.
              </Empty>
            ) : (
              <div className="max-h-[520px] overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0" style={{ background: 'var(--surface)' }}>
                    <tr className="border-b border-hairline text-left text-xs text-muted">
                      <th className="px-4 py-2 font-medium">Date</th>
                      <th className="px-4 py-2 font-medium">Trade</th>
                      <th className="px-4 py-2 font-medium">Deliverable</th>
                      <th className="px-4 py-2 font-medium">Who</th>
                      <th className="px-4 py-2 text-right font-medium">Hours</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {entries.map((e) => (
                      <tr key={e.id}>
                        <td className="whitespace-nowrap px-4 py-2 text-xs text-ink2">{shortDate(e.entry_date)}</td>
                        <td className="px-4 py-2 text-xs">
                          {e.trade_name ? (
                            <span className="flex items-center gap-1.5">
                              <span className="h-2 w-2 rounded-sm" aria-hidden="true"
                                    style={{ background: tradeColor(e.trade_color, dark) }} />
                              <span className="text-ink2">{e.trade_name}</span>
                            </span>
                          ) : <span className="text-muted">—</span>}
                        </td>
                        <td className="px-4 py-2 text-xs text-ink2">
                          {e.task_wbs ? <span title={e.task_name}>{e.task_wbs}</span> : <span className="text-muted">—</span>}
                          {e.description && <span className="block text-muted">{e.description}</span>}
                        </td>
                        <td className="px-4 py-2 text-xs text-muted">{e.user_name || '—'}</td>
                        <td className="tabular px-4 py-2 text-right font-medium text-ink">{num(e.hours, 2)}</td>
                        <td className="px-4 py-2 text-right">
                          {!readOnly && (
                            <button type="button" className="btn btn-danger px-2 py-0.5 text-xs"
                                    onClick={() => remove(e.id)}>
                              Delete
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
