import { Router } from 'express';
import { z } from 'zod';
import db from '../db.js';
import { requireAuth, requireProject, visibleProjectIds } from '../auth.js';
import {
  today, portfolioCard, projectSnapshot, projectSCurve, projectPeriod,
  loadSections, loadTrades, setAllocations,
} from '../service.js';

const router = Router();
router.use(requireAuth);

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use a YYYY-MM-DD date');

const projectInput = z.object({
  code: z.string().min(1).max(40),
  name: z.string().min(1).max(200),
  client: z.string().max(200).optional().default(''),
  description: z.string().max(4000).optional().default(''),
  ntp_date: isoDate,
  duration_months: z.number().positive().max(600),
  days_per_month: z.number().positive().max(40).optional().default(30.4375),
  hours_per_month: z.number().positive().max(400).optional().default(176),
  elapsed_day_offset: z.number().min(0).max(1).optional().default(0),
  currency: z.string().max(10).optional().default('USD'),
  status: z.enum(['active', 'on_hold', 'complete', 'archived']).optional().default('active'),
});

const q = (req) => ({
  dataDate: req.query.data_date || today(),
  horizonDays: Math.min(365, Math.max(1, Number(req.query.horizon) || 30)),
});

/* ---------------------------------------------------------------- portfolio */

router.get('/', (req, res) => {
  const ids = visibleProjectIds(req.user);
  if (!ids.length) return res.json({ projects: [], totals: emptyTotals() });

  const rows = db.prepare(
    `SELECT * FROM projects WHERE id IN (${ids.map(() => '?').join(',')}) ORDER BY status, name`
  ).all(...ids);

  const dataDate = req.query.data_date || today();
  const projects = rows.map((p) => portfolioCard(p, dataDate));

  // Portfolio roll-up: progress weighted by each project's hour budget, so a
  // large project moves the portfolio number more than a small one.
  const budget = projects.reduce((s, p) => s + p.budget_hours, 0);
  const weightOf = (p) => (budget > 0 ? p.budget_hours / budget : 1 / (projects.length || 1));
  const active = projects.filter((p) => p.status === 'active');

  res.json({
    projects,
    totals: {
      project_count: projects.length,
      active_count: active.length,
      planned_progress: projects.reduce((s, p) => s + p.planned_progress * weightOf(p), 0),
      earned_progress: projects.reduce((s, p) => s + p.earned_progress * weightOf(p), 0),
      variance: projects.reduce((s, p) => s + p.variance * weightOf(p), 0),
      late_count: projects.reduce((s, p) => s + p.late_count, 0),
      upcoming_count: projects.reduce((s, p) => s + p.upcoming_count, 0),
      behind_count: projects.reduce((s, p) => s + p.behind_count, 0),
      budget_hours: budget,
      spent_hours: projects.reduce((s, p) => s + p.spent_hours, 0),
      hours_used_pct: budget > 0 ? projects.reduce((s, p) => s + p.spent_hours, 0) / budget : 0,
    },
  });
});

const emptyTotals = () => ({
  project_count: 0, active_count: 0, planned_progress: 0, earned_progress: 0, variance: 0,
  late_count: 0, upcoming_count: 0, behind_count: 0, budget_hours: 0, spent_hours: 0, hours_used_pct: 0,
});

router.post('/', (req, res) => {
  const parsed = projectInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  if (db.prepare('SELECT 1 FROM projects WHERE code = ?').get(parsed.data.code)) {
    return res.status(409).json({ error: 'A project with that code already exists' });
  }
  const d = parsed.data;
  const info = db.prepare(`
    INSERT INTO projects (code, name, client, description, ntp_date, duration_months,
                          days_per_month, hours_per_month, currency, status, owner_id)
    VALUES (@code, @name, @client, @description, @ntp_date, @duration_months,
            @days_per_month, @hours_per_month, @currency, @status, @owner_id)
  `).run({ ...d, owner_id: req.user.id });
  res.status(201).json({ project: db.prepare('SELECT * FROM projects WHERE id = ?').get(info.lastInsertRowid) });
});

/* ------------------------------------------------------------ single project */

router.get('/:projectId', requireProject('viewer'), (req, res) => {
  const { dataDate, horizonDays } = q(req);
  res.json({
    project: req.project,
    role: req.projectRole,
    sections: loadSections(req.project.id),
    snapshot: projectSnapshot(req.project, { dataDate, horizonDays }),
  });
});

