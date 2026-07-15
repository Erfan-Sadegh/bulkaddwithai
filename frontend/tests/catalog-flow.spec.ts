import { expect, test, type Page } from '@playwright/test';

const now = new Date().toISOString();
const seller = { id: 1, name: 'فروشنده', mobile: '-', shop_name: 'فروشگاه', created_at: now, updated_at: now };
const batch = { id: 7, seller_id: 1, status: 'draft', raw_transcript: null, ai_metadata: null, created_at: now, updated_at: now };
const assets = [
  { id: 11, batch_id: 7, type: 'image', upload_order: 1, original_filename: 'a.jpg', mime_type: 'image/jpeg', size_bytes: 3, checksum: 'a', url: '/files/7/image/0001.jpg', created_at: now },
  { id: 12, batch_id: 7, type: 'image', upload_order: 2, original_filename: 'b.jpg', mime_type: 'image/jpeg', size_bytes: 3, checksum: 'b', url: '/files/7/image/0002.jpg', created_at: now },
  { id: 13, batch_id: 7, type: 'audio', upload_order: 1, original_filename: 'voice.webm', mime_type: 'audio/webm', size_bytes: 3, checksum: 'c', url: '/files/7/audio/0001.webm', created_at: now },
];
const item = {
  id: 101,
  batch_id: 7,
  title: 'محصول تستی',
  description: 'توضیح اولیه',
  price_toman: 123000,
  stock: null,
  preparation_days: null,
  weight_grams: null,
  package_weight_grams: null,
  unit_quantity: null,
  confidence: 0.73,
  edited_by_user: false,
  photos: [
    { asset_id: 11, upload_order: 1, url: '/files/7/image/0001.jpg', role: 'product_photo', sort_order: 1 },
    { asset_id: 12, upload_order: 2, url: '/files/7/image/0002.jpg', role: 'product_photo', sort_order: 2 },
  ],
  basalam_category: null,
  created_at: now,
  updated_at: now,
};
const basalamCategory = {
  category_id: 20,
  title: 'گروه شده',
  path: 'کالای دیجیتال > گروه شده',
  confidence: 0.88,
  source: 'auto',
  unit_type_id: 6304,
  unit_type_title: 'عددی',
  max_preparation_days: 7,
};
const basalamConnection = {
  id: 501,
  seller_id: 1,
  platform: 'basalam',
  status: 'connected',
  external_user_id: '42',
  external_shop_id: '476077',
  external_shop_slug: 'test-shop',
  external_shop_name: 'غرفه تست',
  scopes: 'vendor.product.write',
  created_at: now,
  updated_at: now,
};

async function expectResponsiveLayout(page: Page) {
  const metrics = await page.evaluate(() => {
    const viewport = window.innerWidth;
    const rectOf = (selector: string) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height };
    };
    const overlaps = (first: ReturnType<typeof rectOf>, second: ReturnType<typeof rectOf>) => {
      if (!first || !second) return false;
      return first.left < second.right && first.right > second.left && first.top < second.bottom && first.bottom > second.top;
    };
    const bulkInput = rectOf('.bulk-prep-box .suffix-input');
    const bulkApply = rectOf('.bulk-prep-box .prep-apply');
    const bulkClose = rectOf('.bulk-prep-box .bulk-prep-close');
    const nodes = [...document.querySelectorAll('.panel, .product-card, .bulk-prep-box')]
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          className: String((node as HTMLElement).className),
          left: rect.left,
          right: rect.right,
          width: rect.width,
        };
      })
      .filter((item) => item.width > 0);
    return {
      viewport,
      overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - viewport,
      escaped: nodes.filter((item) => item.left < -1 || item.right > viewport + 1),
      mobileMinLeft: Math.min(...nodes.map((item) => item.left)),
      mobileMaxRight: Math.max(...nodes.map((item) => item.right)),
      bulkPrep: {
        inputAndApplyOverlap: overlaps(bulkInput, bulkApply),
        closeWidth: bulkClose?.width ?? 0,
        closeHeight: bulkClose?.height ?? 0,
      },
    };
  });

  expect(metrics.overflow).toBeLessThanOrEqual(1);
  expect(metrics.escaped).toEqual([]);
  if (metrics.viewport <= 600) {
    expect(metrics.mobileMinLeft).toBeGreaterThanOrEqual(12);
    expect(metrics.mobileMaxRight).toBeLessThanOrEqual(metrics.viewport - 12);
    expect(metrics.bulkPrep.inputAndApplyOverlap).toBe(false);
    expect(metrics.bulkPrep.closeWidth).toBeGreaterThanOrEqual(34);
    expect(metrics.bulkPrep.closeHeight).toBeGreaterThanOrEqual(34);
  }
}

