export const pct = (value, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value) ? '—' : `${(value * 100).toFixed(digits)}%`;

export const signedPct = (value, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const s = (value * 100).toFixed(digits);
  return `${value > 0 ? '+' : ''}${s}%`;
};

export const hours = (value, digits = 0) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '—'
    : `${Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} h`;

export const num = (value, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '—'
    : Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const index = (value) => (value === null || value === undefined ? '—' : Number(value).toFixed(2));

export const shortDate = (iso) => {
  if (!iso) return '—';
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
};

export const todayISO = () => new Date().toISOString().slice(0, 10);

/** Health of a progress variance, used to pick a status colour and label. */
export function varianceState(variance) {
  if (variance === null || variance === undefined) return 'neutral';
  if (variance >= -0.0001) return 'good';
  if (variance >= -0.05) return 'warning';
  return 'critical';
}