router.patch('/:projectId', requireProject('manager'), (req, res) => {
  const parsed = projectInput.partial().safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const fields = Object.keys(parsed.data);
  if (!fields.length) return res.json({ project: req.project });
  if (parsed.data.code && parsed.data.code !== req.project.code &&
      db.prepare('SELECT 1 FROM projects WHERE code = ?').get(parsed.data.code)) {
    return res.status(409).json({ error: 'A project with that code already exists' });
  }
  db.prepare(
    `UPDATE projects SET ${fields.map((f) => `${f} = @${f}`).join(', ')}, updated_at = datetime('now') WHERE id = @id`
  ).run({ ...parsed.data, id: req.project.id });
  res.json({ project: db.prepare('SELECT * FROM projects WHERE id = ?').get(req.project.id) });
});

router.delete('/:projectId', requireProject('owner'), (req, res) => {
  db.prepare('DELETE FROM projects WHERE id = ?').run(req.project.id);
  res.json({ ok: true });
});

/* ---------------------------------------------------------------- reporting */

router.get('/:projectId/s-curve', requireProject('viewer'), (req, res) => {
  const steps = Math.min(120, Math.max(4, Number(req.query.steps) || 40));
  res.json({ points: projectSCurve(req.project, { dataDate: q(req).dataDate, steps }) });
});

router.get('/:projectId/schedule', requireProject('viewer'), (req, res) => {
  const { dataDate, horizonDays } = q(req);
  const snap = projectSnapshot(req.project, { dataDate, horizonDays });
  res.json({
    data_date: snap.data_date,
    horizon_days: horizonDays,
    totals: snap.totals,
    late: snap.tasks.filter((t) => t.is_late).sort((a, b) => b.days_late - a.days_late),
    upcoming: snap.tasks.filter((t) => t.is_upcoming).sort((a, b) => a.days_to_due - b.days_to_due),
    behind: snap.tasks.filter((t) => t.is_behind && !t.is_late).sort((a, b) => a.variance - b.variance),
  });
});

router.get('/:projectId/budget', requireProject('viewer'), (req, res) => {
  const snap = projectSnapshot(req.project, q(req));
  const byTrade = db.prepare(`
    SELECT trade_id, entry_date, SUM(hours) AS hours
    FROM time_entries WHERE project_id = ? AND entry_date <= ?
    GROUP BY trade_id, entry_date ORDER BY entry_date
  `).all(req.project.id, snap.data_date);
  res.json({ data_date: snap.data_date, budget: snap.budget, trades: snap.trades, spend_history: byTrade });
});

router.get('/:projectId/period', requireProject('viewer'), (req, res) => {
  const from = req.query.from || req.project.ntp_date;
  const to = req.query.to || today();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    return res.status(400).json({ error: 'from and to must be YYYY-MM-DD dates' });
  }
  res.json({ period: projectPeriod(req.project, from, to), trades: loadTrades(req.project.id) });
});

/* ----------------------------------------------------------------- sections */

const sectionInput = z.object({
  code: z.string().max(20).optional().default(''),
  name: z.string().min(1).max(200),
  sort_order: z.number().int().optional(),
});

router.post('/:projectId/sections', requireProject('manager'), (req, res) => {
  const parsed = sectionInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const order = parsed.data.sort_order ?? (loadSections(req.project.id).length + 1);
  const info = db.prepare('INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)')
    .run(req.project.id, parsed.data.code, parsed.data.name, order);
  res.status(201).json({ section: db.prepare('SELECT * FROM sections WHERE id = ?').get(info.lastInsertRowid) });
});

router.patch('/:projectId/sections/:sectionId', requireProject('manager'), (req, res) => {
  const parsed = sectionInput.partial().safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const section = db.prepare('SELECT * FROM sections WHERE id = ? AND project_id = ?')
    .get(req.params.sectionId, req.project.id);
  if (!section) return res.status(404).json({ error: 'Section not found' });
  const fields = Object.keys(parsed.data);
  if (fields.length) {
    db.prepare(`UPDATE sections SET ${fields.map((f) => `${f} = @${f}`).join(', ')} WHERE id = @id`)
      .run({ ...parsed.data, id: section.id });
  }
  res.json({ section: db.prepare('SELECT * FROM sections WHERE id = ?').get(section.id) });
});

router.delete('/:projectId/sections/:sectionId', requireProject('manager'), (req, res) => {
  db.prepare('DELETE FROM sections WHERE id = ? AND project_id = ?').run(req.params.sectionId, req.project.id);
  res.json({ ok: true });
});

