// Loads the demo project (converted from the Sibline Port control workbook) and
// creates a starting account. Safe to run more than once: it skips work already done.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import db from './db.js';
import { hashPassword } from './auth.js';
import { today } from './service.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const seedFile = process.env.SEED_FILE || path.join(here, '..', 'seed', 'sibline-port.json');

const email = process.env.SEED_EMAIL || 'admin@example.com';
const password = process.env.SEED_PASSWORD || 'changeme123';
const name = process.env.SEED_NAME || 'Project Manager';

let user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
if (!user) {
  const info = db.prepare('INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)')
    .run(email, name, hashPassword(password), 'admin');
  user = db.prepare('SELECT * FROM users WHERE id = ?').get(info.lastInsertRowid);
  console.log(`Created account ${email} (password: ${password})`);
} else {
  console.log(`Account ${email} already exists — leaving it alone`);
}

const seed = JSON.parse(fs.readFileSync(seedFile, 'utf8'));

if (db.prepare('SELECT 1 FROM projects WHERE code = ?').get(seed.project.code)) {
  console.log(`Project ${seed.project.code} already seeded — nothing to do`);
  process.exit(0);
}

const load = db.transaction(() => {
  const p = seed.project;
  const projectId = db.prepare(`
    INSERT INTO projects (code, name, client, description, ntp_date, duration_months,
                          days_per_month, hours_per_month, elapsed_day_offset, status, owner_id)
    VALUES (@code, @name, @client, @description, @ntp_date, @duration_months,
            @days_per_month, @hours_per_month, @elapsed_day_offset, @status, @owner_id)
  `).run({ ...p, owner_id: user.id }).lastInsertRowid;

  const tradeIds = {};
  for (const t of seed.trades) {
    tradeIds[t.key] = db.prepare(
      'INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(projectId, t.key, t.name, t.budget_hours, t.color, t.sort_order).lastInsertRowid;
  }

  const sectionIds = {};
  for (const s of seed.sections) {
    sectionIds[s.code] = db.prepare(
      'INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)'
    ).run(projectId, s.code, s.name, s.sort_order).lastInsertRowid;
  }

  const insertTask = db.prepare(`
    INSERT INTO tasks (project_id, section_id, wbs, name, weight_points, start_month,
                       finish_month, actual_pct, remarks, sort_order)
    VALUES (@project_id, @section_id, @wbs, @name, @weight_points, @start_month,
            @finish_month, @actual_pct, @remarks, @sort_order)
  `);
  const insertAlloc = db.prepare('INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)');
  const insertProgress = db.prepare(`
    INSERT INTO progress_updates (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
    VALUES (?, ?, ?, 0, ?, 'Imported from control workbook', ?)
  `);

  for (const t of seed.tasks) {
    const taskId = insertTask.run({
      project_id: projectId,
      section_id: sectionIds[t.section_code] ?? null,
      wbs: t.wbs,
      name: t.name,
      weight_points: t.weight_points,
      start_month: t.start_month,
      finish_month: t.finish_month,
      actual_pct: t.actual_pct,
      remarks: t.remarks,
      sort_order: t.sort_order,
    }).lastInsertRowid;

    for (const [key, pct] of Object.entries(t.allocations)) {
      if (pct > 0) insertAlloc.run(taskId, tradeIds[key], pct);
    }
    if (t.actual_pct > 0) {
      insertProgress.run(taskId, projectId, user.id, t.actual_pct, p.ntp_date > today() ? p.ntp_date : today());
    }
  }
  return projectId;
});

const id = load();
console.log(`Seeded "${seed.project.name}" (project #${id}) with ${seed.tasks.length} deliverables ` +
  `across ${seed.sections.length} sections and ${seed.trades.length} trades.`);
