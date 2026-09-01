import { Router } from 'express';
import { z } from 'zod';
import db from '../db.js';
import { hashPassword, verifyPassword, issueToken, clearToken, publicUser, requireAuth } from '../auth.js';

const router = Router();

const credentials = z.object({
  email: z.string().email().max(200),
  password: z.string().min(8, 'Password must be at least 8 characters').max(200),
  name: z.string().min(1).max(120).optional(),
});

const allowSignup = () => process.env.ALLOW_SIGNUP !== 'false';

router.post('/register', (req, res) => {
  const parsed = credentials.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0].message });
  const { email, password, name } = parsed.data;

  const isFirstUser = db.prepare('SELECT COUNT(*) AS n FROM users').get().n === 0;
  if (!isFirstUser && !allowSignup()) {
    return res.status(403).json({ error: 'Self-registration is disabled. Ask an administrator for an account.' });
  }
  if (db.prepare('SELECT 1 FROM users WHERE email = ?').get(email)) {
    return res.status(409).json({ error: 'An account with that email already exists' });
  }

  const info = db.prepare(
    'INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)'
  ).run(email, name || email.split('@')[0], hashPassword(password), isFirstUser ? 'admin' : 'user');

  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(info.lastInsertRowid);
  issueToken(res, user);
  res.status(201).json({ user: publicUser(user) });
});

router.post('/login', (req, res) => {
  const parsed = credentials.pick({ email: true, password: true }).safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: 'Enter a valid email and password' });

  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(parsed.data.email);
  if (!user || !verifyPassword(parsed.data.password, user.password_hash)) {
    return res.status(401).json({ error: 'Incorrect email or password' });
  }
  issueToken(res, user);
  res.json({ user: publicUser(user) });
});

router.post('/logout', (req, res) => {
  clearToken(res);
  res.json({ ok: true });
});

router.get('/me', (req, res) => {
  res.json({ user: publicUser(req.user), signup_open: allowSignup() || db.prepare('SELECT COUNT(*) AS n FROM users').get().n === 0 });
});

router.post('/password', requireAuth, (req, res) => {
  const schema = z.object({ current: z.string(), next: z.string().min(8).max(200) });
  const parsed = schema.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: 'New password must be at least 8 characters' });
  if (!verifyPassword(parsed.data.current, req.user.password_hash)) {
    return res.status(401).json({ error: 'Current password is incorrect' });
  }
  db.prepare('UPDATE users SET password_hash = ? WHERE id = ?').run(hashPassword(parsed.data.next), req.user.id);
  res.json({ ok: true });
});

export default router;
