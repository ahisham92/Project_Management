/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        plane: 'var(--plane)',
        surface: 'var(--surface)',
        raised: 'var(--raised)',
        ink: 'var(--ink)',
        ink2: 'var(--ink-2)',
        muted: 'var(--muted)',
        hairline: 'var(--border)',
        grid: 'var(--grid)',
        good: 'var(--good)',
        warning: 'var(--warning)',
        serious: 'var(--serious)',
        critical: 'var(--critical)',
        accent: 'var(--series-1)',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
