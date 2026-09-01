// End-to-end smoke test: signs in, reads the dashboard, records progress,
// books hours, and checks both themes and the mobile layout.
//
//   npm install playwright && npx playwright install chromium
//   npm --prefix server run seed && npm run build && npm start
//   node e2e/smoke.mjs
//
// Run it against a freshly seeded database — it books hours, so repeated runs
// against the same database accumulate them and the budget assertion will fail.
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL || 'http://localhost:4000';
const SHOTS = process.argv[2] || 'e2e/screenshots';
const errors = [];

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on('console', (m) => {
  // The app probes /api/auth/me on load; a 401 there is the normal signed-out answer.
  const text = m.text();
  if (m.type() === 'error' && !text.includes('401')) errors.push(`console: ${text}`);
});
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));

const step = async (name, fn) => {
  try { await fn(); console.log(`  PASS  ${name}`); }
  catch (e) { console.log(`  FAIL  ${name}: ${e.message}`); errors.push(`${name}: ${e.message}`); }
};
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });

await step('login page renders', async () => {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Project Control');
  await shot('01-login');
});

await step('rejects a bad password', async () => {
  await page.fill('input[type=email]', 'admin@example.com');
  await page.fill('input[type=password]', 'totallywrong');
  await page.click('button[type=submit]');
  await page.waitForSelector('text=Incorrect email or password', { timeout: 5000 });
});

await step('signs in', async () => {
  await page.fill('input[type=password]', 'changeme123');
  await page.click('button[type=submit]');
  await page.waitForSelector('text=Portfolio', { timeout: 8000 });
  await page.waitForSelector('text=SIBLINE-PORT');
  await shot('02-portfolio');
});

await step('portfolio shows workbook figures', async () => {
  const body = await page.textContent('body');
  for (const t of ['Sibline Port', '1 late', 'Hours booked']) {
    if (!body.includes(t)) throw new Error(`missing "${t}"`);
  }
});

await step('opens the project dashboard with an S-curve', async () => {
  await page.click('text=Sibline Port');
  await page.waitForSelector('text=Progress S-curve', { timeout: 8000 });
  await page.waitForSelector('.recharts-line', { timeout: 8000 });
  const lines = await page.locator('.recharts-line').count();
  if (lines < 2) throw new Error(`expected planned and earned lines, found ${lines}`);
  await page.waitForTimeout(600);
  await shot('03-dashboard');
});

await step('trade table lists all four trades', async () => {
  const body = await page.textContent('body');
  for (const t of ['Marine', 'Geotechnical', 'Marine Structures', 'Utilities']) {
    if (!body.includes(t)) throw new Error(`missing trade "${t}"`);
  }
});

await step('progress page lists deliverables', async () => {
  await page.click('a:has-text("Progress")');
  await page.waitForSelector('text=Progress update', { timeout: 8000 });
  await page.waitForSelector('text=Marine Design');
  await shot('04-progress');
});

await step('records a progress update', async () => {
  const row = page.locator('tr', { hasText: 'Coastal numerical modelling' }).first();
  await row.locator('button:has-text("Update")').click();
  const input = row.locator('input[type=number]');
  await input.fill('35');
  await row.locator('button:has-text("Save")').click();
  await page.waitForSelector('text=Progress update', { timeout: 8000 });
  await page.waitForTimeout(800);
  const text = await page.locator('tr', { hasText: 'Coastal numerical modelling' }).first().textContent();
  if (!text.includes('35%')) throw new Error(`progress did not persist: ${text.slice(0, 120)}`);
});

await step('filters to late deliverables', async () => {
  await page.click('button:has-text("Late")');
  await page.waitForTimeout(500);
  const body = await page.textContent('body');
  if (!body.includes('kick-off')) throw new Error('expected the late kick-off milestone');
  await page.click('button:has-text("All")');
});

await step('schedule page splits late / due soon / behind', async () => {
  await page.click('a:has-text("Schedule")');
  await page.waitForSelector('text=Late deliverables', { timeout: 8000 });
  await page.waitForSelector('text=Behind plan');
  await shot('05-schedule');
});

await step('budget page renders the hours chart', async () => {
  await page.click('a:has-text("Budget")');
  await page.waitForSelector('text=Budget control', { timeout: 8000 });
  await page.waitForSelector('.recharts-wrapper', { timeout: 8000 });
  // Bars can legitimately be zero-width before any hours are booked, so count
  // the series groups rather than waiting for a visible rectangle.
  const bars = await page.locator('.recharts-bar').count();
  if (bars < 3) throw new Error(`expected booked/remaining/over series, found ${bars}`);
  await page.waitForTimeout(500);
  await shot('06-budget');
});

await step('books hours and they reach budget control', async () => {
  await page.click('a:has-text("Timesheet")');
  await page.waitForSelector('text=Book hours', { timeout: 8000 });
  await page.selectOption('select >> nth=0', { label: 'Geotechnical' });
  await page.fill('input[type=number]', '36');
  await page.fill('input[placeholder="What the time went on"]', 'Borehole data review');
  await page.click('button:has-text("Book hours")');
  await page.waitForTimeout(1200);
  const body = await page.textContent('body');
  if (!body.includes('Borehole data review')) throw new Error('entry not listed');
  await shot('07-timesheet');

  await page.click('a:has-text("Budget")');
  await page.waitForSelector('text=Budget control', { timeout: 8000 });
  await page.waitForTimeout(800);
  const budget = await page.textContent('body');
  if (!budget.includes('36 h')) throw new Error('booked hours did not reach budget control');
});

await step('setup page loads the editable deliverable list', async () => {
  await page.click('a:has-text("Setup")');
  await page.waitForSelector('text=Project setup', { timeout: 8000 });
  await page.waitForSelector('text=Deliverables');
  await shot('08-setup');
});

await step('dark mode renders', async () => {
  await page.click('a:has-text("Dashboard")');
  await page.waitForSelector('text=Progress S-curve', { timeout: 8000 });
  await page.evaluate(() => { localStorage.setItem('pm-theme', 'dark'); document.documentElement.setAttribute('data-theme', 'dark'); });
  await page.waitForTimeout(900);
  await shot('09-dashboard-dark');
});

await step('mobile layout does not overflow horizontally', async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(700);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 2) throw new Error(`page scrolls horizontally by ${overflow}px`);
  await shot('10-mobile');
});

await browser.close();

console.log(`\n${errors.length ? 'ERRORS:' : 'No errors.'}`);
for (const e of errors) console.log('  -', e);
process.exit(errors.length ? 1 : 0);