/* ------------------------------------------------------------------- trades */

const tradeInput = z.object({
  key: z.string().min(1).max(40).optional(),
  name: z.string().min(1).max(120),
  budget_hours: z.number().min(0).max(10_000_000).optional().default(0),
  color: z.string().max(20).optional().default('#2563eb'),
  sort_order: z.number().int().optional(),
});

router.get('/:projectId/trades', requireProject('viewer'), (req, res) => {
  res.json({ trades: loadTrades(req.project.id) });
});

router.post('/:projectId/trades', requireProject('manager'), (req, res) => {
  const parsed = tradeInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const d = parsed.data;
  const key = (d.key || d.name).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  if (db.prepare('SELECT 1 FROM trades WHERE project_id = ? AND key = ?').get(req.project.id, key)) {
    return res.status(409).json({ error: 'A trade with that name already exists on this project' });
  }
  const order = d.sort_order ?? (loadTrades(req.project.id).length + 1);
  const info = db.prepare(
    'INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)'
  ).run(req.project.id, key, d.name, d.budget_hours, d.color, order);
  res.status(201).json({ trade: db.prepare('SELECT * FROM trades WHERE id = ?').get(info.lastInsertRowid) });
});

router.patch('/:projectId/trades/:tradeId', requireProject('manager'), (req, res) => {
  const parsed = tradeInput.partial().safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const trade = db.prepare('SELECT * FROM trades WHERE id = ? AND project_id = ?')
    .get(req.params.tradeId, req.project.id);
  if (!trade) return res.status(404).json({ error: 'Trade not found' });
  const fields = Object.keys(parsed.data);
  if (fields.length) {
    db.prepare(`UPDATE trades SET ${fields.map((f) => `${f} = @${f}`).join(', ')} WHERE id = @id`)
      .run({ ...parsed.data, id: trade.id });
  }
  res.json({ trade: db.prepare('SELECT * FROM trades WHERE id = ?').get(trade.id) });
});

router.delete('/:projectId/trades/:tradeId', requireProject('manager'), (req, res) => {
  db.prepare('DELETE FROM trades WHERE id = ? AND project_id = ?').run(req.params.tradeId, req.project.id);
  res.json({ ok: true });
});

/* -------------------------------------------------------------------- tasks */

const taskInput = z.object({
  section_id: z.number().int().nullable().optional(),
  wbs: z.string().max(20).optional().default(''),
  name: z.string().min(1).max(500),
  weight_points: z.number().min(0).max(100000).optional().default(0),
  start_month: z.number().min(0).max(600).optional().default(0),
  finish_month: z.number().min(0).max(600).optional().default(0),
  actual_pct: z.number().min(0).max(1).optional().default(0),
  remarks: z.string().max(2000).optional().default(''),
  sort_order: z.number().int().optional(),
  allocations: z.record(z.coerce.number()).optional(),
});

router.post('/:projectId/tasks', requireProject('member'), (req, res, next) => {
  const parsed = taskInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const d = parsed.data;
  if (d.section_id && !db.prepare('SELECT 1 FROM sections WHERE id = ? AND project_id = ?')
    .get(d.section_id, req.project.id)) {
    return res.status(400).json({ error: 'Section does not belong to this project' });
  }
  const order = d.sort_order ??
    (db.prepare('SELECT COUNT(*) AS n FROM tasks WHERE project_id = ?').get(req.project.id).n + 1);
  try {
    const info = db.prepare(`
      INSERT INTO tasks (project_id, section_id, wbs, name, weight_points, start_month,
                         finish_month, actual_pct, remarks, sort_order)
      VALUES (@project_id, @section_id, @wbs, @name, @weight_points, @start_month,
              @finish_month, @actual_pct, @remarks, @sort_order)
    `).run({
      project_id: req.project.id,
      section_id: d.section_id ?? null,
      wbs: d.wbs, name: d.name, weight_points: d.weight_points,
      start_month: d.start_month, finish_month: d.finish_month,
      actual_pct: d.actual_pct, remarks: d.remarks, sort_order: order,
    });
    if (d.allocations) setAllocations(info.lastInsertRowid, req.project.id, d.allocations);
    if (d.actual_pct > 0) {
      db.prepare(`
        INSERT INTO progress_updates (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
        VALUES (?, ?, ?, 0, ?, 'Initial value', ?)
      `).run(info.lastInsertRowid, req.project.id, req.user.id, d.actual_pct, today());
    }
    res.status(201).json({ task: db.prepare('SELECT * FROM tasks WHERE id = ?').get(info.lastInsertRowid) });
  } catch (err) { next(err); }
});

