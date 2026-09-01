import Database from 'better-sqlite3';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// DATA_DIR lets a deployment point the database at a mounted persistent volume.
const dataDir = process.env.DATA_DIR || path.join(here, '..', 'data');
fs.mkdirSync(dataDir, { recursive: true });

export const dbPath = process.env.DATABASE_FILE || path.join(dataDir, 'pm.sqlite');
export const db = new Database(dbPath);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');
db.exec(fs.readFileSync(path.join(here, 'schema.sql'), 'utf8'));

/** Adds a column to an existing database if a newer schema introduced it. */
function ensureColumn(table, column, definition) {
  const exists = db.prepare(`PRAGMA table_info(${table})`).all().some((c) => c.name === column);
  if (!exists) db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}

ensureColumn('projects', 'elapsed_day_offset', 'REAL NOT NULL DEFAULT 0');

export default db;
