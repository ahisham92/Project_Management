import { STATUS } from '../palette.js';

export function Card({ title, subtitle, action, children, className = '', bodyClass = 'p-4' }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

/**
 * A single headline figure. `state` drives an icon + word, so the meaning never
 * rests on colour alone.
 */
export function StatTile({ label, value, hint, state = 'neutral', stateLabel }) {
  const icons = { good: '●', warning: '▲', serious: '▲', critical: '■', neutral: '' };
  return (
    <div className="card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold text-ink">{value}</p>
      {(hint || stateLabel) && (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-ink2">
          {stateLabel && (
            <span className="inline-flex items-center gap-1 font-medium" style={{ color: STATUS[state] }}>
              <span aria-hidden="true">{icons[state]}</span>
              {stateLabel}
            </span>
          )}
          {hint && <span className="text-muted">{hint}</span>}
        </p>
      )}
    </div>
  );
}

export function Badge({ state = 'neutral', children, title }) {
  const tints = {
    good: 'rgba(12, 163, 12, 0.12)',
    warning: 'rgba(250, 178, 25, 0.16)',
    serious: 'rgba(236, 131, 90, 0.16)',
    critical: 'rgba(208, 59, 59, 0.14)',
    neutral: 'var(--raised)',
  };
  const icons = { good: '●', warning: '▲', serious: '▲', critical: '■', neutral: '○' };
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium"
      style={{ background: tints[state], color: state === 'neutral' ? 'var(--ink-2)' : STATUS[state] }}
    >
      <span aria-hidden="true">{icons[state]}</span>
      {children}
    </span>
  );
}

/** Horizontal progress bar. The planned marker shows where the task should be. */
export function ProgressBar({ value, planned, color = 'var(--series-1)', height = 8 }) {
  const clamp = (n) => Math.min(1, Math.max(0, n || 0));
  return (
    <div className="relative w-full rounded-full" style={{ height, background: 'var(--grid)' }}>
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${clamp(value) * 100}%`, background: color }}
      />
      {planned !== undefined && planned !== null && (
        <div
          className="absolute inset-y-[-2px] w-0.5 rounded"
          style={{ left: `${clamp(planned) * 100}%`, background: 'var(--ink-2)' }}
          title={`Planned ${(clamp(planned) * 100).toFixed(1)}%`}
        />
      )}
    </div>
  );
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      {label}
    </div>
  );
}

export function ErrorNote({ children, onRetry }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-lg px-3 py-2 text-sm"
      style={{ background: 'rgba(208, 59, 59, 0.10)', color: 'var(--critical)' }}
    >
      <span>{children}</span>
      {onRetry && <button type="button" className="underline" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children }) {
  return (
    <div className="px-4 py-12 text-center">
      <p className="text-sm font-medium text-ink2">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-xs text-muted">{children}</p>}
    </div>
  );
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-ink2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
