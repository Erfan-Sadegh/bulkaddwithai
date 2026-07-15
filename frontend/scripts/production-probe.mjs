import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const [appUrl, outputDir] = process.argv.slice(2);
if (!appUrl || !outputDir) throw new Error('usage: production-probe.mjs <app-url> <output-dir>');

await mkdir(outputDir, { recursive: true });
const origin = new URL(appUrl).origin;
const browser = await chromium.launch({ headless: true });
const views = [];

for (const view of [
  { name: 'desktop', viewport: { width: 1440, height: 1000 } },
  { name: 'mobile', viewport: { width: 390, height: 844 } },
]) {
  const context = await browser.newContext({ viewport: view.viewport, locale: 'fa-IR' });
  const page = await context.newPage();
  const issues = new Set();

  page.on('pageerror', () => issues.add('page_error'));
  page.on('console', (message) => {
    if (message.type() === 'error') issues.add('console_error');
  });
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).origin !== origin) return;
    if (['document', 'script', 'stylesheet'].includes(request.resourceType())) issues.add('resource_failed');
  });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const target = new URL(request.url());
    if (target.origin !== origin) {
      // Analytics is intentionally excluded from this privacy-safe synthetic page load.
      if (request.resourceType() === 'script') {
        await route.fulfill({ status: 200, contentType: 'application/javascript', body: '' });
      } else {
        await route.fulfill({ status: 204, body: '' });
      }
      return;
    }
    const method = request.method();
    if (target.pathname === '/sellers' && method === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 999,
          name: '',
          mobile: '',
          shop_name: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      });
      return;
    }
    if (target.pathname === '/sellers/999/platform-connections' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      return;
    }
    if (target.pathname.startsWith('/observability/') && method === 'POST') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      issues.add('mutation_attempt');
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });

  try {
    const response = await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    if (!response || !response.ok()) issues.add('document_failed');
    await page.waitForTimeout(1500);
    if (!(await page.locator('.app-shell').isVisible().catch(() => false))) issues.add('app_shell_missing');
    if ((await page.locator('.platform-card:visible').count()) !== 2) issues.add('primary_actions_missing');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    if (overflow) issues.add('horizontal_overflow');
  } catch {
    issues.add('navigation_failed');
  }

  const screenshot = `production-${view.name}.png`;
  await page.screenshot({ path: path.join(outputDir, screenshot), fullPage: true });
  views.push({ name: view.name, screenshot, issues: [...issues].sort() });
  await context.close();
}

await browser.close();
await writeFile(path.join(outputDir, 'browser-probe.json'), JSON.stringify({ app_url: origin, views }, null, 2));