test('photo first flow with mocked API', async ({ page }) => {
  let uploadCall = 0;
  let savedBody: Record<string, unknown> | undefined;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7/assets', async (route) => {
    if (route.request().method() === 'POST') {
      uploadCall += 1;
      return route.fulfill({ json: uploadCall === 1 ? assets.slice(0, 2) : assets.slice(2), status: 201 });
    }
    return route.fulfill({ json: assets });
  });
  await page.route('**/batches/7/process', async (route) => route.fulfill({ json: { job_id: 30 }, status: 202 }));
  await page.route('**/jobs/30', async (route) => route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [item] }));
  await page.route('**/batches/7/categories/basalam/suggest', async (route) => route.fulfill({
    json: [{
      ...item,
      basalam_category: basalamCategory,
    }],
  }));
  await page.route('**/batch-items/101', async (route) => {
    savedBody = JSON.parse(route.request().postData() ?? '{}');
    return route.fulfill({ json: { ...item, ...savedBody, edited_by_user: true } });
  });
  await page.route('**/batch-items/split', async (route) => route.fulfill({ json: { ...item, photos: [item.photos[0]] }, status: 201 }));
  await page.route('**/batch-items/101/photos/reorder', async (route) => route.fulfill({ json: item }));

  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: /افزودن محصولات به باسلام/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /افزودن محصولات به ترب/ })).toBeVisible();
  await expect(page.getByText('عکس محصولات')).toHaveCount(0);

  await page.getByRole('button', { name: /افزودن محصولات به باسلام/ }).click();
  await expect(page.getByText('هرچی محصول داری می‌تونی عکسش رو بذاری.')).toBeVisible();
  await expect(page.getByText('بچ', { exact: true })).toHaveCount(0);
  await expect(page.getByText('انتخاب فروشنده')).toHaveCount(0);
  await expect(page.getByText('یکی کردن')).toHaveCount(0);

  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.locator('.drop-zone').click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles([
    { name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('aaa') },
    { name: 'b.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('bbb') },
  ]);
  await expect(page.getByText('۲ عکس اضافه شده')).toBeVisible();
  await expect(page.getByAltText('عکس شماره ۱')).toBeVisible();

  await expect(page.locator('input[accept="audio/*"]')).toHaveCount(0);
  await expect(page.getByText('فایل ویس')).toHaveCount(0);

  await page.getByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }).click();
  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  await expect(page.locator('.price-input input')).toHaveValue('۱۲۳٬۰۰۰');
  await expect(page.getByRole('button', { name: 'این عکس محصول جداست' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'عکس بعدی' })).toBeVisible();
  await expect(page.getByText('عکس‌های این محصول را چک کن.')).toHaveCount(0);
  await expect(page.getByText(/اطمینان/)).toHaveCount(0);

  await expect(page.locator('input[accept="image/*"]').first()).toBeDisabled();

  await page.locator('.price-input input').fill('1234567');
  await expect(page.locator('.price-input input')).toHaveValue('۱٬۲۳۴٬۵۶۷');
  await expect(page.getByLabel('موجودی')).toBeVisible();
  await expect(page.getByLabel('زمان آماده‌سازی همه محصولات')).toBeVisible();
  await expectResponsiveLayout(page);

  await page.getByRole('button', { name: /افزودن محصولات جدید/ }).click();
  await expect(page.getByRole('dialog')).toContainText('محصولات جدید اضافه می‌کنی؟');
  await page.getByRole('button', { name: 'نه، برگرد' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('processing failure keeps uploads and retries without English errors', async ({ page }) => {
  let processCall = 0;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2), status: 201 }));
  await page.route('**/batches/7/process', async (route) => {
    processCall += 1;
    return route.fulfill({ json: { job_id: processCall === 1 ? 31 : 30 }, status: 202 });
  });
  await page.route('**/jobs/31', async (route) =>
    route.fulfill({ json: { id: 31, batch_id: 7, status: 'failed', step: 'failed', error: 'AI provider timeout 503' } }),
  );
  await page.route('**/jobs/30', async (route) =>
    route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }),
  );
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [item] }));
  await page.route('**/batches/7/categories/basalam/suggest', async (route) =>
    route.fulfill({ json: [{ ...item, basalam_category: basalamCategory }] }),
  );

  await page.goto('/');
  await page.getByRole('button', { name: /افزودن محصولات به باسلام/ }).click();
  await page.locator('input[accept="image/*"]').first().setInputFiles([
    { name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('aaa') },
    { name: 'b.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('bbb') },
  ]);

  await expect(page.getByText('۲ عکس اضافه شده')).toBeVisible();
  await page.getByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }).click();

  await expect(page.getByText('ساخت لیست ناموفق بود')).toBeVisible();
  await expect(page.getByText('عکس‌ها پاک نشده‌اند. می‌توانی دوباره تلاش کنی.')).toBeVisible();
  await expect(page.getByText('ساخت لیست کامل نشد. عکس‌ها پاک نشده‌اند؛ دوباره تلاش کن.')).toBeVisible();
  await expect(page.getByText(/AI provider|timeout|503/i)).toHaveCount(0);
  await expect(page.getByText('۲ عکس اضافه شده')).toBeVisible();

  await page.getByRole('button', { name: 'دوباره تلاش کن' }).click();

  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  await expect(page.getByText('دسته‌بندی باسلام', { exact: true })).toBeVisible();
  expect(processCall).toBe(2);
});

