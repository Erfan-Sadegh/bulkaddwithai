import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

const now = new Date().toISOString();

const seller = {
  id: 1,
  name: 'فروشنده',
  mobile: '-',
  shop_name: 'فروشگاه',
  created_at: now,
  updated_at: now,
};

const batch = {
  id: 10,
  seller_id: 1,
  status: 'draft',
  raw_transcript: null,
  ai_metadata: null,
  created_at: now,
  updated_at: now,
};

const imageAssets = [
  {
    id: 11,
    batch_id: 10,
    type: 'image',
    upload_order: 1,
    original_filename: 'a.jpg',
    mime_type: 'image/jpeg',
    size_bytes: 3,
    checksum: 'a',
    url: '/files/10/image/0001.jpg',
    created_at: now,
  },
  {
    id: 12,
    batch_id: 10,
    type: 'image',
    upload_order: 2,
    original_filename: 'b.jpg',
    mime_type: 'image/jpeg',
    size_bytes: 3,
    checksum: 'b',
    url: '/files/10/image/0002.jpg',
    created_at: now,
  },
];

const item = {
  id: 101,
  batch_id: 10,
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
    { asset_id: 11, upload_order: 1, url: '/files/10/image/0001.jpg', role: 'product_photo', sort_order: 1 },
    { asset_id: 12, upload_order: 2, url: '/files/10/image/0002.jpg', role: 'product_photo', sort_order: 2 },
  ],
  basalam_category: null,
  created_at: now,
  updated_at: now,
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

