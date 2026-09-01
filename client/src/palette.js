// The categorical series slots, in fixed order. Both columns are selected for
// their own surface — the dark column is not a computed inversion of the light one.
export const SERIES = [
  { name: 'Blue',    light: '#2a78d6', dark: '#3987e5' },
  { name: 'Orange',  light: '#eb6834', dark: '#d95926' },
  { name: 'Aqua',    light: '#1baf7a', dark: '#199e70' },
  { name: 'Yellow',  light: '#eda100', dark: '#c98500' },
  { name: 'Magenta', light: '#e87ba4', dark: '#d55181' },
  { name: 'Green',   light: '#008300', dark: '#008300' },
  { name: 'Violet',  light: '#4a3aa7', dark: '#9085e9' },
  { name: 'Red',     light: '#e34948', dark: '#e66767' },
];

const DARK_OF = Object.fromEntries(SERIES.map((s) => [s.light.toLowerCase(), s.dark]));

export const isDark = () => {
  const stamped = document.documentElement.getAttribute('data-theme');
  if (stamped) return stamped === 'dark';
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
};

/** A stored trade colour, re-stepped for the dark surface when one is known. */
export const tradeColor = (hex, dark = isDark()) =>
  (dark ? DARK_OF[String(hex || '').toLowerCase()] : null) || hex || SERIES[0].light;

/** Status colours are fixed and never themed; they always ship with a label. */
export const STATUS = {
  good: 'var(--good)',
  warning: 'var(--warning)',
  serious: 'var(--serious)',
  critical: 'var(--critical)',
  neutral: 'var(--muted)',
};