test('Basalam and Torob keep separate upload workspaces in the browser', async ({ page }) => {
  let nextBatchId = 7;
  const createdBatchIds: number[] = [];
  const uploadBatchIds: number[] = [];

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => {
    const id = nextBatchId++;
    createdBatchIds.push(id);
    return route.fulfill({ json: { ...batch, id }, status: 201 });
  });
  await page.route(/.*\/batches\/\d+\/assets$/, async (route) => {
    const match = route.request().url().match(/\/batches\/(\d+)\/assets$/);
    const batchId = Number(match?.[1]);
    uploadBatchIds.push(batchId);
    return route.fulfill({
      json: [
        {
          ...assets[0],
          id: 100 + batchId,
          batch_id: batchId,
          url: `/files/${batchId}/image/0001.jpg`,
        },
      ],
      status: 201,
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /افزودن محصولات به باسلام/ }).click();
  await expect(page.getByText('غرفه باسلام')).toBeVisible();
  await page.locator('input[accept="image/*"]').first().setInputFiles({
    name: 'basalam.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('basalam'),
  });
  await expect(page.getByText('۱ عکس اضافه شده')).toBeVisible();

  await page.getByRole('button', { name: 'تغییر مسیر' }).click();
  await page.getByRole('button', { name: /افزودن محصولات به ترب/ }).click();
  await expect(page.getByText('فروشگاه ترب')).toBeVisible();
  await expect(page.getByText('۱ عکس اضافه شده')).toHaveCount(0);
  await expect(page.getByAltText('عکس شماره ۱')).toHaveCount(0);

  await page.locator('input[accept="image/*"]').first().setInputFiles({
    name: 'torob.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('torob'),
  });
  await expect(page.getByText('۱ عکس اضافه شده')).toBeVisible();

  expect(createdBatchIds).toEqual([7, 8]);
  expect(uploadBatchIds).toEqual([7, 8]);
});

test('Torob photo flow reaches a review request without Basalam fields', async ({ page }) => {
  let torobBody: Record<string, unknown> | undefined;
  let categorySuggestCalled = false;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2), status: 201 }));
  await page.route('**/batches/7/process', async (route) => route.fulfill({ json: { job_id: 30 }, status: 202 }));
  await page.route('**/jobs/30', async (route) => route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [item] }));
  await page.route('**/batches/7/categories/basalam/suggest', async (route) => {
    categorySuggestCalled = true;
    return route.fulfill({ json: [item] });
  });
  await page.route('**/batch-items/101', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    return route.fulfill({ json: { ...item, ...body, edited_by_user: true } });
  });
  await page.route('**/batches/7/torob-submissions', async (route) => {
    torobBody = JSON.parse(route.request().postData() ?? '{}');
    return route.fulfill({
      json: { id: 701, status: 'pending', message: 'درخواستت ثبت شد. به زودی بررسی می‌شود.' },
      status: 201,
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /افزودن محصولات به ترب/ }).click();
  await expect(page.getByText('فروشگاه ترب')).toBeVisible();
  await expect(page.getByText('غرفه باسلام')).toHaveCount(0);
  await page.getByLabel('اسم فروشگاه').fill('فروشگاه تست ترب');
  await page.getByLabel('شماره تماس').fill('09120000000');

  await page.locator('input[accept="image/*"]').first().setInputFiles([
    { name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('aaa') },
    { name: 'b.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('bbb') },
  ]);
  await page.getByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }).click();

  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  await expect(page.getByText('دسته‌بندی باسلام')).toHaveCount(0);
  await expect(page.getByLabel('موجودی')).toHaveCount(0);

  await page.getByRole('button', { name: 'ثبت درخواست ترب' }).click();

  await expect(page.getByRole('dialog')).toContainText('درخواست ترب ثبت شد');
  expect(torobBody).toEqual({ shop_name: 'فروشگاه تست ترب', contact_mobile: '09120000000' });
  expect(categorySuggestCalled).toBe(false);
});