/* ------------------------------------------------------------- time entries */

const timeInput = z.object({
  trade_id: z.number().int().nullable().optional(),
  task_id: z.number().int().nullable().optional(),
  entry_date: isoDate,
  hours: z.number().gt(0, 'Hours must be greater than zero').max(2000),
  description: z.string().max(1000).optional().default(''),
});

router.get('/:projectId/time-entries', requireProject('viewer'), (req, res) => {
  const limit = Math.min(1000, Math.max(1, Number(req.query.limit) || 200));
  const entries = db.prepare(`
    SELECT e.*, u.name AS user_name, tr.name AS trade_name, tr.color AS trade_color,
           t.wbs AS task_wbs, t.name AS task_name
    FROM time_entries e
    LEFT JOIN users u ON u.id = e.user_id
    LEFT JOIN trades tr ON tr.id = e.trade_id
    LEFT JOIN tasks t ON t.id = e.task_id
    WHERE e.project_id = ?
    ORDER BY e.entry_date DESC, e.id DESC
    LIMIT ?
  `).all(req.project.id, limit);
  res.json({ entries });
});

router.post('/:projectId/time-entries', requireProject('member'), (req, res) => {
  const parsed = timeInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const d = parsed.data;
  if (d.trade_id && !db.prepare('SELECT 1 FROM trades WHERE id = ? AND project_id = ?')
    .get(d.trade_id, req.project.id)) {
    return res.status(400).json({ error: 'Trade does not belong to this project' });
  }
  if (d.task_id && !db.prepare('SELECT 1 FROM tasks WHERE id = ? AND project_id = ?')
    .get(d.task_id, req.project.id)) {
    return res.status(400).json({ error: 'Task does not belong to this project' });
  }
  const info = db.prepare(`
    INSERT INTO time_entries (project_id, trade_id, task_id, user_id, entry_date, hours, description)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `).run(req.project.id, d.trade_id ?? null, d.task_id ?? null, req.user.id,
    d.entry_date, d.hours, d.description);
  res.status(201).json({ entry: db.prepare('SELECT * FROM time_entries WHERE id = ?').get(info.lastInsertRowid) });
});

router.delete('/:projectId/time-entries/:entryId', requireProject('member'), (req, res) => {
  const entry = db.prepare('SELECT * FROM time_entries WHERE id = ? AND project_id = ?')
    .get(req.params.entryId, req.project.id);
  if (!entry) return res.status(404).json({ error: 'Time entry not found' });
  // Members may remove their own bookings; managers may remove anyone's.
  if (entry.user_id !== req.user.id && !['owner', 'manager'].includes(req.projectRole)) {
    return res.status(403).json({ error: 'You can only delete your own time entries' });
  }
  db.prepare('DELETE FROM time_entries WHERE id = ?').run(entry.id);
  res.json({ ok: true });
});

/* ------------------------------------------------------------------ members */

router.get('/:projectId/members', requireProject('viewer'), (req, res) => {
  const members = db.prepare(`
    SELECT u.id, u.name, u.email, m.role
    FROM project_members m JOIN users u ON u.id = m.user_id
    WHERE m.project_id = ? ORDER BY u.name
  `).all(req.project.id);
  const owner = db.prepare('SELECT id, name, email FROM users WHERE id = ?').get(req.project.owner_id);
  res.json({ owner, members });
});

router.post('/:projectId/members', requireProject('manager'), (req, res) => {
  const parsed = z.object({
    email: z.string().email(),
    role: z.enum(['manager', 'member', 'viewer']).optional().default('member'),
  }).safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });

  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(parsed.data.email);
  if (!user) return res.status(404).json({ error: 'No account with that email. Ask them to register first.' });
  if (user.id === req.project.owner_id) return res.status(400).json({ error: 'That user already owns this project' });

  db.prepare(`
    INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, ?)
    ON CONFLICT (project_id, user_id) DO UPDATE SET role = excluded.role
  `).run(req.project.id, user.id, parsed.data.role);
  res.status(201).json({ member: { id: user.id, name: user.name, email: user.email, role: parsed.data.role } });
});

router.delete('/:projectId/members/:userId', requireProject('manager'), (req, res) => {
  db.prepare('DELETE FROM project_members WHERE project_id = ? AND user_id = ?')
    .run(req.project.id, req.params.userId);
  res.json({ ok: true });
});

export default router;
