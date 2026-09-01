import { Router } from 'express';
import { z } from 'zod';
import db from '../db.js';
import { requireAuth } from '../auth.js';
import { setAllocations, today } from '../service.js';

const router = Router();
router.use(requireAuth);

const rank = { viewer: 0, member: 1, manager: 2, owner: 3 };

/** Resolves :taskId to its task + project and checks the caller's access. */
function withTask(minRole = 'viewer') {
  return (req, res, next) => {
    const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(req.params.taskId);
    if (!task) return res.status(404).json({ error: 'Task not found' });
    const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(task.project_id);
    if (!project) return res.status(404).json({ error: 'Task not found' });

    let role = null;
    if (project.owner_id === req.user.id) role = 'owner';
    else if (req.user.role === 'admin') role = 'manager';
    else {
      const member = db.prepare('SELECT role FROM project_members WHERE project_id = ? AND user_id = ?')
        .get(project.id, req.user.id);
      if (member) role = member.role;
    }
    if (!role) return res.status(404).json({ error: 'Task not found' });
    if (rank[role] < rank[minRole]) return res.status(403).json({ error: 'Insufficient permissions on this project' });

    req.task = task;
    req.project = project;
    req.projectRole = role;
    next();
  };
}

const taskPatch = z.object({
  section_id: z.number().int().nullable().optional(),
  wbs: z.string().max(20).optional(),
  name: z.string().min(1).max(500).optional(),
  weight_points: z.number().min(0).max(100000).optional(),
  start_month: z.number().min(0).max(600).optional(),
  finish_month: z.number().min(0).max(600).optional(),
  remarks: z.string().max(2000).optional(),
  sort_order: z.number().int().optional(),
  allocations: z.record(z.coerce.number()).optional(),
});

router.get('/:taskId', withTask('viewer'), (req, res) => {
  const allocations = db.prepare('SELECT trade_id, pct FROM task_allocations WHERE task_id = ?').all(req.task.id);
  const history = db.prepare(`
    SELECT p.*, u.name AS user_name
    FROM progress_updates p LEFT JOIN users u ON u.id = p.user_id
    WHERE p.task_id = ? ORDER BY p.data_date DESC, p.id DESC
  `).all(req.task.id);
  const hours = db.prepare('SELECT COALESCE(SUM(hours), 0) AS hours FROM time_entries WHERE task_id = ?')
    .get(req.task.id).hours;
  res.json({ task: req.task, allocations, history, spent_hours: hours });
});

router.patch('/:taskId', withTask('manager'), (req, res, next) => {
  const parsed = taskPatch.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const { allocations, ...fields } = parsed.data;
  if (fields.section_id && !db.prepare('SELECT 1 FROM sections WHERE id = ? AND project_id = ?')
    .get(fields.section_id, req.project.id)) {
    return res.status(400).json({ error: 'Section does not belong to this project' });
  }
  try {
    const keys = Object.keys(fields);
    if (keys.length) {
      db.prepare(
        `UPDATE tasks SET ${keys.map((f) => `${f} = @${f}`).join(', ')}, updated_at = datetime('now') WHERE id = @id`
      ).run({ ...fields, id: req.task.id });
    }
    if (allocations) setAllocations(req.task.id, req.project.id, allocations);
    res.json({ task: db.prepare('SELECT * FROM tasks WHERE id = ?').get(req.task.id) });
  } catch (err) { next(err); }
});

/**
 * Records progress. Every update is written to the history so the S-curve and
 * period reports can show what was reported when, not just the latest value.
 */
router.post('/:taskId/progress', withTask('member'), (req, res) => {
  const parsed = z.object({
    actual_pct: z.number().min(0).max(1),
    note: z.string().max(1000).optional().default(''),
    data_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  }).safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: 'Progress must be a value between 0% and 100%' });

  const { actual_pct, note } = parsed.data;
  const dataDate = parsed.data.data_date || today();
  const previous = req.task.actual_pct;

  const tx = db.transaction(() => {
    db.prepare("UPDATE tasks SET actual_pct = ?, updated_at = datetime('now') WHERE id = ?")
      .run(actual_pct, req.task.id);
    db.prepare(`
      INSERT INTO progress_updates (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(req.task.id, req.project.id, req.user.id, previous, actual_pct, note, dataDate);
  });
  tx();

  res.json({
    task: db.prepare('SELECT * FROM tasks WHERE id = ?').get(req.task.id),
    previous_pct: previous,
  });
});

router.delete('/:taskId', withTask('manager'), (req, res) => {
  db.prepare('DELETE FROM tasks WHERE id = ?').run(req.task.id);
  res.json({ ok: true });
});

export default router;