test('Basalam connected booth flow publishes reviewed products', async ({ page }) => {
  const readyItem = { ...item, basalam_category: basalamCategory };
  let publishCalled = false;
  let lastUpdateBody: Record<string, unknown> | undefined;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [basalamConnection] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2), status: 201 }));
  await page.route('**/batches/7/process', async (route) => route.fulfill({ json: { job_id: 30 }, status: 202 }));
  await page.route('**/jobs/30', async (route) => route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [readyItem] }));
  await page.route('**/batches/7/categories/basalam/suggest', async (route) => route.fulfill({ json: [readyItem] }));
  await page.route('**/batch-items/101', async (route) => {
    lastUpdateBody = JSON.parse(route.request().postData() ?? '{}');
    return route.fulfill({ json: { ...readyItem, ...lastUpdateBody, edited_by_user: true } });
  });
  await page.route('**/batches/7/publish/basalam?**', async (route) => {
    publishCalled = true;
    return route.fulfill({ json: { job_id: 80 }, status: 202 });
  });
  await page.route('**/publish-jobs/80', async (route) => route.fulfill({
    json: { id: 80, batch_id: 7, connection_id: 501, platform: 'basalam', status: 'succeeded', step: 'ready', error: null },
  }));
  await page.route('**/batches/7/published-products', async (route) => route.fulfill({
    json: [
      {
        id: 1,
        batch_item_id: 101,
        publish_job_id: 80,
        connection_id: 501,
        platform: 'basalam',
        external_product_id: '9001',
        external_url: 'https://basalam.com/p/9001',
        status: 'published',
        error: null,
        response_metadata: {},
        created_at: now,
        updated_at: now,
      },
    ],
  }));

  await page.goto('/');
  await page.getByRole('button', { name: /افزودن محصولات به باسلام/ }).click();
  await expect(page.getByText('غرفه تست')).toBeVisible();
  await page.locator('input[accept="image/*"]').first().setInputFiles([
    { name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('aaa') },
    { name: 'b.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('bbb') },
  ]);
  await page.getByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }).click();

  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  const extraInputs = page.locator('.product-extra-fields input');
  await extraInputs.nth(0).fill('5');
  await extraInputs.nth(1).fill('2');
  await extraInputs.nth(2).fill('300');
  await extraInputs.nth(3).fill('500');
  await extraInputs.nth(4).fill('1');

  await page.getByRole('button', { name: 'ثبت در غرفه باسلام' }).click();

  await expect(page.getByText('محصول‌ها در باسلام ثبت شدند')).toBeVisible();
  await expect(page.getByText('۱ محصول با موفقیت ثبت شد.')).toBeVisible();
  expect(publishCalled).toBe(true);
  expect(lastUpdateBody).toMatchObject({
    stock: 5,
    preparation_days: 2,
    weight_grams: 300,
    package_weight_grams: 500,
    unit_quantity: 1,
  });
});

