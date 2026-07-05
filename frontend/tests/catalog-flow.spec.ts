import { expect, test } from '@playwright/test';

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

test('photo first flow with mocked API', async ({ page }) => {
  let uploadCall = 0;
  let savedBody: Record<string, unknown> | undefined;

  await page.route('**/sellers', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: seller, status: 201 });
    return route.fulfill({ json: [] });
  });
  await page.route('**/sellers/1/platform-connections', async (route) => route.fulfill({ json: [] }));
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
      basalam_category: {
        category_id: 20,
        title: 'گروه شده',
        path: 'کالای دیجیتال > گروه شده',
        confidence: 0.88,
        source: 'auto',
        unit_type_id: 6304,
        unit_type_title: 'عددی',
        max_preparation_days: 7,
      },
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
  await expect(page.getByText('هرچی محصول داری می‌تونی عکسش رو بذاری.')).toBeVisible();
  await expect(page.getByText('بچ', { exact: true })).toHaveCount(0);
  await expect(page.getByText('انتخاب فروشنده')).toHaveCount(0);
  await expect(page.getByText('یکی کردن')).toHaveCount(0);

  await page.locator('input[accept="image/*"]').first().setInputFiles([
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
  await expect(page.getByRole('button', { name: 'این یک محصول جداست' }).first()).toBeVisible();
  await expect(page.getByText('عکس‌های این محصول را چک کن.')).toBeVisible();
  await expect(page.getByText(/اطمینان/)).toHaveCount(0);

  await page.locator('.price-input input').fill('1234567');
  await expect(page.locator('.price-input input')).toHaveValue('۱٬۲۳۴٬۵۶۷');
  await expect(page.getByLabel('موجودی')).toBeVisible();
  await expect(page.getByLabel('زمان آماده‌سازی همه محصولات')).toBeVisible();

  await page.getByRole('button', { name: /افزودن محصولات جدید/ }).click();
  await expect(page.getByRole('dialog')).toContainText('محصولات جدید اضافه می‌کنی؟');
  await page.getByRole('button', { name: 'نه، برگرد' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
