import { useState } from 'react';
import { useAuth } from '../auth.jsx';
import { Field } from '../components/ui.jsx';

export default function Login() {
  const { login, register, signupOpen } = useAuth();
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ email: '', name: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'login') await login(form.email.trim(), form.password);
      else await register(form.email.trim(), form.name.trim(), form.password);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div
            className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl text-lg font-bold text-white"
            style={{ background: 'var(--series-1)' }}
            aria-hidden="true"
          >
            PC
          </div>
          <h1 className="text-lg font-semibold text-ink">Project Control</h1>
          <p className="mt-1 text-sm text-muted">Progress, schedule and budget across your portfolio</p>
        </div>

        <form onSubmit={submit} className="card space-y-4 p-5">
          <div className="flex gap-1 rounded-lg p-1" style={{ background: 'var(--plane)' }}>
            {['login', 'register'].map((m) => (
              <button
                key={m}
                type="button"
                disabled={m === 'register' && !signupOpen}
                onClick={() => { setMode(m); setError(''); }}
                className="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-40"
                style={mode === m
                  ? { background: 'var(--surface)', color: 'var(--ink)', boxShadow: '0 1px 2px rgba(0,0,0,0.06)' }
                  : { color: 'var(--muted)' }}
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          {mode === 'register' && (
            <Field label="Full name">
              <input className="field" value={form.name} onChange={set('name')} autoComplete="name" required />
            </Field>
          )}

          <Field label="Email">
            <input className="field" type="email" value={form.email} onChange={set('email')}
                   autoComplete="username" required />
          </Field>

          <Field label="Password" hint={mode === 'register' ? 'At least 8 characters' : undefined}>
            <input className="field" type="password" value={form.password} onChange={set('password')}
                   autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={8} />
          </Field>

          {error && (
            <p role="alert" className="rounded-lg px-3 py-2 text-sm"
               style={{ background: 'rgba(208, 59, 59, 0.10)', color: 'var(--critical)' }}>
              {error}
            </p>
          )}

          <button type="submit" className="btn btn-primary w-full" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>

          {!signupOpen && mode === 'login' && (
            <p className="text-center text-xs text-muted">
              New accounts are created by an administrator.
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
