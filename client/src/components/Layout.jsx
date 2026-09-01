import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useParams } from 'react-router-dom';
import { useAuth } from '../auth.jsx';

function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem('pm-theme') || 'system');

  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('pm-theme', theme);
  }, [theme]);

  const next = { system: 'light', light: 'dark', dark: 'system' };
  const icon = { system: '◐', light: '☀', dark: '☾' };
  return (
    <button
      type="button"
      className="btn btn-ghost px-2 py-1"
      title={`Theme: ${theme}. Click to switch.`}
      aria-label={`Theme: ${theme}. Click to switch.`}
      onClick={() => setTheme(next[theme])}
    >
      <span aria-hidden="true">{icon[theme]}</span>
    </button>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { id } = useParams();

  const tabs = id ? [
    { to: `/projects/${id}`, label: 'Dashboard', end: true },
    { to: `/projects/${id}/tasks`, label: 'Progress' },
    { to: `/projects/${id}/schedule`, label: 'Schedule' },
    { to: `/projects/${id}/budget`, label: 'Budget' },
    { to: `/projects/${id}/time`, label: 'Timesheet' },
    { to: `/projects/${id}/settings`, label: 'Setup' },
  ] : [];

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-hairline" style={{ background: 'var(--surface)' }}>
        <div className="mx-auto flex max-w-[1400px] items-center gap-4 px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2">
            <span
              className="flex h-7 w-7 items-center justify-center rounded-lg text-xs font-bold text-white"
              style={{ background: 'var(--series-1)' }}
              aria-hidden="true"
            >
              PC
            </span>
            <span className="text-sm font-semibold text-ink">Project Control</span>
          </Link>

          <nav className="ml-2 hidden sm:block">
            <NavLink
              to="/"
              end
              className={({ isActive }) => `rounded-md px-2.5 py-1 text-sm ${isActive ? 'font-medium text-ink' : 'text-muted hover:text-ink'}`}
            >
              Portfolio
            </NavLink>
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <div className="hidden text-right sm:block">
              <p className="text-xs font-medium leading-tight text-ink">{user?.name}</p>
              <p className="text-xs leading-tight text-muted">{user?.email}</p>
            </div>
            <button type="button" className="btn btn-ghost" onClick={logout}>Sign out</button>
          </div>
        </div>

        {tabs.length > 0 && (
          <div className="mx-auto max-w-[1400px] overflow-x-auto px-4">
            <nav className="flex gap-1">
              {tabs.map((t) => (
                <NavLink
                  key={t.to}
                  to={t.to}
                  end={t.end}
                  className={({ isActive }) =>
                    `whitespace-nowrap border-b-2 px-3 py-2 text-sm transition ${
                      isActive ? 'font-medium text-ink' : 'border-transparent text-muted hover:text-ink'
                    }`}
                  style={({ isActive }) => (isActive ? { borderColor: 'var(--series-1)' } : undefined)}
                >
                  {t.label}
                </NavLink>
              ))}
            </nav>
          </div>
        )}
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}
