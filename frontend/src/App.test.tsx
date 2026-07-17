import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import type { ProductBasalamCategory, ProductItem } from './lib/types';

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

const audioAsset = {
  id: 21,
  batch_id: 10,
  type: 'audio',
  upload_order: 1,
  original_filename: 'voice.webm',
  mime_type: 'audio/webm',
  size_bytes: 5,
  checksum: 'voice',
  url: '/files/10/audio/0001.webm',
  created_at: now,
};

const item: ProductItem = {
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
    window.history.pushState({}, '', '/');
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(window, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    });
    delete (window as Window & { __VOICE_NUDGE_DELAY_MS__?: number }).__VOICE_NUDGE_DELAY_MS__;
  });

  it('starts from photos and avoids internal product terms', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ uploadAssetCount: 1 });

    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /افزودن محصولات به ترب/ })).toBeInTheDocument();
    expect(screen.queryByText('عکس محصولات')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));

    expect(screen.getByText('هرچی محصول داری می‌تونی عکسش رو بذاری.')).toBeInTheDocument();
    expect(await screen.findByText('عکس محصولات')).toBeInTheDocument();
    expect(screen.getByText('غرفه باسلام')).toBeInTheDocument();
    expect(screen.queryByText('اطلاعات فروشگاه')).not.toBeInTheDocument();
    const basalamPanel = container.querySelector('.basalam-panel');
    const uploadPanel = container.querySelector('.upload-panel');
    expect(basalamPanel && uploadPanel && basalamPanel.compareDocumentPosition(uploadPanel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('بچ')).not.toBeInTheDocument();
    expect(screen.queryByText('انتخاب فروشنده')).not.toBeInTheDocument();
    expect(screen.queryByText('یکی کردن')).not.toBeInTheDocument();

    const file = new File(['aaa'], 'a.jpg', { type: 'image/jpeg' });
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, file);

    expect(await screen.findByText('۱ عکس اضافه شده')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ })).toBeInTheDocument();
    expect(await screen.findByAltText('عکس شماره ۱')).toBeInTheDocument();
  });

  it('shrinks very large photos before uploading them', async () => {
    const user = userEvent.setup();
    const uploadedFiles: File[] = [];
    const originalCreateImageBitmap = window.createImageBitmap;
    const bitmap = { width: 4200, height: 3000, close: vi.fn() } as unknown as ImageBitmap;
    Object.defineProperty(window, 'createImageBitmap', {
      configurable: true,
      value: vi.fn().mockResolvedValue(bitmap),
    });
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === 'canvas') {
        Object.defineProperty(element, 'getContext', {
          configurable: true,
          value: vi.fn(() => ({ drawImage: vi.fn() })),
        });
        Object.defineProperty(element, 'toBlob', {
          configurable: true,
          value: (callback: BlobCallback) => callback(new Blob(['small-image'], { type: 'image/jpeg' })),
        });
      }
      return element;
    });

    const { container } = renderWithApi({ uploadAssetCount: 1, uploadedFiles });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['x'.repeat(2_000_000)], 'large.png', { type: 'image/png' }),
      new File(['y'.repeat(2_000_000)], 'second.png', { type: 'image/png' }),
    ]);

    await waitFor(() => expect(uploadedFiles).toHaveLength(2));
    expect(uploadedFiles[0].name).toBe('large.jpg');
    expect(uploadedFiles[0].type).toBe('image/jpeg');
    expect(uploadedFiles[0].size).toBeLessThan(2_000_000);
    expect(uploadedFiles[1].name).toBe('second.jpg');
    expect(uploadedFiles[1].type).toBe('image/jpeg');
    expect(bitmap.close).toHaveBeenCalledTimes(2);

    Object.defineProperty(window, 'createImageBitmap', {
      configurable: true,
      value: originalCreateImageBitmap,
    });
  });

  it('keeps selected photo order when image preparation finishes out of order', async () => {
    const user = userEvent.setup();
    const uploadedFiles: File[] = [];
    const originalCreateImageBitmap = window.createImageBitmap;
    Object.defineProperty(window, 'createImageBitmap', {
      configurable: true,
      value: vi.fn(async (file: File) => {
        if (file.name === 'first.png') await new Promise((resolve) => window.setTimeout(resolve, 30));
        return { width: 4200, height: 3000, close: vi.fn() } as unknown as ImageBitmap;
      }),
    });
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === 'canvas') {
        Object.defineProperty(element, 'getContext', {
          configurable: true,
          value: vi.fn(() => ({ drawImage: vi.fn() })),
        });
        Object.defineProperty(element, 'toBlob', {
          configurable: true,
          value: (callback: BlobCallback) => callback(new Blob(['small-image'], { type: 'image/jpeg' })),
        });
      }
      return element;
    });

    const { container } = renderWithApi({ uploadAssetCount: 2, uploadedFiles });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['x'.repeat(2_000_000)], 'first.png', { type: 'image/png' }),
      new File(['y'.repeat(2_000_000)], 'second.png', { type: 'image/png' }),
    ]);

    await waitFor(() => expect(uploadedFiles.map((file) => file.name)).toEqual(['first.jpg', 'second.jpg']));

    Object.defineProperty(window, 'createImageBitmap', {
      configurable: true,
      value: originalCreateImageBitmap,
    });
  });

  it('creates a browser-local seller instead of reusing another connected seller', async () => {
    const user = userEvent.setup();
    const onCreateSeller = vi.fn();
    const onListSellers = vi.fn();
    renderWithApi({
      listedSellers: [
        {
          ...seller,
          id: 99,
          shop_name: 'غرفه ساز',
        },
      ],
      onCreateSeller,
      onListSellers,
    });

    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(onCreateSeller).toHaveBeenCalledTimes(1));
    expect(onListSellers).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('bulkadd_seller_id')).toBe('1');

    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    expect(screen.getByText('غرفه باسلام')).toBeInTheDocument();
    expect(screen.queryByText('غرفه ساز')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'اتصال غرفه' })).toBeInTheDocument();
  });

  it('shows a clear Persian message when Basalam OAuth is not configured locally', async () => {
    const user = userEvent.setup();
    renderWithApi({
      oauthResponse: {
        configured: false,
        url: null,
        state: null,
        error: 'اتصال باسلام در این محیط تنظیم نشده است.',
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.click(await screen.findByRole('button', { name: 'اتصال غرفه' }));

    expect(await screen.findByText('اتصال باسلام در این محیط تنظیم نشده است.')).toBeInTheDocument();
    expect(screen.queryByText(/503|Service Unavailable|Failed to fetch/i)).not.toBeInTheDocument();
  });

  it('shows loading and prevents duplicate requests while building the Basalam connect link', async () => {
    const user = userEvent.setup();
    const onOAuthUrl = vi.fn();
    renderWithApi({
      onOAuthUrl,
      oauthDelayMs: 80,
      oauthResponse: {
        configured: false,
        url: null,
        state: null,
        error: 'اتصال باسلام در این محیط تنظیم نشده است.',
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    const connectButton = await screen.findByRole('button', { name: 'اتصال غرفه' });

    await user.dblClick(connectButton);

    expect(connectButton).toBeDisabled();
    expect(connectButton.querySelector('.spin')).toBeInTheDocument();
    expect(await screen.findByText('اتصال باسلام در این محیط تنظیم نشده است.')).toBeInTheDocument();
    expect(onOAuthUrl).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Failed to fetch|Service Unavailable|503/i)).not.toBeInTheDocument();
  });

  it('hides raw network errors behind a Persian message', async () => {
    const user = userEvent.setup();
    renderWithApi({ failCreateBatchNetwork: true });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));

    expect(await screen.findByText('ارتباط برقرار نشد. چند لحظه بعد دوباره تلاش کن.')).toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch|NetworkError|TypeError/i)).not.toBeInTheDocument();
  });

  it('keeps Basalam and Torob upload workspaces separate', async () => {
    const user = userEvent.setup();
    const onCreateBatch = vi.fn();
    const { container } = renderWithApi({ onCreateBatch, uploadAssetCount: 1 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await waitFor(() => expect(onCreateBatch).toHaveBeenCalledTimes(1));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));
    expect(await screen.findByText('۱ عکس اضافه شده')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'تغییر مسیر' }));
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به ترب/ }));
    await waitFor(() => expect(onCreateBatch).toHaveBeenCalledTimes(2));

    expect(screen.getByText('فروشگاه ترب')).toBeInTheDocument();
    expect(screen.queryByText('۱ عکس اضافه شده')).not.toBeInTheDocument();
    expect(screen.queryByAltText('عکس شماره ۱')).not.toBeInTheDocument();
  });

  it('lets the seller delete an uploaded photo before building the list', async () => {
    const user = userEvent.setup();
    const deletedAssetIds: number[] = [];
    const { container } = renderWithApi({ uploadAssetCount: 2, deletedAssetIds });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));
    const deleteButton = (await screen.findAllByRole('button', { name: 'حذف عکس' }))[0];

    await user.click(deleteButton);

    expect(deletedAssetIds).toEqual([11]);
    await waitFor(() => expect(screen.getByAltText('عکس شماره ۱')).toBeInTheDocument());
    expect(screen.queryByAltText('عکس شماره ۲')).not.toBeInTheDocument();
  });

  it('shows a minimal loading state while photo upload is slow', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ uploadAssetCount: 1, uploadDelayMs: 80 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));

    expect(await screen.findByText('در حال آماده‌سازی عکس‌ها')).toBeInTheDocument();
    expect(await screen.findByText('۱ عکس اضافه شده')).toBeInTheDocument();
  });

  it('keeps photo upload in one pending request after rapid duplicate input changes', async () => {
    const user = userEvent.setup();
    const uploadKinds: string[] = [];
    const { container } = renderWithApi({ uploadKinds, uploadDelayMs: 80, uploadAssetCount: 1 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    const input = container.querySelector('input[accept="image/*"]') as HTMLInputElement;

    fireEvent.change(input, { target: { files: [new File(['aaa'], 'a.jpg', { type: 'image/jpeg' })] } });
    fireEvent.change(input, { target: { files: [new File(['bbb'], 'b.jpg', { type: 'image/jpeg' })] } });

    expect(await screen.findByText('در حال آماده‌سازی عکس‌ها')).toBeInTheDocument();
    await waitFor(() => expect(uploadKinds).toEqual(['image']));
    expect(await screen.findByText('۱ عکس اضافه شده')).toBeInTheDocument();
  });

  it('reports the safe lifecycle of an enabled image picker without filenames', async () => {
    const user = userEvent.setup();
    const uxEvents: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({ uxEvents, uploadAssetCount: 1 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(
      container.querySelector('input[accept="image/*"]') as HTMLInputElement,
      new File(['aaa'], 'private-name.jpg', { type: 'image/jpeg' }),
    );

    await waitFor(() => expect(uxEvents.some((event) => event.event === 'ui_action_accepted')).toBe(true));
    const pickerEvents = uxEvents.filter((event) => String(event.event).startsWith('image_'));
    expect(pickerEvents.map((event) => event.event)).toEqual(['image_picker_opened', 'image_files_selected']);
    expect(pickerEvents[0].attempt_id).toBe(pickerEvents[1].attempt_id);
    expect(pickerEvents[1].file_count).toBe(1);
    expect(uxEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ event: 'ui_action_started', control: 'photo_drop_zone' }),
        expect.objectContaining({ event: 'ui_action_accepted', control: 'photo_drop_zone' }),
      ]),
    );
    expect(JSON.stringify(uxEvents)).not.toContain('private-name.jpg');
  });

  it('forwards a safe runtime failure envelope from the mounted catalog', async () => {
    const runtimeEvents: Array<Record<string, unknown>> = [];
    renderWithApi({ runtimeEvents });
    await screen.findByRole('heading', { level: 1 });

    window.dispatchEvent(new ErrorEvent('error', { message: 'private title', filename: 'https://example.test/?token=secret' }));

    await waitFor(() => expect(runtimeEvents).toHaveLength(1));
    expect(runtimeEvents[0]).toEqual({ event: 'frontend_runtime_failed', code: 'script_error', surface: 'catalog' });
    expect(JSON.stringify(runtimeEvents)).not.toContain('private');
  });

  it('shows results, formats Persian price, and confirms starting over', async () => {
    const user = userEvent.setup();
    const updateBodies: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({ updateBodies });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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
    expect(screen.getByText('برای افزودن عکس‌های جدید، اول روی «افزودن محصولات جدید» بزن.')).toBeInTheDocument();
    window.clarity = vi.fn();
    await user.click(screen.getByText('افزودن عکس'));
    expect(window.clarity).toHaveBeenCalledWith('event', 'image_picker_blocked');
    expect(window.clarity).toHaveBeenCalledWith('set', 'reason', 'list_exists');

    fireEvent.change(screen.getByDisplayValue('۱۲۳٬۰۰۰'), { target: { value: '۱۲۳۴۵۶۷' } });
    expect(screen.getByDisplayValue('۱٬۲۳۴٬۵۶۷')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /افزودن محصولات جدید/ }));
    expect(await screen.findByRole('dialog')).toHaveTextContent('محصولات جدید اضافه می‌کنی؟');
    await user.click(screen.getByRole('button', { name: 'نه، برگرد' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('records optional voice before building the AI list', async () => {
    const user = userEvent.setup();
    const uploadKinds: string[] = [];
    const uploadedFiles: File[] = [];
    let processCalls = 0;
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeMediaRecorder {
      mimeType = 'audio/mp4';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/mp4' }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    const { container } = renderWithApi({
      uploadKinds,
      uploadedFiles,
      uploadDelayMs: 80,
      onProcess: () => {
        processCalls += 1;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await screen.findByText('۲ عکس اضافه شده');

    await user.click(screen.getByRole('button', { name: 'ضبط صدا' }));
    await user.click(await screen.findByRole('button', { name: 'توقف ضبط' }));

    expect(await screen.findByText('در حال آماده‌کردن صدا')).toBeInTheDocument();
    expect(screen.queryByText('در حال آماده‌سازی عکس‌ها')).not.toBeInTheDocument();
    expect(container.querySelector('.photo-grid .loading-tile')).not.toBeInTheDocument();
    expect(container.querySelector('.file-button .spin')).not.toBeInTheDocument();
    expect(await screen.findByText('صدا ضبط شد و آماده پردازش است.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ضبط دوباره' })).toBeInTheDocument();
    expect(uploadKinds).toEqual(['image', 'audio']);
    const recordedFile = uploadedFiles.find((file) => file.type.startsWith('audio/'));
    expect(recordedFile?.type).toBe('audio/mp4');
    expect(recordedFile?.name).toMatch(/\.m4a$/);
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stopTrack).toHaveBeenCalledTimes(1);

    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    await waitFor(() => expect(processCalls).toBe(1));
    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    expect(container.querySelector('.product-card.basalam-card')).toBeInTheDocument();
  });

  it('does not upload an empty browser recording', async () => {
    const user = userEvent.setup();
    const uploadKinds: string[] = [];
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class EmptyMediaRecorder {
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob([], { type: this.mimeType }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', EmptyMediaRecorder);
    const { container } = renderWithApi({ uploadKinds, uploadAssetCount: 1 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(
      container.querySelector('input[accept="image/*"]') as HTMLInputElement,
      new File(['image'], 'a.jpg', { type: 'image/jpeg' }),
    );
    await user.click(screen.getByRole('button', { name: 'ضبط صدا' }));
    await user.click(screen.getByRole('button', { name: 'توقف ضبط' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('صدایی ضبط نشد. دوباره ضبط کن.');
    expect(uploadKinds).toEqual(['image']);
    expect(screen.queryByText('صدا آماده است')).not.toBeInTheDocument();
  });

  it('does not show redundant copy when no voice is recorded', async () => {
    renderWithApi();

    expect(screen.queryByText('می‌توانی بدون صدا هم ادامه بدهی.')).not.toBeInTheDocument();
  });

  it('shows a Persian microphone error when voice permission is denied', async () => {
    const user = userEvent.setup();
    const getUserMedia = vi.fn(
      () =>
        new Promise((_resolve, reject) => {
          window.setTimeout(() => reject(new Error('Permission denied by browser')), 80);
        }),
    );
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    const uploadKinds: string[] = [];
    renderWithApi({ uploadKinds });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.click(screen.getByRole('button', { name: 'ضبط صدا' }));

    expect(await screen.findByRole('button', { name: 'در حال آماده‌سازی' })).toBeDisabled();
    expect(await screen.findByRole('alert')).toHaveTextContent('اجازه میکروفون داده نشد. دسترسی میکروفون را فعال کن و دوباره تلاش کن.');
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(uploadKinds).toEqual([]);
    expect(screen.queryByText(/Permission denied|browser|NotAllowedError|Failed to fetch/i)).not.toBeInTheDocument();
  });

  it('keeps files and offers retry when processing fails', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const { container } = renderWithApi({ failProcessing: true, uploadAssetCount: 1, onProcess: () => { processCalls += 1; } });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByText('ساخت لیست ناموفق بود')).toBeInTheDocument();
    expect(screen.getByText('عکس‌ها پاک نشده‌اند. می‌توانی دوباره تلاش کنی.')).toBeInTheDocument();
    expect(screen.getByText('۱ عکس اضافه شده')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'دوباره تلاش کن' }));
    expect(processCalls).toBe(2);
  });

  it('shows a running processing state while polling the AI list job', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const { container } = renderWithApi({
      onProcess: () => {
        processCalls += 1;
      },
      jobResponses: [
        { id: 30, batch_id: 10, status: 'running', step: 'vision_extracting', error: null },
        { id: 30, batch_id: 10, status: 'succeeded', step: 'ready', error: null },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    const processButton = await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ });

    await user.click(processButton);

    expect(processCalls).toBe(1);
    expect(await screen.findByText('در حال بررسی عکس‌ها')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /در حال ساخت لیست/ })).toBeDisabled();
    expect(screen.queryByText(/AI provider|timeout|503|Failed to fetch/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByDisplayValue(item.title)).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('دسته‌بندی باسلام', { exact: true })).toBeInTheDocument();
  });

  it('keeps AI list creation in one pending request after a fast double click', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const { container } = renderWithApi({
      processDelayMs: 80,
      onProcess: () => {
        processCalls += 1;
      },
      jobResponses: [
        { id: 30, batch_id: 10, status: 'running', step: 'matching', error: null },
        { id: 30, batch_id: 10, status: 'succeeded', step: 'ready', error: null },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    const processButton = await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ });

    await user.dblClick(processButton);

    await waitFor(() => expect(processCalls).toBe(1));
    expect(screen.getByRole('button', { name: /در حال ساخت لیست/ })).toBeDisabled();
    expect(screen.queryByText(/AI provider|timeout|503|Failed to fetch/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByDisplayValue(item.title)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('does not show split action when grouped photos are confident', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ itemOverride: { confidence: 0.93 } });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue('محصول تستی')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'این عکس محصول جداست' })).toBeInTheDocument();
    expect(screen.getByText('عکس‌های این محصول را چک کن.')).toBeInTheDocument();
  });

  it('blocks Basalam publish until required product info is complete', async () => {
    const user = userEvent.setup();
    let publishCalled = false;
    const uxEvents: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({
      platformConnections: [],
      uxEvents,
      onPublish: () => {
        publishCalled = true;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(container.querySelector('.action-button') as HTMLButtonElement);
    await screen.findByDisplayValue(item.title);
    const publishButton = container.querySelector('.save-dock button') as HTMLButtonElement;
    expect(publishButton).toHaveAttribute('data-observe-control', 'publish_basalam');
    await user.click(publishButton);

    expect(publishCalled).toBe(false);
    expect(await screen.findByText('اطلاعات لازم کامل نیست.')).toBeInTheDocument();
    expect(screen.getByText(/محصول نیاز به تکمیل دارد؛ اول موجودی/)).toBeInTheDocument();
    expect(container.querySelector('.product-card.needs-info')).toBeInTheDocument();
    expect(uxEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          event: 'ui_action_blocked',
          control: 'publish_basalam',
          outcome: 'validation',
          failure_field: 'stock',
        }),
      ]),
    );
  });

  it('lets the seller connect Basalam from the reviewed list', async () => {
    const user = userEvent.setup();
    const updateBodies: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({
      updateBodies,
      oauthResponse: {
        configured: false,
        url: null,
        state: null,
        error: 'اتصال باسلام در این محیط تنظیم نشده است.',
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);
    const extraInputs = container.querySelectorAll('.product-extra-fields input');
    fireEvent.change(extraInputs[0], { target: { value: '۵' } });
    fireEvent.change(extraInputs[1], { target: { value: '۲' } });
    fireEvent.change(extraInputs[2], { target: { value: '۳۰۰' } });
    fireEvent.change(extraInputs[3], { target: { value: '۵۰۰' } });
    fireEvent.change(extraInputs[4], { target: { value: '۱' } });

    await user.click(screen.getByRole('button', { name: 'اتصال غرفه باسلام' }));

    expect(await screen.findByText('اتصال باسلام در این محیط تنظیم نشده است.')).toBeInTheDocument();
    expect(updateBodies[updateBodies.length - 1]).toMatchObject({
      stock: 5,
      preparation_days: 2,
      weight_grams: 300,
      package_weight_grams: 500,
      unit_quantity: 1,
    });
    expect(window.localStorage.getItem('bulkadd_basalam_active_batch_id')).toBe('10');
  });

  it('saves edited fields when connecting from the top Basalam panel after review', async () => {
    const user = userEvent.setup();
    const updateBodies: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({
      updateBodies,
      oauthResponse: {
        configured: false,
        url: null,
        state: null,
        error: 'اتصال باسلام در این محیط تنظیم نشده است.',
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);
    const extraInputs = container.querySelectorAll('.product-extra-fields input');
    fireEvent.change(extraInputs[0], { target: { value: '۷' } });
    fireEvent.change(extraInputs[1], { target: { value: '۳' } });
    fireEvent.change(extraInputs[2], { target: { value: '۴۰۰' } });
    fireEvent.change(extraInputs[3], { target: { value: '۶۰۰' } });
    fireEvent.change(extraInputs[4], { target: { value: '۲' } });

    await user.click(screen.getByRole('button', { name: 'اتصال غرفه' }));

    expect(await screen.findByText('اتصال باسلام در این محیط تنظیم نشده است.')).toBeInTheDocument();
    expect(updateBodies[updateBodies.length - 1]).toMatchObject({
      stock: 7,
      preparation_days: 3,
      weight_grams: 400,
      package_weight_grams: 600,
      unit_quantity: 2,
    });
  });

  it('returns to the same Basalam list after OAuth callback', async () => {
    const journeyEvents: Array<Record<string, unknown>> = [];
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.localStorage.setItem('bulkadd_basalam_active_batch_id', '10');
    window.localStorage.setItem('bulkadd_basalam_oauth_snapshot', JSON.stringify({
      batchId: 10,
      assetCount: 2,
      itemCount: 1,
      journeyId: '11111111-1111-4111-8111-111111111111',
    }));
    window.history.pushState({}, '', '/?basalam_status=success&seller_id=1');

    renderWithApi({
      platformConnections: [basalamConnection],
      itemOverride: {
        stock: 5,
        preparation_days: 2,
        weight_grams: 300,
        package_weight_grams: 500,
        unit_quantity: 1,
      },
      journeyEvents,
    });

    expect(await screen.findByText('غرفه تست')).toBeInTheDocument();
    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    expect(screen.getByLabelText('موجودی')).toHaveValue('۵');
    expect(screen.queryByRole('button', { name: /افزودن محصولات به باسلام/ })).not.toBeInTheDocument();
    expect(journeyEvents).toEqual(expect.arrayContaining([
      expect.objectContaining({
        event: 'journey_step',
        journey: 'basalam_connect_restore',
        journey_id: '11111111-1111-4111-8111-111111111111',
        stage: 'restore_complete',
        outcome: 'succeeded',
        expected_item_count: 1,
        actual_item_count: 1,
      }),
    ]));
  });

  it('returns to the Basalam upload screen after OAuth when no list was active', async () => {
    const onCreateBatch = vi.fn();
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.history.pushState({}, '', '/?basalam_status=success&seller_id=1');

    renderWithApi({
      platformConnections: [basalamConnection],
      onCreateBatch,
      createdBatch: { ...batch, id: 12, seller_id: 1 },
    });

    expect(await screen.findByText('غرفه تست')).toBeInTheDocument();
    expect(screen.getByText('عکس محصولات')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /افزودن محصولات به باسلام/ })).not.toBeInTheDocument();
    expect(window.localStorage.getItem('bulkadd_basalam_active_batch_id')).toBe('12');
    expect(onCreateBatch).toHaveBeenCalledTimes(1);
  });

  it('shows a Persian error and keeps the Basalam path after failed OAuth callback', async () => {
    const onCreateBatch = vi.fn();
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.history.pushState({}, '', '/?basalam_status=failed&seller_id=1');

    renderWithApi({ onCreateBatch, createdBatch: { ...batch, id: 13, seller_id: 1 } });

    expect(await screen.findByText('اتصال غرفه باسلام انجام نشد. دوباره تلاش کن.')).toBeInTheDocument();
    expect(screen.getByText('عکس محصولات')).toBeInTheDocument();
    expect(screen.queryByText(/failed|oauth|callback|503/i)).not.toBeInTheDocument();
    expect(window.localStorage.getItem('bulkadd_basalam_active_batch_id')).toBe('13');
    expect(onCreateBatch).toHaveBeenCalledTimes(1);
  });

  it('does not restore a saved Basalam batch from another seller after OAuth', async () => {
    const onCreateBatch = vi.fn();
    window.localStorage.setItem('bulkadd_seller_id', '1');
    window.localStorage.setItem('bulkadd_basalam_active_batch_id', '10');
    window.history.pushState({}, '', '/?basalam_status=success&seller_id=1');

    renderWithApi({
      platformConnections: [basalamConnection],
      onCreateBatch,
      restoredBatch: { ...batch, seller_id: 99 },
      createdBatch: { ...batch, id: 11, seller_id: 1 },
    });

    expect(await screen.findByText('غرفه تست')).toBeInTheDocument();
    expect(await screen.findByText('عکس محصولات')).toBeInTheDocument();
    expect(screen.queryByDisplayValue(item.title)).not.toBeInTheDocument();
    expect(window.localStorage.getItem('bulkadd_basalam_active_batch_id')).toBe('11');
    expect(onCreateBatch).toHaveBeenCalledTimes(1);
  });

  it('records voice after an incomplete list and reprocesses the same batch', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeMediaRecorder {
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      onProcess: () => {
        processCalls += 1;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);
    await user.click(container.querySelector('.save-dock button') as HTMLButtonElement);

    const validationDock = await screen.findByText('اطلاعات لازم کامل نیست.');
    const dock = validationDock.closest('.dock-message') as HTMLElement;
    expect(within(dock).getByRole('button', { name: 'تکمیل فیلدها' })).toBeInTheDocument();
    expect(within(dock).queryByRole('button', { name: 'اولین مورد' })).not.toBeInTheDocument();
    await user.click(within(dock).getByRole('button', { name: 'ضبط صدا' }));
    await user.click(await within(dock).findByRole('button', { name: 'توقف ضبط' }));

    await waitFor(() => expect(within(dock).getByRole('button', { name: 'بازبینی' })).not.toBeDisabled());
    await user.click(within(dock).getByRole('button', { name: 'بازبینی' }));

    await waitFor(() => expect(processCalls).toBe(2));
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stopTrack).toHaveBeenCalledTimes(1);
  });

  it('shows a delayed voice completion sheet after a Basalam list is ready without voice', async () => {
    (window as Window & { __VOICE_NUDGE_DELAY_MS__?: number }).__VOICE_NUDGE_DELAY_MS__ = 30;
    const user = userEvent.setup();
    let processCalls = 0;
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeMediaRecorder {
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);

    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      onProcess: () => {
        processCalls += 1;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);

    expect(processCalls).toBe(1);
    expect(screen.queryByRole('dialog', { name: 'تکمیل با صدا' })).not.toBeInTheDocument();

    const sheet = await screen.findByRole('dialog', { name: 'تکمیل با صدا' });
    expect(within(sheet).getByText('با ضبط صدا راحت‌تر اطلاعات رو تکمیل کن')).toBeInTheDocument();

    await user.click(within(sheet).getByRole('button', { name: 'ضبط صدا' }));
    await user.click(await within(sheet).findByRole('button', { name: 'توقف ضبط' }));
    await waitFor(() => expect(within(sheet).getByRole('button', { name: 'بازبینی' })).not.toBeDisabled());
    await user.click(within(sheet).getByRole('button', { name: 'بازبینی' }));

    await waitFor(() => expect(processCalls).toBe(2));
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stopTrack).toHaveBeenCalledTimes(1);
  });

  it('does not show the delayed voice completion sheet for Torob', async () => {
    (window as Window & { __VOICE_NUDGE_DELAY_MS__?: number }).__VOICE_NUDGE_DELAY_MS__ = 20;
    const user = userEvent.setup();
    const { container } = renderWithApi();

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به ترب/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);

    await new Promise((resolve) => window.setTimeout(resolve, 40));

    expect(screen.queryByRole('dialog', { name: 'تکمیل با صدا' })).not.toBeInTheDocument();
  });

  it('does not nudge for voice when the Basalam list already has required fields', async () => {
    (window as Window & { __VOICE_NUDGE_DELAY_MS__?: number }).__VOICE_NUDGE_DELAY_MS__ = 20;
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      itemOverride: {
        stock: 5,
        preparation_days: 2,
        weight_grams: 300,
        package_weight_grams: 500,
        unit_quantity: 1,
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);

    await new Promise((resolve) => window.setTimeout(resolve, 40));

    expect(screen.queryByRole('dialog', { name: 'تکمیل با صدا' })).not.toBeInTheDocument();
  });

  it('keeps edited product fields when a product action refreshes items from the API', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      itemOverride: { confidence: 0.51 },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);

    const titleInput = container.querySelector('.product-title-field input') as HTMLInputElement;
    const stockInput = container.querySelector('.product-extra-fields input') as HTMLInputElement;
    await user.clear(titleInput);
    await user.type(titleInput, 'Manual title');
    await user.type(stockInput, '5');

    await user.click(container.querySelector('.split-photo-button') as HTMLButtonElement);

    await waitFor(() => expect(container.querySelector('.product-title-field input')).toHaveValue('Manual title'));
    expect((container.querySelector('.product-extra-fields input') as HTMLInputElement).value).not.toBe('');
  });

  it('does not clear edited product fields when the viewport changes', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      itemOverride: { stock: null, preparation_days: null },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue(item.title);

    const titleInput = container.querySelector('.product-title-field input') as HTMLInputElement;
    const extraInputs = container.querySelectorAll('.product-extra-fields input');
    await user.clear(titleInput);
    await user.type(titleInput, 'نامی که فروشنده نوشته');
    await user.type(extraInputs[0] as HTMLInputElement, '7');

    window.dispatchEvent(new Event('resize'));

    expect(container.querySelector('.product-title-field input')).toHaveValue('نامی که فروشنده نوشته');
    expect(extraInputs[0]).toHaveValue('۷');
  });

  it('preserves seller edits while applying AI-filled empty fields after voice reprocess', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeMediaRecorder {
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);

    const firstItem: ProductItem = { ...item, title: 'AI old title', stock: null };
    const revisedItem: ProductItem = { ...item, title: 'AI revised title', stock: 8 };
    const category = {
      category_id: 20,
      title: 'گروه شده',
      path: 'کالای دیجیتال > گروه شده',
      confidence: 0.88,
      source: 'auto',
      unit_type_id: 6304,
      unit_type_title: 'عددی',
      max_preparation_days: 7,
    };
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      listItemsResponses: [[firstItem], [revisedItem]],
      categorySuggestionResponses: [[{ ...firstItem, basalam_category: category }], [{ ...revisedItem, basalam_category: category }]],
      onProcess: () => {
        processCalls += 1;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));
    await screen.findByDisplayValue('AI old title');

    const titleInput = container.querySelector('.product-title-field input') as HTMLInputElement;
    await user.clear(titleInput);
    await user.type(titleInput, 'Manual title');
    await user.click(container.querySelector('.save-dock button') as HTMLButtonElement);

    const validationDock = await screen.findByText('اطلاعات لازم کامل نیست.');
    const dock = validationDock.closest('.dock-message') as HTMLElement;
    await user.click(within(dock).getByRole('button', { name: 'ضبط صدا' }));
    await user.click(await within(dock).findByRole('button', { name: 'توقف ضبط' }));
    await waitFor(() => expect(within(dock).getByRole('button', { name: 'بازبینی' })).not.toBeDisabled());
    await user.click(within(dock).getByRole('button', { name: 'بازبینی' }));

    await waitFor(() => expect(processCalls).toBe(2));
    expect(await screen.findByDisplayValue('Manual title')).toBeInTheDocument();
    expect((container.querySelector('.product-extra-fields input') as HTMLInputElement).value).not.toBe('');
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
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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
    const successDialog = await screen.findByRole('dialog');
    expect(successDialog).toHaveTextContent('محصول‌ها به غرفه اضافه شدند');
    await user.click(within(successDialog).getByRole('button', { name: /افزودن محصولات بعدی/ }));
    await waitFor(() => expect(screen.queryByDisplayValue(item.title)).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'عکس محصولات' })).toBeInTheDocument();
  });

  it('blocks Basalam publish when package weight exceeds three times product weight', async () => {
    const user = userEvent.setup();
    let publishCalled = false;
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      onPublish: () => {
        publishCalled = true;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(container.querySelector('.action-button') as HTMLButtonElement);
    await screen.findByDisplayValue(item.title);
    const extraInputs = container.querySelectorAll('.product-extra-fields input');
    fireEvent.change(extraInputs[0], { target: { value: '5' } });
    fireEvent.change(extraInputs[1], { target: { value: '2' } });
    fireEvent.change(extraInputs[2], { target: { value: '101' } });
    fireEvent.change(extraInputs[3], { target: { value: '304' } });
    fireEvent.change(extraInputs[4], { target: { value: '1' } });

    await user.click(container.querySelector('.save-dock button') as HTMLButtonElement);

    const validationTitle = await screen.findByText('اطلاعات لازم کامل نیست.');
    expect(validationTitle.closest('.dock-message')).toHaveTextContent('وزن با بسته‌بندی');
    expect(publishCalled).toBe(false);
  });

  it('shows a running Basalam publish state while polling the publish job', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      publishJobResponses: [
        {
          id: 80,
          batch_id: 10,
          connection_id: 501,
          platform: 'basalam',
          status: 'running',
          step: 'uploading_photos',
          error: null,
        },
        {
          id: 80,
          batch_id: 10,
          connection_id: 501,
          platform: 'basalam',
          status: 'succeeded',
          step: 'ready',
          error: null,
        },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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

    expect(await screen.findByText('در حال فرستادن عکس‌ها به باسلام')).toBeInTheDocument();
    expect(container.querySelector('.save-dock button')).toBeDisabled();
    expect(screen.queryByText(/product\(s\) failed|Basalam product create failed|Service Unavailable|Failed to fetch/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('محصول‌ها به غرفه اضافه شدند'), { timeout: 3000 });
  });

  it('ignores failed products from older Basalam publish jobs after a successful retry', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      publishJobResponse: {
        id: 80,
        batch_id: 10,
        connection_id: 501,
        platform: 'basalam',
        status: 'succeeded',
        step: 'ready',
        error: null,
      },
      publishedProductsResponse: [
        {
          id: 1,
          batch_item_id: 101,
          publish_job_id: 79,
          connection_id: 501,
          platform: 'basalam',
          external_product_id: null,
          external_url: null,
          status: 'failed',
          error: 'Basalam product create failed: 422 old failure',
          response_metadata: {},
          created_at: now,
          updated_at: now,
        },
        {
          id: 2,
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
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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

    expect(await screen.findByRole('dialog')).toHaveTextContent('محصول‌ها به غرفه اضافه شدند');
    expect(screen.queryByText('ثبت کامل انجام نشد.')).not.toBeInTheDocument();
    expect(screen.queryByText(/محصول ثبت نشد/)).not.toBeInTheDocument();
    expect(screen.queryByText(/old failure|Basalam product create failed/i)).not.toBeInTheDocument();
  });

  it('keeps Basalam publish in one pending request even after a fast double click', async () => {
    const user = userEvent.setup();
    let publishCalls = 0;
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      publishDelayMs: 80,
      onPublish: () => {
        publishCalls += 1;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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

    const publishButton = container.querySelector('.save-dock button') as HTMLButtonElement;
    await user.dblClick(publishButton);

    expect(publishButton).toBeDisabled();
    await waitFor(() => expect(publishCalls).toBe(1));
    expect(await screen.findByRole('dialog')).toHaveTextContent('محصول‌ها به غرفه اضافه شدند');
    expect(screen.queryByText(/product\(s\) failed|Basalam product create failed|Service Unavailable|Failed to fetch/i)).not.toBeInTheDocument();
  });

  it('humanizes Basalam publish failures and hides raw English errors', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      publishJobResponse: {
        id: 80,
        batch_id: 10,
        connection_id: 501,
        platform: 'basalam',
        status: 'failed',
        step: 'failed',
        error: 'Basalam product create failed: 422 product(s) failed 1',
      },
      publishedProductsResponse: [
        {
          id: 1,
          batch_item_id: 101,
          publish_job_id: 80,
          connection_id: 501,
          platform: 'basalam',
          external_product_id: null,
          external_url: null,
          status: 'failed',
          error: 'Basalam product create failed: 422 product(s) failed 1',
          response_metadata: {},
          created_at: now,
          updated_at: now,
        },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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

    expect(await screen.findByText('ثبت محصول‌ها انجام نشد')).toBeInTheDocument();
    expect(screen.getByText('۱ محصول ثبت نشد.')).toBeInTheDocument();
    const genericFailure = 'ثبت این محصول ناموفق بود. فیلدهای لازم را چک کن و دوباره تلاش کن.';
    expect(screen.getAllByText(genericFailure)).toHaveLength(2);
    expect(within(container.querySelector('.save-dock') as HTMLElement).getByText(genericFailure)).toBeInTheDocument();
    expect(screen.queryByText(/Basalam|product\(s\) failed|failed 1|422/i)).not.toBeInTheDocument();
  });

  it('explains category publish failures without saying the category was missing', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      publishJobResponse: {
        id: 80,
        batch_id: 10,
        connection_id: 501,
        platform: 'basalam',
        status: 'failed',
        step: 'failed',
        error: 'Basalam product create failed: 422 category_id is invalid',
      },
      publishedProductsResponse: [
        {
          id: 1,
          batch_item_id: 101,
          publish_job_id: 80,
          connection_id: 501,
          platform: 'basalam',
          external_product_id: null,
          external_url: null,
          status: 'failed',
          error: 'Basalam product create failed: 422 category_id is invalid',
          response_metadata: {},
          created_at: now,
          updated_at: now,
        },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
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

    const categoryError = 'باسلام این دسته‌بندی را قبول نکرد. روی «تغییر» در کارت محصول بزن و دسته نزدیک‌تر را انتخاب کن.';
    expect(await screen.findAllByText(categoryError)).toHaveLength(2);
    expect(within(container.querySelector('.save-dock') as HTMLElement).getByText(categoryError)).toBeInTheDocument();
    expect(screen.queryByText(/category_id|invalid|422|Basalam/i)).not.toBeInTheDocument();
    expect(screen.queryByText('دسته‌بندی این محصول درست نیست یا انتخاب نشده. دسته‌بندی را اصلاح کن و دوباره ثبت کن.')).not.toBeInTheDocument();
  });

  it('shows a clear Persian message when Basalam category search fails', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      failCategorySearch: true,
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(container.querySelector('.action-button') as HTMLButtonElement);
    await screen.findByDisplayValue(item.title);

    await user.click(screen.getByRole('button', { name: 'تغییر' }));
    await user.type(screen.getByLabelText('جستجوی دسته‌بندی باسلام'), 'کفش');

    expect(await screen.findByText('جستجوی دسته انجام نشد. دوباره تلاش کن.')).toBeInTheDocument();
    expect(screen.queryByText(/503|Service Unavailable|categories request failed|Failed to fetch/i)).not.toBeInTheDocument();
  });

  it('shows a neutral review note for low-confidence automatic Basalam categories', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({
      platformConnections: [basalamConnection],
      itemOverride: {
        stock: 5,
        preparation_days: 2,
        weight_grams: 300,
        package_weight_grams: 500,
        unit_quantity: 1,
      },
      categorySuggestionOverride: {
        category_id: 20,
        title: 'پنل خورشیدی و تجهیزات',
        path: 'کالای دیجیتال > باتری و منبع تغذیه > پنل خورشیدی و تجهیزات',
        confidence: 0.51,
        source: 'auto',
        unit_type_id: 6304,
        unit_type_title: 'عددی',
        max_preparation_days: 7,
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به باسلام/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(container.querySelector('.action-button') as HTMLButtonElement);

    expect(await screen.findByText('کالای دیجیتال > باتری و منبع تغذیه > پنل خورشیدی و تجهیزات')).toBeInTheDocument();
    const note = screen.getByText('دسته را چک کن؛ اگر درست است ادامه بده.');
    expect(note).toBeInTheDocument();
    expect(note).toHaveClass('category-check-note');
    expect(container.querySelector('.save-dock button')).not.toBeDisabled();
    expect(screen.queryByText('اگر دسته درست نیست، اصلاحش کن.')).not.toBeInTheDocument();
  });

  it('creates a Torob review request without touching Basalam publish flow', async () => {
    const user = userEvent.setup();
    const torobBodies: Array<Record<string, unknown>> = [];
    let categorySuggestCalled = false;
    const { container } = renderWithApi({
      torobBodies,
      torobSubmissionMessage: 'Submission created successfully. Pending admin review.',
      onCategorySuggest: () => {
        categorySuggestCalled = true;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(await screen.findByRole('button', { name: /افزودن محصولات به ترب/ }));
    expect(screen.getByText('فروشگاه ترب')).toBeInTheDocument();
    expect(screen.queryByText('غرفه باسلام')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('اسم فروشگاه'), 'فروشگاه من');
    await user.type(screen.getByLabelText('شماره تماس'), '09120000000');
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    expect(screen.queryByText('دسته‌بندی باسلام')).not.toBeInTheDocument();
    expect(categorySuggestCalled).toBe(false);

    await user.click(screen.getByRole('button', { name: 'ثبت درخواست ترب' }));

    await waitFor(() => expect(torobBodies).toHaveLength(1));
    expect(torobBodies[0]).toEqual({ shop_name: 'فروشگاه من', contact_mobile: '09120000000' });
    expect(await screen.findByRole('dialog')).toHaveTextContent('درخواست ترب ثبت شد');
    expect(screen.getByRole('dialog')).toHaveTextContent('درخواستت ثبت شد. به زودی بررسی می‌شود.');
    expect(screen.queryByText(/Submission created|Pending admin/i)).not.toBeInTheDocument();
  });

  it('keeps Torob submission in one pending request even after a fast double click', async () => {
    const user = userEvent.setup();
    const torobBodies: Array<Record<string, unknown>> = [];
    const { container } = renderWithApi({ torobBodies, torobSubmissionDelayMs: 80 });

    await screen.findByRole('heading', { level: 1 });
    await user.click(await screen.findByRole('button', { name: /افزودن محصولات به ترب/ }));
    await user.type(screen.getByLabelText('اسم فروشگاه'), 'فروشگاه من');
    await user.type(screen.getByLabelText('شماره تماس'), '09120000000');
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    const submitButton = screen.getByRole('button', { name: 'ثبت درخواست ترب' });
    await user.dblClick(submitButton);

    expect(submitButton).toBeDisabled();
    expect(submitButton.querySelector('.spin')).toBeInTheDocument();
    expect(await screen.findByRole('dialog')).toHaveTextContent('درخواست ترب ثبت شد');
    expect(torobBodies).toHaveLength(1);
    expect(torobBodies[0]).toEqual({ shop_name: 'فروشگاه من', contact_mobile: '09120000000' });
    expect(screen.queryByText(/Failed to fetch|Service Unavailable|Pending admin|Submission created/i)).not.toBeInTheDocument();
  });

  it('hides raw Torob submission errors behind a Persian message', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApi({ failTorobSubmission: true });

    await screen.findByRole('heading', { level: 1 });
    await user.click(await screen.findByRole('button', { name: /افزودن محصولات به ترب/ }));
    await user.type(screen.getByLabelText('اسم فروشگاه'), 'فروشگاه من');
    await user.type(screen.getByLabelText('شماره تماس'), '09120000000');
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'ثبت درخواست ترب' }));

    expect(await screen.findByText('درخواست انجام نشد. دوباره تلاش کن.')).toBeInTheDocument();
    expect(screen.queryByText(/Torob upstream|Service Unavailable|503|failed/i)).not.toBeInTheDocument();
  });

  it('polls Torob AI list creation without running Basalam category logic', async () => {
    const user = userEvent.setup();
    let processCalls = 0;
    let categorySuggestCalled = false;
    const { container } = renderWithApi({
      onProcess: () => {
        processCalls += 1;
      },
      onCategorySuggest: () => {
        categorySuggestCalled = true;
      },
      jobResponses: [
        { id: 30, batch_id: 10, status: 'running', step: 'matching', error: null },
        { id: 30, batch_id: 10, status: 'succeeded', step: 'ready', error: null },
      ],
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(await screen.findByRole('button', { name: /افزودن محصولات به ترب/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, [
      new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['bbb'], 'b.jpg', { type: 'image/jpeg' }),
    ]);
    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    expect(processCalls).toBe(1);
    expect(await screen.findByText('در حال ساخت لیست محصولات')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /در حال ساخت لیست/ })).toBeDisabled();
    expect(screen.queryByText(/AI provider|timeout|503|Failed to fetch/i)).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByDisplayValue(item.title)).toBeInTheDocument(), { timeout: 3000 });
    expect(categorySuggestCalled).toBe(false);
    expect(screen.queryByText('دسته‌بندی باسلام')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('موجودی')).not.toBeInTheDocument();
  });

  it('lets Torob sellers add voice before AI list without running Basalam category logic', async () => {
    const user = userEvent.setup();
    const uploadKinds: string[] = [];
    let categorySuggestCalled = false;
    let processCalls = 0;
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeMediaRecorder {
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void | Promise<void>) | null = null;

      start() {
        this.ondataavailable?.({ data: new Blob(['torob voice'], { type: 'audio/webm' }) } as BlobEvent);
      }

      stop() {
        void this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    const { container } = renderWithApi({
      uploadAssetCount: 1,
      uploadKinds,
      onProcess: () => {
        processCalls += 1;
      },
      onCategorySuggest: () => {
        categorySuggestCalled = true;
      },
    });

    await screen.findByRole('heading', { level: 1 });
    await user.click(screen.getByRole('button', { name: /افزودن محصولات به ترب/ }));
    await user.upload(container.querySelector('input[accept="image/*"]') as HTMLInputElement, new File(['aaa'], 'a.jpg', { type: 'image/jpeg' }));
    await screen.findByText('۱ عکس اضافه شده');

    await user.click(screen.getByRole('button', { name: 'ضبط صدا' }));
    await user.click(await screen.findByRole('button', { name: 'توقف ضبط' }));

    expect(await screen.findByText('صدا ضبط شد و آماده پردازش است.')).toBeInTheDocument();
    expect(uploadKinds).toEqual(['image', 'audio']);
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stopTrack).toHaveBeenCalled();

    await user.click(await screen.findByRole('button', { name: /ساخت لیست محصولات با هوش مصنوعی/ }));

    await waitFor(() => expect(processCalls).toBe(1));
    expect(await screen.findByDisplayValue(item.title)).toBeInTheDocument();
    expect(categorySuggestCalled).toBe(false);
    expect(screen.queryByText('دسته‌بندی باسلام')).not.toBeInTheDocument();
  });
});

function renderWithApi({
  failProcessing = false,
  uploadAssetCount = 2,
  updateBodies = [],
  itemOverride = {},
  categorySuggestionOverride,
  listItemsResponses,
  categorySuggestionResponses,
  platformConnections = [],
  onProcess,
  onPublish,
  onCategorySuggest,
  jobResponses,
  processDelayMs = 0,
  failCategorySearch = false,
  torobBodies = [],
  listedSellers = [],
  onCreateSeller,
  onListSellers,
  onCreateBatch,
  onOAuthUrl,
  oauthResponse,
  oauthDelayMs = 0,
  failCreateBatchNetwork,
  publishJobResponse,
  publishJobResponses,
  publishedProductsResponse,
  publishDelayMs = 0,
  uploadKinds,
  uploadedFiles,
  deletedAssetIds,
  uploadDelayMs = 0,
  torobSubmissionMessage = 'درخواستت ثبت شد. به زودی بررسی می‌شود.',
  failTorobSubmission = false,
  torobSubmissionDelayMs = 0,
  restoredBatch = batch,
  createdBatch = batch,
  uxEvents,
  runtimeEvents,
  journeyEvents,
}: {
  failProcessing?: boolean;
  uploadAssetCount?: number;
  updateBodies?: Array<Record<string, unknown>>;
  itemOverride?: Partial<typeof item>;
  categorySuggestionOverride?: ProductBasalamCategory;
  listItemsResponses?: ProductItem[][];
  categorySuggestionResponses?: ProductItem[][];
  platformConnections?: Array<typeof basalamConnection>;
  onProcess?: () => void;
  onPublish?: () => void;
  onCategorySuggest?: () => void;
  jobResponses?: Array<Record<string, unknown>>;
  processDelayMs?: number;
  failCategorySearch?: boolean;
  torobBodies?: Array<Record<string, unknown>>;
  listedSellers?: Array<typeof seller>;
  onCreateSeller?: () => void;
  onListSellers?: () => void;
  onCreateBatch?: () => void;
  onOAuthUrl?: () => void;
  oauthResponse?: Record<string, unknown>;
  oauthDelayMs?: number;
  failCreateBatchNetwork?: boolean;
  publishJobResponse?: Record<string, unknown>;
  publishJobResponses?: Array<Record<string, unknown>>;
  publishedProductsResponse?: Array<Record<string, unknown>>;
  publishDelayMs?: number;
  uploadKinds?: string[];
  uploadedFiles?: File[];
  deletedAssetIds?: number[];
  uploadDelayMs?: number;
  torobSubmissionMessage?: string;
  failTorobSubmission?: boolean;
  torobSubmissionDelayMs?: number;
  restoredBatch?: typeof batch;
  createdBatch?: typeof batch;
  uxEvents?: Array<Record<string, unknown>>;
  runtimeEvents?: Array<Record<string, unknown>>;
  journeyEvents?: Array<Record<string, unknown>>;
} = {}) {
  const responseItem = { ...item, ...itemOverride };
  let jobResponseIndex = 0;
  let listItemsResponseIndex = 0;
  let categorySuggestionResponseIndex = 0;
  let publishJobResponseIndex = 0;
  let availableImageAssets = imageAssets.slice(0, uploadAssetCount);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = getPath(input);
      const method = init?.method ?? 'GET';

      if (path === '/observability/ux-events' && method === 'POST') {
        uxEvents?.push(JSON.parse(String(init?.body ?? '{}')));
        return new Response(null, { status: 204 });
      }
      if (path === '/observability/runtime-events' && method === 'POST') {
        runtimeEvents?.push(JSON.parse(String(init?.body ?? '{}')));
        return new Response(null, { status: 204 });
      }
      if (path === '/observability/journey-events' && method === 'POST') {
        journeyEvents?.push(JSON.parse(String(init?.body ?? '{}')));
        return new Response(null, { status: 204 });
      }

      if (path === '/sellers' && method === 'POST') {
        onCreateSeller?.();
        return jsonResponse(seller, 201);
      }
      if (path === '/sellers' && method === 'GET') {
        onListSellers?.();
        return jsonResponse(listedSellers);
      }
      if (path === '/sellers/1/platform-connections') return jsonResponse(platformConnections);
      if (path === '/sellers/1' && method === 'GET') return jsonResponse(seller);
      if (path === '/sellers/1' && method === 'PATCH') return jsonResponse(seller);
      if (path === '/integrations/basalam/oauth-url') {
        onOAuthUrl?.();
        if (oauthDelayMs > 0) await new Promise((resolve) => window.setTimeout(resolve, oauthDelayMs));
        return jsonResponse(
          oauthResponse ?? {
            configured: false,
            url: null,
            state: null,
            error: 'اتصال باسلام در این محیط تنظیم نشده است.',
          },
        );
      }
      if (path === '/batches' && method === 'POST') {
        onCreateBatch?.();
        if (failCreateBatchNetwork) throw new TypeError('Failed to fetch');
        return jsonResponse(createdBatch, 201);
      }
      if (path === '/batches/10' && method === 'GET') return jsonResponse(restoredBatch);
      if (path === '/batches/10/assets' && method === 'GET') return jsonResponse(availableImageAssets);
      if (path === '/batches/10/assets' && method === 'POST') {
        const files = init?.body instanceof FormData ? init.body.getAll('files') : [];
        const hasAudio = files.some((file) => file instanceof File && file.type.startsWith('audio/'));
        uploadedFiles?.push(...files.filter((file): file is File => file instanceof File));
        uploadKinds?.push(hasAudio ? 'audio' : 'image');
        if (uploadDelayMs > 0) await new Promise((resolve) => window.setTimeout(resolve, uploadDelayMs));
        if (!hasAudio) availableImageAssets = imageAssets.slice(0, uploadAssetCount);
        return jsonResponse(hasAudio ? [audioAsset] : availableImageAssets, 201);
      }
      if (path.startsWith('/assets/') && method === 'DELETE') {
        const assetId = Number(path.split('/').pop());
        deletedAssetIds?.push(assetId);
        availableImageAssets = availableImageAssets
          .filter((asset) => asset.id !== assetId)
          .map((asset, index) => ({ ...asset, upload_order: index + 1 }));
        return new Response(null, { status: 204 });
      }
      if (path === '/batches/10/process' && method === 'POST') {
        onProcess?.();
        if (processDelayMs > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, processDelayMs));
        }
        return jsonResponse({ job_id: failProcessing ? 31 : 30 }, 202);
      }
      if (path === '/jobs/30') {
        if (jobResponses) {
          const response = jobResponses[Math.min(jobResponseIndex, jobResponses.length - 1)];
          jobResponseIndex += 1;
          return jsonResponse(response);
        }
        return jsonResponse({ id: 30, batch_id: 10, status: 'succeeded', step: 'ready', error: null });
      }
      if (path === '/jobs/31') return jsonResponse({ id: 31, batch_id: 10, status: 'failed', step: 'failed', error: 'پردازش کامل نشد.' });
      if (path === '/batches/10/items') {
        if (listItemsResponses) {
          const response = listItemsResponses[Math.min(listItemsResponseIndex, listItemsResponses.length - 1)];
          listItemsResponseIndex += 1;
          return jsonResponse(response);
        }
        return jsonResponse([responseItem]);
      }
      if (path === '/batches/10/categories/basalam/suggest' && method === 'POST') {
        onCategorySuggest?.();
        if (categorySuggestionResponses) {
          const response = categorySuggestionResponses[Math.min(categorySuggestionResponseIndex, categorySuggestionResponses.length - 1)];
          categorySuggestionResponseIndex += 1;
          return jsonResponse(response);
        }
        return jsonResponse([
          {
            ...responseItem,
            basalam_category: categorySuggestionOverride ?? {
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
        if (failCategorySearch) {
          return jsonResponse({ detail: 'Basalam categories request failed: 503 Service Unavailable' }, 503);
        }
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
        if (publishDelayMs > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, publishDelayMs));
        }
        return jsonResponse({ job_id: 80 }, 202);
      }
      if (path === '/publish-jobs/80') {
        if (publishJobResponses) {
          const response = publishJobResponses[Math.min(publishJobResponseIndex, publishJobResponses.length - 1)];
          publishJobResponseIndex += 1;
          return jsonResponse(response);
        }
        return jsonResponse(
          publishJobResponse ?? {
            id: 80,
            batch_id: 10,
            connection_id: 501,
            platform: 'basalam',
            status: 'succeeded',
            step: 'ready',
            error: null,
          },
        );
      }
      if (path === '/batches/10/published-products') {
        return jsonResponse(
          publishedProductsResponse ?? [
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
        );
      }
      if (path === '/batches/10/torob-submissions' && method === 'POST') {
        const body = JSON.parse(String(init?.body ?? '{}'));
        torobBodies.push(body);
        if (torobSubmissionDelayMs > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, torobSubmissionDelayMs));
        }
        if (failTorobSubmission) {
          return jsonResponse({ detail: 'Torob upstream failed 503' }, 503);
        }
        return jsonResponse({ id: 701, status: 'pending', message: torobSubmissionMessage }, 201);
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
