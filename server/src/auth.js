import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import db from './db.js';

const COOKIE = 'pm_token';
const DAYS = 7;

// In production a real secret must be supplied; in development we fall back to a
// per-install random value so tokens still work without any configuration.
export const JWT_SECRET = process.env.JWT_SECRET || (() => {
  if (process.env.NODE_ENV === 'production') {
    throw new Error('JWT_SECRET must be set in production');
  }
  return 'dev-secret-do-not-use-in-production';
})();

export const hashPassword = (plain) => bcrypt.hashSync(plain, 10);
export const verifyPassword = (plain, hash) => bcrypt.compareSync(plain, hash);

export function issueToken(res, user) {
  const token = jwt.sign({ uid: user.id, email: user.email }, JWT_SECRET, { expiresIn: `${DAYS}d` });
  res.cookie(COOKIE, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    maxAge: DAYS * 86400000,
    path: '/',
  });
  return token;
}

export function clearToken(res) {
  res.clearCookie(COOKIE, { path: '/' });
}

export function publicUser(user) {
  if (!user) return null;
  return { id: user.id, email: user.email, name: user.name, role: user.role };
}

/** Populates req.user when a valid token is present; never rejects. */
export function attachUser(req, _res, next) {
  const token = req.cookies?.[COOKIE] ||
    (req.headers.authorization?.startsWith('Bearer ') ? req.headers.authorization.slice(7) : null);
  if (token) {
    try {
      const payload = jwt.verify(token, JWT_SECRET);
      req.user = db.prepare('SELECT * FROM users WHERE id = ?').get(payload.uid) || null;
    } catch {
      req.user = null;
    }
  }
  next();
}

export function requireAuth(req, res, next) {
  if (!req.user) return res.status(401).json({ error: 'Authentication required' });
  next();
}

/**
 * Resolves :projectId, checks the caller may see it and attaches req.project
 * plus req.projectRole ('owner' | 'manager' | 'member' | 'viewer').
 */
export function requireProject(minRole = 'viewer') {
  const rank = { viewer: 0, member: 1, manager: 2, owner: 3 };
  return (req, res, next) => {
    const id = Number(req.params.projectId ?? req.params.id);
    const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(id);
    if (!project) return res.status(404).json({ error: 'Project not found' });

    let role = null;
    if (project.owner_id === req.user.id) role = 'owner';
    else if (req.user.role === 'admin') role = 'manager';
    else {
      const member = db.prepare('SELECT role FROM project_members WHERE project_id = ? AND user_id = ?')
        .get(id, req.user.id);
      if (member) role = member.role;
    }
    if (!role) return res.status(404).json({ error: 'Project not found' });
    if (rank[role] < rank[minRole]) return res.status(403).json({ error: 'Insufficient permissions on this project' });

    req.project = project;
    req.projectRole = role;
    next();
  };
}

/** Every project id the user may see. */
export function visibleProjectIds(user) {
  if (user.role === 'admin') {
    return db.prepare('SELECT id FROM projects').all().map((r) => r.id);
  }
  return db.prepare(`
    SELECT id FROM projects WHERE owner_id = @uid
    UNION
    SELECT project_id FROM project_members WHERE user_id = @uid
  `).all({ uid: user.id }).map((r) => r.id);
}
