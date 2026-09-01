import db from './db.js';
import { computeProject, buildSCurve, buildPeriodReport, toISODate } from './calc.js';

export const today = () => new Date().toISOString().slice(0, 10);

/** Tasks for a project, each with its trade allocations keyed by trade id. */
export function loadTasks(projectId) {
  const tasks = db.prepare(`
    SELECT t.*, s.name AS section_name, s.code AS section_code, s.sort_order AS section_order
    FROM tasks t
    LEFT JOIN sections s ON s.id = t.section_id
    WHERE t.project_id = ?
    ORDER BY COALESCE(s.sort_order, 999), t.sort_order, t.id
  `).all(projectId);

  const allocations = db.prepare(`
    SELECT a.task_id, a.trade_id, a.pct
    FROM task_allocations a
    JOIN tasks t ON t.id = a.task_id
    WHERE t.project_id = ?
  `).all(projectId);

  const byTask = new Map();
  for (const a of allocations) {
    if (!byTask.has(a.task_id)) byTask.set(a.task_id, {});
    byTask.get(a.task_id)[a.trade_id] = a.pct;
  }
  for (const t of tasks) t.allocations = byTask.get(t.id) || {};
  return tasks;
}

export const loadTrades = (projectId) =>
  db.prepare('SELECT * FROM trades WHERE project_id = ? ORDER BY sort_order, id').all(projectId);

export const loadSections = (projectId) =>
  db.prepare('SELECT * FROM sections WHERE project_id = ? ORDER BY sort_order, id').all(projectId);

/** Hours booked per trade, up to and including the data date. */
export function spentHoursByTrade(projectId, dataDate) {
  const rows = db.prepare(`
    SELECT trade_id, SUM(hours) AS hours
    FROM time_entries
    WHERE project_id = ? AND entry_date <= ?
    GROUP BY trade_id
  `).all(projectId, dataDate);
  const out = {};
  for (const r of rows) if (r.trade_id != null) out[r.trade_id] = r.hours;
  return out;
}

export const unallocatedHours = (projectId, dataDate) =>
  db.prepare(`
    SELECT COALESCE(SUM(hours), 0) AS hours
    FROM time_entries
    WHERE project_id = ? AND entry_date <= ? AND trade_id IS NULL
  `).get(projectId, dataDate).hours;

export const loadProgressHistory = (projectId) =>
  db.prepare('SELECT task_id, actual_pct, data_date FROM progress_updates WHERE project_id = ? ORDER BY data_date, id')
    .all(projectId);

/** Full computed view of a project at a data date. */
export function projectSnapshot(project, { dataDate = today(), horizonDays = 30 } = {}) {
  const iso = toISODate(dataDate);
  const tasks = loadTasks(project.id);
  const trades = loadTrades(project.id);
  const snapshot = computeProject(project, tasks, trades, iso, {
    horizonDays,
    spentByTrade: spentHoursByTrade(project.id, iso),
  });
  snapshot.budget.unallocated_hours = unallocatedHours(project.id, iso);
  snapshot.budget.spent_hours += snapshot.budget.unallocated_hours;
  snapshot.budget.remaining_hours = snapshot.budget.budget_hours - snapshot.budget.spent_hours;
  snapshot.budget.hours_used_pct = snapshot.budget.budget_hours > 0
    ? snapshot.budget.spent_hours / snapshot.budget.budget_hours
    : 0;
  return snapshot;
}

export function projectSCurve(project, { dataDate = today(), steps = 40 } = {}) {
  return buildSCurve(project, loadTasks(project.id), loadProgressHistory(project.id), toISODate(dataDate), steps);
}

export function projectPeriod(project, from, to) {
  return buildPeriodReport(project, loadTasks(project.id), loadTrades(project.id),
    loadProgressHistory(project.id), from, to);
}

/** Compact figures used by the portfolio list. */
export function portfolioCard(project, dataDate = today()) {
  const snap = projectSnapshot(project, { dataDate });
  return {
    id: project.id,
    code: project.code,
    name: project.name,
    client: project.client,
    status: project.status,
    ntp_date: project.ntp_date,
    duration_months: project.duration_months,
    end_date: snap.tasks.reduce((max, t) => (t.due_date > max ? t.due_date : max), snap.ntp_date),
    elapsed_months: snap.elapsed_months,
    time_elapsed_pct: snap.time_elapsed_pct,
    planned_progress: snap.totals.planned_progress,
    earned_progress: snap.totals.earned_progress,
    variance: snap.totals.variance,
    spi: snap.totals.spi,
    task_count: snap.totals.task_count,
    complete_count: snap.totals.complete_count,
    late_count: snap.totals.late_count,
    upcoming_count: snap.totals.upcoming_count,
    behind_count: snap.totals.behind_count,
    budget_hours: snap.budget.budget_hours,
    spent_hours: snap.budget.spent_hours,
    hours_used_pct: snap.budget.hours_used_pct,
    cpi: snap.budget.cpi,
    budget_status: snap.budget.budget_status,
  };
}

/** Rewrites a task's trade split, validating that it totals 100%. */
export function setAllocations(taskId, projectId, allocations) {
  const trades = loadTrades(projectId);
  const valid = new Set(trades.map((t) => t.id));
  const entries = Object.entries(allocations || {})
    .map(([tradeId, pct]) => [Number(tradeId), Number(pct) || 0])
    .filter(([tradeId]) => valid.has(tradeId));

  const total = entries.reduce((s, [, pct]) => s + pct, 0);
  if (entries.length && Math.abs(total - 1) > 0.005) {
    const err = new Error(`Trade allocation must total 100% (currently ${(total * 100).toFixed(1)}%)`);
    err.status = 400;
    throw err;
  }

  const tx = db.transaction(() => {
    db.prepare('DELETE FROM task_allocations WHERE task_id = ?').run(taskId);
    const insert = db.prepare('INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)');
    for (const [tradeId, pct] of entries) if (pct > 0) insert.run(taskId, tradeId, pct);
  });
  tx();
}