test('Basalam booth can be connected after reviewing the generated list', async ({ page }) => {
  const readyItem = { ...item, basalam_category: basalamCategory };
  let oauthSellerId: string | null = null;
  let lastUpdateBody: Record<string, unknown> | undefined;
  let oauthStarted = false;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) =>
    route.fulfill({ json: oauthStarted ? [basalamConnection] : [] }),
  );
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7', async (route) => route.fulfill({ json: batch }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2), status: 201 }));
  await page.route('**/batches/7/process', async (route) => route.fulfill({ json: { job_id: 30 }, status: 202 }));
  await page.route('**/jobs/30', async (route) =>
    route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }),
  );
  await page.route('**/batches/7/items', async (route) =>
    route.fulfill({ json: [{ ...readyItem, ...(lastUpdateBody ?? {}) }] }),
  );
  await page.route('**/batches/7/categories/basalam/suggest', async (route) => route.fulfill({ json: [readyItem] }));
  await page.route('**/batch-items/101', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    lastUpdateBody = body;
    return route.fulfill({ json: { ...readyItem, ...body, edited_by_user: true } });
  });
  await page.route('**/integrations/basalam/oauth-url?**', async (route) => {
    const url = new URL(route.request().url());
    oauthSellerId = url.searchParams.get('seller_id');
    oauthStarted = true;
    return route.fulfill({
      json: {
        configured: true,
        url: 'http://127.0.0.1:5173/?basalam_status=success&seller_id=1',
        state: 'test-state',
        error: null,
      },
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /افزودن محصولات به باسلام/ }).click();
  await page.locator('input[accept="image/*"]').first().setInputFiles([
    { name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('aaa') },
    { name: 'b.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('bbb') },
  ]);
  await page.getByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }).click();

  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  const extraInputs = page.locator('.product-extra-fields input');
  await extraInputs.nth(0).fill('5');
  await extraInputs.nth(1).fill('2');
  await extraInputs.nth(2).fill('300');
  await extraInputs.nth(3).fill('500');
  await extraInputs.nth(4).fill('1');

  await page.getByRole('button', { name: 'اتصال غرفه باسلام' }).click();

  await expect(page.getByText('غرفه تست')).toBeVisible();
  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  await expect(page.locator('.product-extra-fields input').nth(0)).toHaveValue('۵');
  await expect(page.locator('.product-extra-fields input').nth(4)).toHaveValue('۱');
  expect(await page.evaluate(() => window.localStorage.getItem('bulkadd_basalam_active_batch_id'))).toBe('7');
  expect(oauthSellerId).toBe('1');
  expect(lastUpdateBody).toMatchObject({
    stock: 5,
    preparation_days: 2,
    weight_grams: 300,
    package_weight_grams: 500,
    unit_quantity: 1,
  });
});

test('a temporary OAuth restore failure never replaces the active list with an empty batch', async ({ page }) => {
  let createdBatchCount = 0;
  let restoreAvailable = false;
  const workflowEvents: Array<Record<string, unknown>> = [];

  await page.addInitScript(() => {
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.localStorage.setItem('bulkadd_workspace_id', 'test-workspace');
    window.localStorage.setItem('bulkadd_basalam_active_batch_id', '7');
    window.localStorage.setItem(
      'bulkadd_basalam_oauth_snapshot',
      JSON.stringify({ batchId: 7, assetCount: 2, itemCount: 1 }),
    );
  });
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/observability/workflow-events', async (route) => {
    workflowEvents.push(JSON.parse(route.request().postData() ?? '{}'));
    return route.fulfill({ status: 204 });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) =>
    route.fulfill({ json: [basalamConnection] }),
  );
  await page.route('**/batches/7', async (route) => restoreAvailable
    ? route.fulfill({ json: batch })
    : route.fulfill({ status: 503, json: { detail: 'temporary restore failure' } }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2) }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [{ ...item, basalam_category: basalamCategory }] }));
  await page.route('**/batches', async (route) => {
    if (route.request().method() === 'POST') createdBatchCount += 1;
    return route.fulfill({ status: 201, json: { ...batch, id: 8 } });
  });

  await page.goto('/?basalam_status=success&seller_id=1');

  await expect(page.getByText('فهرست محصولاتت موقتاً بازیابی نشد و فهرست خالی جای آن ساخته نشد. صفحه را دوباره باز کن.')).toBeVisible();
  expect(createdBatchCount).toBe(0);
  expect(await page.evaluate(() => window.localStorage.getItem('bulkadd_basalam_active_batch_id'))).toBe('7');
  expect(workflowEvents).toContainEqual({
    event: 'basalam_oauth_restore_failed',
    stage: 'batch',
    reason: 'request_failed',
    expected_asset_count: 2,
    expected_item_count: 1,
  });
  restoreAvailable = true;
  await page.reload();
  await expect(page.getByLabel('نام محصول')).toHaveValue('محصول تستی');
  expect(createdBatchCount).toBe(0);
  expect(await page.evaluate(() => window.localStorage.getItem('bulkadd_basalam_oauth_snapshot'))).toBeNull();
});

