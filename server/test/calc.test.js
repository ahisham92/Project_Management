// Checks the calculation engine against the figures produced by the source
// control workbook at its 2026-09-01 data date.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeProject, plannedPct, elapsedMonths, buildSCurve, buildPeriodReport } from '../src/calc.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const seed = JSON.parse(fs.readFileSync(path.join(here, '..', 'seed', 'sibline-port.json'), 'utf8'));

const trades = seed.trades.map((t, i) => ({ ...t, id: i + 1 }));
const tradeIdByKey = Object.fromEntries(trades.map((t) => [t.key, t.id]));
const tasks = seed.tasks.map((t, i) => ({
  ...t,
  id: i + 1,
  allocations: Object.fromEntries(
    Object.entries(t.allocations).filter(([, pct]) => pct > 0).map(([k, pct]) => [tradeIdByKey[k], pct])
  ),
}));
// The workbook measures elapsed time as `data date - NTP + 1`; the seed carries
// that convention so the demo project reproduces its published figures.
const project = seed.project;
assert.equal(project.elapsed_day_offset, 1);
const DATA_DATE = '2026-09-01';
const close = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) < tol, `expected ${b}, got ${a}`);

test('elapsed months matches the workbook', () => {
  close(elapsedMonths(project.ntp_date, DATA_DATE, project.days_per_month, 1), 0.06570841889117043);
  // Default convention: no elapsed time on the NTP date itself.
  close(elapsedMonths(project.ntp_date, project.ntp_date, project.days_per_month, 0), 0);
  close(elapsedMonths(project.ntp_date, DATA_DATE, project.days_per_month, 0), 1 / project.days_per_month);
});

test('weight points total 100', () => {
  close(seed.tasks.reduce((s, t) => s + t.weight_points, 0), 100, 1e-6);
});

test('every trade allocation totals 100%', () => {
  for (const t of seed.tasks) {
    if (t.weight_points === 0) continue;
    close(Object.values(t.allocations).reduce((s, v) => s + v, 0), 1, 1e-6);
  }
});

test('planned % ramps linearly and milestones step', () => {
  close(plannedPct({ start_month: 0, finish_month: 4 }, 2), 0.5);
  close(plannedPct({ start_month: 1, finish_month: 3 }, 0), 0);      // before start
  close(plannedPct({ start_month: 1, finish_month: 3 }, 9), 1);      // after finish
  close(plannedPct({ start_month: 0, finish_month: 0 }, 0), 1);      // milestone on its date
  close(plannedPct({ start_month: 2, finish_month: 2 }, 1.9), 0);    // milestone not yet due
});

test('overall planned, earned and variance match the workbook', () => {
  const r = computeProject(project, tasks, trades, DATA_DATE);
  close(r.totals.planned_progress, 0.01762217659137577);
  close(r.totals.earned_progress, 0.005);
  close(r.totals.variance, -0.01262217659137577);
});

test('late, upcoming and behind counts match the workbook Task Schedule tab', () => {
  const r = computeProject(project, tasks, trades, DATA_DATE, { horizonDays: 2 });
  assert.equal(r.totals.late_count, 1);       // kick-off meeting, due at NTP, only 50% done
  assert.equal(r.totals.upcoming_count, 0);
  assert.equal(r.totals.behind_count, 8);
  close(r.totals.weight_at_risk, 0.01);
});

test('the late line is the kick-off meeting', () => {
  const r = computeProject(project, tasks, trades, DATA_DATE);
  const late = r.tasks.filter((t) => t.is_late);
  assert.equal(late.length, 1);
  assert.equal(late[0].wbs, '1.6');
  assert.equal(late[0].days_late, 1);
  assert.equal(late[0].due_date, '2026-08-31');
});

test('trade scope weights and contributions match the Trade Budget Control tab', () => {
  const r = computeProject(project, tasks, trades, DATA_DATE);
  const by = Object.fromEntries(r.trades.map((t) => [t.key, t]));

  close(by.marine.scope_weight_pct, 0.35145000000000015);
  close(by.geotechnical.scope_weight_pct, 0.21200000000000005);
  close(by.marine_structures.scope_weight_pct, 0.37565000000000004);
  close(by.utilities.scope_weight_pct, 0.06090000000000001);

  close(by.marine.planned_contribution, 0.005441067761806982);
  close(by.geotechnical.planned_contribution, 0.005404928131416837);
  close(by.marine_structures.planned_contribution, 0.005401642710472279);
  close(by.utilities.planned_contribution, 0.0013745379876796715);

  close(by.marine.earned_contribution, 0.0015);
  close(by.geotechnical.earned_contribution, 0.0015);
  close(by.marine_structures.earned_contribution, 0.0015);
  close(by.utilities.earned_contribution, 0.0005);

  close(by.marine.earned_pct_of_trade, 0.00426803243704652);
  close(by.geotechnical.earned_pct_of_trade, 0.007075471698113206);
  close(by.utilities.schedule_variance_pct, -0.014360229682753222);

  // Scope weights must add back up to the whole project.
  close(r.trades.reduce((s, t) => s + t.scope_weight_pct, 0), 1, 1e-9);
  close(r.trades.reduce((s, t) => s + t.earned_contribution, 0), r.totals.earned_progress, 1e-9);
  close(r.trades.reduce((s, t) => s + t.planned_contribution, 0), r.totals.planned_progress, 1e-9);
});