describe('App', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('starts from photos and avoids internal product terms', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ uploadAssetCount: 1 });

    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByText('هرچی محصول داری می‌تونی عکسش رو بذاری.')).toBeInTheDocument();
    expect(await screen.findByText('عکس محصولات')).toBeInTheDocument();
    expect(screen.queryByText('بچ')).not.toBeInTheDocument();
    expect(screen.queryByText('انتخاب فروشنده')).not.toBeInTheDocument();
    expect(screen.queryByText('یکی کردن')).not.toBeInTheDocument();

    const file = new File(['aaa'], 'a.jpg', { type: 'image/jpeg' });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, file);

    expect(await screen.findByText('۱ عکس اضافه شده')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ })).toBeInTheDocument();
    expect(await screen.findByAltText('عکس شماره ۱')).toBeInTheDocument();
  });

  it('shows results, formats Persian price, and confirms starting over', async () => {
    const user = userEvent.setup();
    const updateBodies: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({ updateBodies });

    await screen.findByRole('heading', { level: 1 });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue('محصول تستی')).toBeInTheDocument();
    expect(screen.getByDisplayValue('۱۲۳٬۰۰۰')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'این عکس محصول جداست' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'عکس قبلی' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'عکس بعدی' })).toBeInTheDocument();
    expect(screen.queryByText('عکس‌های این محصول را چک کن.')).not.toBeInTheDocument();
    expect(screen.queryByText(/اطمینان/)).not.toBeInTheDocument();

    const uploadInputs = Array.from(container.querySelectorAll('input[accept="image/*"]')) as HTMLInputElement[];
    expect(uploadInputs.every((input) => input.disabled)).toBe(true);

    fireEvent.change(screen.getByDisplayValue('۱۲۳٬۰۰۰'), { target: { value: '۱۲۳۴۵۶۷' } });
    expect(screen.getByDisplayValue('۱٬۲۳۴٬۵۶۷')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /افزودن محصولات جدید/ }));
    expect(await screen.findByRole('dialog')).toHaveTextContent('محصولات جدید اضافه می‌کنی؟');
    await user.click(screen.getByRole('button', { name: 'نه، برگرد' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps files and offers retry when processing fails', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const { container } = renderWithApi({ failProcessing: true, uploadAssetCount: 1, onProcess: () => { processCalls += 1; } });

    await screen.findByRole('heading', { level: 1 });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByText('ساخت لیست ناموفق بود')).toBeInTheDocument();
    expect(screen.getByText('عکس‌ها و صدا پاک نشده‌اند. می‌توانی دوباره تلاش کنی.')).toBeInTheDocument();
    expect(screen.getByText('۱ عکس اضافه شده')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'دوباره تلاش کن' }));
    expect(processCalls).toBe(2);
  });

  it('does not show split action when grouped photos are confident', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ itemOverride: { confidence: 0.93 } });

    await screen.findByRole('heading', { level: 1 });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue('محصول تستی')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'این عکس محصول جداست' })).not.toBeInTheDocument();
    expect(screen.queryByText('عکس‌های این محصول را چک کن.')).not.toBeInTheDocument();
  });

  it('shows split action only when grouped photos are very uncertain', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ itemOverride: { confidence: 0.51 } });

    await screen.findByRole('heading', { level: 1 });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue('محصول تستی')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'این عکس محصول جداست' })).toBeInTheDocument();
    expect(screen.getByText('عکس‌های این محصول را چک کن.')).toBeInTheDocument();
  });
  it('publishes reviewed products to connected Basalam booth', async () => {
    const user = userEvent.setup();
    const updateBodies: Array<Record<string, unknown>> = [];
    let publishCalled = false;
    const { container } = renderWithApi({
      updateBodies,
      platformConnections: [basalamConnection],
      onPublish: () => {
        publishCalled = true;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(container.querySelector('.action-button') as HTMLButtonElement);
    await screen.findByDisplayValue(item.title);
    const extraInputs = container.querySelectorAll('.product-extra-fields input');
    fireEvent.change(extraInputs[0], { target: { value: '۵' } });
    fireEvent.change(extraInputs[1], { target: { value: '۲' } });
    fireEvent.change(extraInputs[2], { target: { value: '۳۰۰' } });
    fireEvent.change(extraInputs[3], { target: { value: '۵۰۰' } });
    fireEvent.change(extraInputs[4], { target: { value: '۱' } });
    await user.click(container.querySelector('.save-dock button') as HTMLButtonElement);

    await waitFor(() => expect(publishCalled).toBe(true));
    expect(updateBodies.length).toBeGreaterThan(0);
    expect(updateBodies[updateBodies.length - 1]).toMatchObject({
      stock: 5,
      preparation_days: 2,
      weight_grams: 300,
      package_weight_grams: 500,
      unit_quantity: 1,
    });
    await waitFor(() => expect(container.querySelector('.publish-status')).toBeInTheDocument());
  });
});

function renderWithApi({
  failProcessing = false,
  uploadAssetCount = 2,
  updateBodies = [],
  itemOverride = {},
  platformConnections = [],
  onProcess,
  onPublish,
}: {
  failProcessing?: boolean;
  uploadAssetCount?: number;
  updateBodies?: Array<Record<string, unknown>>;
  itemOverride?: Partial<typeof item>;
  platformConnections?: Array<typeof basalamConnection>;
  onProcess?: () => void;
  onPublish?: () => void;
} = {}) {
  const responseItem = { ...item, ...itemOverride };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = getPath(input);
      const method = init?.method ?? 'GET';

      if (path === '/sellers' && method === 'POST') return jsonResponse(seller, 201);
      if (path === '/sellers' && method === 'GET') return jsonResponse([]);
      if (path === '/sellers/1/platform-connections') return jsonResponse(platformConnections);
      if (path === '/sellers/1' && method === 'PATCH') return jsonResponse(seller);
      if (path === '/batches' && method === 'POST') return jsonResponse(batch, 201);
      if (path === '/batches/10/assets' && method === 'POST') return jsonResponse(imageAssets.slice(0, uploadAssetCount), 201);
      if (path === '/batches/10/process' && method === 'POST') {
        onProcess?.();
        return jsonResponse({ job_id: failProcessing ? 31 : 30 }, 202);
      }
      if (path === '/jobs/30') return jsonResponse({ id: 30, batch_id: 10, status: 'succeeded', step: 'ready', error: null });
      if (path === '/jobs/31') return jsonResponse({ id: 31, batch_id: 10, status: 'failed', step: 'failed', error: 'پردازش کامل نشد.' });
      if (path === '/batches/10/items') return jsonResponse([responseItem]);
      if (path === '/batches/10/categories/basalam/suggest' && method === 'POST') {
        return jsonResponse([
          {
            ...responseItem,
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
          },
        ]);
      }
      if (path === '/integrations/basalam/categories') {
        return jsonResponse([
          {
            id: 20,
            title: 'گروه شده',
            path: 'کالای دیجیتال > گروه شده',
            confidence: 0.88,
            unit_type_id: 6304,
            unit_type_title: 'عددی',
            max_preparation_days: 7,
          },
        ]);
      }
      if (path === '/batch-items/101/basalam-category' && method === 'PATCH') {
        return jsonResponse({
          ...responseItem,
          basalam_category: {
            category_id: 20,
            title: 'گروه شده',
            path: 'کالای دیجیتال > گروه شده',
            confidence: 1,
            source: 'user',
            unit_type_id: 6304,
            unit_type_title: 'عددی',
            max_preparation_days: 7,
          },
        });
      }
      if (path === '/batch-items/101' && method === 'PATCH') {
        const body = JSON.parse(String(init?.body ?? '{}'));
        updateBodies.push(body);
        return jsonResponse({ ...responseItem, ...body, edited_by_user: true });
      }
      if (path === '/batch-items/split' && method === 'POST') return jsonResponse({ ...responseItem, photos: [responseItem.photos[0]] }, 201);
      if (path === '/batch-items/101/photos/reorder' && method === 'POST') return jsonResponse(responseItem);
      if (path === '/batches/10/publish/basalam' && method === 'POST') {
        onPublish?.();
        return jsonResponse({ job_id: 80 }, 202);
      }
      if (path === '/publish-jobs/80') {
        return jsonResponse({ id: 80, batch_id: 10, connection_id: 501, platform: 'basalam', status: 'succeeded', step: 'ready', error: null });
      }
      if (path === '/batches/10/published-products') {
        return jsonResponse([
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
        ]);
      }

      return jsonResponse({});
    }),
  );
  return render(<App />);
}

function getPath(input: RequestInfo | URL) {
  const raw = input instanceof Request ? input.url : input.toString();
  return new URL(raw, 'http://127.0.0.1:8000').pathname;
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}