test('an incomplete OAuth restore cannot prune locally backed up product drafts', async ({ page }) => {
  const secondDraft = {
    title: 'محصول دوم',
    description: 'توضیح دوم',
    price_toman: '200000',
    stock: '2',
    preparation_days: '1',
    weight_grams: '200',
    package_weight_grams: '300',
    unit_quantity: '1',
  };
  await page.addInitScript(({ draft }) => {
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.localStorage.setItem('bulkadd_workspace_id', 'test-workspace');
    window.localStorage.setItem('bulkadd_basalam_active_batch_id', '7');
    window.localStorage.setItem(
      'bulkadd_basalam_oauth_snapshot',
      JSON.stringify({ batchId: 7, assetCount: 2, itemCount: 2 }),
    );
    window.localStorage.setItem(
      'bulkadd_product_drafts:basalam:7',
      JSON.stringify({ drafts: { 102: draft }, touched: { 102: { title: true } } }),
    );
  }, { draft: secondDraft });
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/sellers/1/platform-connections?**', async (route) =>
    route.fulfill({ json: [basalamConnection] }),
  );
  await page.route('**/batches/7', async (route) => route.fulfill({ json: batch }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2) }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: [{ ...item, basalam_category: basalamCategory }] }));
  await page.route('**/observability/workflow-events', async (route) => route.fulfill({ status: 204 }));

  await page.goto('/?basalam_status=success&seller_id=1');

  await expect(page.getByText('بخشی از فهرست قبلی بازیابی نشد. چیزی را دوباره ثبت نکن و صفحه را تازه‌سازی کن.')).toBeVisible();
  const stored = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem('bulkadd_product_drafts:basalam:7') ?? '{}'),
  );
  expect(stored.drafts['102']).toEqual(secondDraft);
  await expect(page.getByLabel('نام محصول')).toHaveCount(0);
});

test('OAuth integrity keeps exact counts above one hundred', async ({ page }) => {
  const missingDraft = {
    title: 'محصول صد و یکم', description: '', price_toman: '1', stock: '1', preparation_days: '1',
    weight_grams: '1', package_weight_grams: '1', unit_quantity: '1',
  };
  const oneHundredItems = Array.from({ length: 100 }, (_, index) => ({
    ...item,
    id: 1000 + index,
    photos: [],
    basalam_category: basalamCategory,
  }));
  await page.addInitScript(({ draft }) => {
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.localStorage.setItem('bulkadd_workspace_id', 'test-workspace');
    window.localStorage.setItem('bulkadd_basalam_active_batch_id', '7');
    window.localStorage.setItem(
      'bulkadd_basalam_oauth_snapshot',
      JSON.stringify({ batchId: 7, assetCount: 2, itemCount: 101 }),
    );
    window.localStorage.setItem(
      'bulkadd_product_drafts:basalam:7',
      JSON.stringify({ drafts: { 9999: draft }, touched: { 9999: { title: true } } }),
    );
  }, { draft: missingDraft });
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [basalamConnection] }));
  await page.route('**/batches/7', async (route) => route.fulfill({ json: batch }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: assets.slice(0, 2) }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: oneHundredItems }));
  await page.route('**/observability/workflow-events', async (route) => route.fulfill({ status: 204 }));

  await page.goto('/?basalam_status=success&seller_id=1');

  await expect(page.getByText('بخشی از فهرست قبلی بازیابی نشد. چیزی را دوباره ثبت نکن و صفحه را تازه‌سازی کن.')).toBeVisible();
  const stored = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem('bulkadd_product_drafts:basalam:7') ?? '{}'),
  );
  expect(stored.drafts['9999']).toEqual(missingDraft);
  await expect(page.getByLabel('نام محصول')).toHaveCount(0);
});

