import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const [appUrl, outputDir] = process.argv.slice(2);
if (!appUrl || !outputDir) throw new Error('usage: production-probe.mjs <app-url> <output-dir>');

await mkdir(outputDir, { recursive: true });
const origin = new URL(appUrl).origin;
const browser = await chromium.launch({ headless: true });
const views = [];
const probePng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=',
  'base64',
);
const now = '2026-01-01T00:00:00Z';
const fakeBatch = { id: 1000, seller_id: 999, status: 'draft', raw_transcript: null, ai_metadata: null, created_at: now, updated_at: now };
const fakeAsset = {
  id: 1001, batch_id: 1000, type: 'image', upload_order: 1,
  original_filename: 'synthetic-probe.png', mime_type: 'image/png', size_bytes: probePng.length,
  checksum: 'synthetic', url: '/probe-image.png', created_at: now,
};
const fakeItem = {
  id: 1002, batch_id: 1000, title: 'محصول آزمایشی', description: 'داده ساختگی browser probe',
  price_toman: 100000, stock: 1, preparation_days: 1, weight_grams: 100,
  package_weight_grams: 100, unit_quantity: 1, confidence: 0.95, edited_by_user: false,
  photos: [{ asset_id: 1001, upload_order: 1, url: '/probe-image.png', role: 'product_photo', sort_order: 1 }],
  basalam_category: {
    category_id: 20, title: 'دسته آزمایشی', path: 'دسته آزمایشی', confidence: 1, source: 'auto',
    unit_type_id: 6304, unit_type_title: 'عددی', max_preparation_days: 7,
  },
  created_at: now, updated_at: now,
};

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
          created_at: now,
          updated_at: now,
        }),
      });
      return;
    }
    if (target.pathname === '/sellers/999/platform-connections' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      return;
    }
    if (target.pathname === '/batches' && method === 'POST') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(fakeBatch) });
      return;
    }
    if (target.pathname === '/batches/1000/assets' && method === 'POST') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify([fakeAsset]) });
      return;
    }
    if (target.pathname === '/probe-image.png' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'image/png', body: probePng });
      return;
    }
    if (target.pathname === '/batches/1000/process' && method === 'POST') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: '{"job_id":2000}' });
      return;
    }
    if (target.pathname === '/jobs/2000' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 2000, batch_id: 1000, status: 'succeeded', step: 'ready', error: null }) });
      return;
    }
    if (target.pathname === '/batches/1000/items' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([fakeItem]) });
      return;
    }
    if (target.pathname === '/batches/1000/categories/basalam/suggest' && method === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([fakeItem]) });
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
    await page.screenshot({ path: path.join(outputDir, `production-${view.name}.png`), fullPage: true });

    try {
      await page.locator('.platform-card').first().click();
      await page.locator('.upload-panel').waitFor({ state: 'visible', timeout: 5000 });
    } catch {
      issues.add('platform_open_failed');
    }
    const imageInput = page.locator('input[type="file"][accept="image/*"]').first();
    if ((await imageInput.count()) === 0 || !(await imageInput.isEnabled().catch(() => false))) {
      issues.add('file_picker_missing');
    } else {
      try {
        const chooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
        await imageInput.click({ force: true });
        const chooser = await chooserPromise;
        await chooser.setFiles({ name: 'synthetic-probe.png', mimeType: 'image/png', buffer: probePng });
        await page.locator('.photo-tile').first().waitFor({ state: 'visible', timeout: 8000 });
      } catch {
        issues.add('file_picker_failed');
      }
    }
    if ((await page.locator('.photo-tile:visible').count()) < 1) issues.add('upload_render_failed');
    const buildButton = page.locator('.action-button:visible').first();
    if ((await buildButton.count()) === 0 || !(await buildButton.isEnabled().catch(() => false))) {
      issues.add('build_action_missing');
    } else {
      try {
        await buildButton.click();
        await page.locator('.product-card').first().waitFor({ state: 'visible', timeout: 8000 });
      } catch {
        issues.add('list_build_failed');
      }
    }
    if ((await page.locator('.product-card:visible').count()) < 1) issues.add('product_review_missing');
  } catch {
    issues.add('navigation_failed');
  }

  const screenshot = `production-${view.name}-journey.png`;
  await page.screenshot({ path: path.join(outputDir, screenshot), fullPage: true });
  views.push({ name: view.name, screenshot, issues: [...issues].sort() });
  await context.close();
}

await browser.close();
await writeFile(path.join(outputDir, 'browser-probe.json'), JSON.stringify({ app_url: origin, views }, null, 2));