test('earned hours follow the workbook man-month figures', () => {
  const r = computeProject(project, tasks, trades, DATA_DATE);
  const by = Object.fromEntries(r.trades.map((t) => [t.key, t]));
  const MM = seed.project.hours_per_month;
  // Workbook: Marine earned 0.02560819462227912 MM of a 6 MM budget.
  close(by.marine.earned_hours / MM, 0.02560819462227912, 1e-9);
  close(by.geotechnical.earned_hours / MM, 0.017688679245283015, 1e-9);
  close(by.marine_structures.earned_hours / MM, 0.023958471981898037, 1e-9);
  close(by.utilities.earned_hours / MM, 0.004105090311986863, 1e-9);
  close(r.budget.earned_hours / MM, 0.07136043616144702, 1e-9);
  close(r.budget.budget_hours, 15 * MM, 1e-9);
});

test('spent hours drive CPI, EAC and VAC', () => {
  const spent = { [tradeIdByKey.marine]: 200 };
  const r = computeProject(project, tasks, trades, DATA_DATE, { spentByTrade: spent });
  const marine = r.trades.find((t) => t.key === 'marine');
  assert.equal(marine.spent_hours, 200);
  close(marine.cpi, marine.earned_hours / 200);
  close(marine.eac_hours, marine.budget_hours / marine.cpi);
  close(marine.vac_hours, marine.budget_hours - marine.eac_hours);
  assert.ok(marine.hours_over_under > 0, 'burning hours ahead of earned progress');
  assert.equal(marine.budget_status, 'Over-burning');
  const idle = r.trades.find((t) => t.key === 'utilities');
  assert.equal(idle.cpi, null);
  assert.equal(idle.budget_status, 'No spend booked');
});

test('a fully complete project earns 100%', () => {
  const done = tasks.map((t) => ({ ...t, actual_pct: 1 }));
  const r = computeProject(project, done, trades, DATA_DATE);
  close(r.totals.earned_progress, 1, 1e-9);
  assert.equal(r.totals.late_count, 0);
  assert.equal(r.totals.behind_count, 0);
});

test('S-curve planned rises from 0 to 100% and earned stops at the data date', () => {
  const history = tasks.filter((t) => t.actual_pct > 0)
    .map((t) => ({ task_id: t.id, actual_pct: t.actual_pct, data_date: '2026-08-31' }));
  const points = buildSCurve(project, tasks, history, DATA_DATE, 20);
  // Month 0 already carries the kick-off milestone, which falls due on the NTP date.
  close(points[0].planned, 0.01, 1e-9);
  close(points.at(-1).planned, 1, 1e-9);
  for (let i = 1; i < points.length; i++) {
    assert.ok(points[i].planned >= points[i - 1].planned - 1e-12, 'planned curve must not go backwards');
  }
  assert.equal(points.at(-1).earned, null, 'no earned value beyond the data date');
  assert.ok(points.filter((p) => p.earned !== null).length >= 1);
});

test('the elapsed-day convention changes planned progress but not earned', () => {
  const strict = computeProject({ ...project, elapsed_day_offset: 0 }, tasks, trades, DATA_DATE);
  const workbook = computeProject(project, tasks, trades, DATA_DATE);
  close(strict.totals.earned_progress, workbook.totals.earned_progress);
  assert.ok(strict.totals.planned_progress < workbook.totals.planned_progress);
  close(strict.totals.planned_progress, 0.01381108829568788);
});

test('period report attributes progress to the right period and trades', () => {
  const kickoff = tasks.find((t) => t.wbs === '1.6');
  const history = [
    { task_id: kickoff.id, actual_pct: 0.25, data_date: '2026-08-31' },
    { task_id: kickoff.id, actual_pct: 0.5, data_date: '2026-09-01' },
  ];
  const period = buildPeriodReport(project, tasks, trades, history, '2026-09-01', '2026-09-01');
  close(period.earned_at_start, 0.01 * 0.25);
  close(period.earned_at_end, 0.01 * 0.5);
  close(period.earned_in_period, 0.01 * 0.25);
  const marine = period.trade_earned_in_period.find((t) => t.name === 'Marine');
  close(marine.earned_in_period, 0.01 * 0.25 * 0.3);
  assert.equal(period.tasks.find((t) => t.wbs === '1.6').period_status, 'Advanced in period');
});