test('Basalam reviewed product grid stays readable and multi-photo items use a carousel', async ({ page }) => {
  const manyAssets = Array.from({ length: 6 }, (_, index) => ({
    ...assets[0],
    id: 101 + index,
    upload_order: index + 1,
    original_filename: `${index + 1}.jpg`,
    url: `/files/7/image/000${index + 1}.jpg`,
  }));
  const product = (id: number, imageNumbers: number[], confidence = 0.91) => ({
    ...item,
    id,
    title: `محصول ${id}`,
    confidence,
    photos: imageNumbers.map((imageNumber, index) => ({
      asset_id: 100 + imageNumber,
      upload_order: imageNumber,
      url: `/files/7/image/000${imageNumber}.jpg`,
      role: 'product_photo',
      sort_order: index + 1,
    })),
    basalam_category: basalamCategory,
  });
  const manyItems = [
    product(201, [1, 2]),
    product(202, [3]),
    product(203, [4]),
    product(204, [5, 6], 0.52),
  ];

  await page.route('**/files/**', async (route) =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#eef3f2"/><circle cx="400" cy="300" r="90" fill="#7fb4aa"/></svg>',
    }),
  );
  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections?**', async (route) => route.fulfill({ json: [basalamConnection] }));
  await page.route('**/sellers/1', async (route) => route.fulfill({ json: seller }));
  await page.route('**/batches', async (route) => route.fulfill({ json: batch, status: 201 }));
  await page.route('**/batches/7/assets', async (route) => route.fulfill({ json: manyAssets, status: 201 }));
  await page.route('**/batches/7/process', async (route) => route.fulfill({ json: { job_id: 30 }, status: 202 }));
  await page.route('**/jobs/30', async (route) => route.fulfill({ json: { id: 30, batch_id: 7, status: 'succeeded', step: 'ready', error: null } }));
  await page.route('**/batches/7/items', async (route) => route.fulfill({ json: manyItems }));
  await page.route('**/batches/7/categories/basalam/suggest', async (route) => route.fulfill({ json: manyItems }));

  await page.goto('/');
  await page.locator('.platform-card').first().click();
  await page.locator('input[accept="image/*"]').first().setInputFiles({
    name: 'a.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('aaa'),
  });
  await page.locator('.action-button').click();
  await expect(page.locator('.product-card')).toHaveCount(4);

  const metrics = await page.evaluate(() => {
    const viewport = window.innerWidth;
    const cards = [...document.querySelectorAll('.product-card')].map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        width: rect.width,
        resultPhotos: node.querySelectorAll('.result-photo').length,
        hasGallery: node.querySelectorAll('.gallery-dots button').length > 1,
      };
    });
    return {
      viewport,
      overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - viewport,
      cards,
      splitButtons: document.querySelectorAll('.split-photo-button').length,
    };
  });

  expect(metrics.overflow).toBeLessThanOrEqual(1);
  expect(metrics.cards.every((card) => card.resultPhotos === 1)).toBe(true);
  expect(metrics.cards.filter((card) => card.hasGallery)).toHaveLength(2);
  expect(metrics.splitButtons).toBe(1);
  if (metrics.viewport >= 900) {
    expect(metrics.cards.every((card) => card.width >= 480)).toBe(true);
    expect(new Set(metrics.cards.slice(0, 2).map((card) => Math.round(card.top))).size).toBe(1);
  } else {
    expect(metrics.cards.every((card) => card.left >= 12 && card.right <= metrics.viewport - 12)).toBe(true);
    expect(new Set(metrics.cards.map((card) => Math.round(card.left))).size).toBe(1);
  }
});
