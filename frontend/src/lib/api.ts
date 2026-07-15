import type {
  Asset,
  BasalamCategory,
  Batch,
  Job,
  PlatformConnection,
  ProductItem,
  PublishedProduct,
  PublishJob,
  Seller,
  TorobSubmission,
} from './types';
import { captureApiFailure, getRequestId, trackEvent } from './telemetry';

export const API_BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const requestId = getRequestId();
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers:
        init?.body instanceof FormData
          ? { 'X-Request-ID': requestId, ...init.headers }
          : { 'Content-Type': 'application/json', 'X-Request-ID': requestId, ...init?.headers },
    });
  } catch {
    captureApiFailure(path, null, requestId);
    throw new Error('ارتباط برقرار نشد. چند لحظه بعد دوباره تلاش کن.');
  }
  if (!response.ok) {
    const text = await response.text();
    if (response.status >= 500) captureApiFailure(path, response.status, response.headers.get('X-Request-ID'));
    throw new Error(toFriendlyApiError(text, response.status));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function toFriendlyApiError(text: string, status: number): string {
  const detail = extractDetail(text);
  const normalized = detail.toLowerCase();
  if (normalized.includes('batch not found')) return 'این نوبت محصول پیدا نشد. برای اضافه کردن عکس جدید، از «افزودن محصولات جدید» استفاده کن.';
  if (normalized.includes('seller not found')) return 'اطلاعات فروشنده پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('batch item not found')) return 'این محصول پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('asset not found')) return 'این عکس پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('asset is already attached to a product')) return 'این عکس داخل لیست محصول استفاده شده و از اینجا حذف نمی‌شود.';
  if (normalized.includes('no ready products found')) return 'هنوز محصول آماده‌ای برای ثبت وجود ندارد.';
  if (normalized.includes('at least one product image is required')) return 'برای ساخت لیست، اول حداقل یک عکس محصول اضافه کن.';
  if (normalized.includes('basalam booth is not connected')) return 'غرفه باسلام هنوز وصل نیست.';
  if (normalized.includes('status') && (normalized.includes('invalid') || detail.includes('نامعتبر'))) {
    return 'ثبت محصول در باسلام انجام نشد. دوباره تلاش کن.';
  }
  if (normalized.includes('basalam category was not found')) return 'این دسته‌بندی در باسلام پیدا نشد. دسته دیگری انتخاب کن.';
  if (normalized.includes('only image and audio uploads are supported')) return 'فقط عکس و صدای ضبط‌شده قابل اضافه کردن است.';
  if (normalized.includes('one or more items were not found')) return 'یکی از محصول‌ها پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('torob submission not found')) return 'درخواست ترب پیدا نشد. صفحه را دوباره باز کن.';
  if (detail && !/[{}[\]":]/.test(detail) && !/[A-Za-z]{3,}/.test(detail)) return detail;
  if (status === 404) return 'مورد موردنظر پیدا نشد. صفحه را دوباره باز کن.';
  if (status === 422) return 'یکی از اطلاعات لازم کامل نیست. فیلدها را چک کن.';
  return 'درخواست انجام نشد. دوباره تلاش کن.';
}

function extractDetail(text: string): string {
  if (!text) return '';
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === 'string') return parsed.detail;
    if (Array.isArray(parsed?.detail)) {
      return parsed.detail
        .map((item: { msg?: string }) => item?.msg)
        .filter(Boolean)
        .join('، ');
    }
  } catch {
    return text;
  }
  return text;
}

export const api = {
  reportUxEvent: (payload: {
      event:
        | 'image_picker_blocked'
        | 'image_picker_opened'
        | 'image_files_selected'
        | 'image_picker_cancelled'
        | 'ui_rage_click'
        | 'ui_action_started'
        | 'ui_action_accepted'
        | 'ui_action_blocked'
        | 'ui_action_failed';
    control:
      | 'photo_drop_zone'
      | 'add_photo_button'
      | 'build_product_list'
      | 'publish_basalam'
      | 'submit_torob'
      | 'connect_basalam'
      | 'record_voice'
      | 'change_platform'
      | 'delete_photo'
      | 'split_photo'
      | 'start_new_products';
    reason?: 'list_exists' | 'processing';
    attempt_id?: string;
    file_count?: number;
      click_count?: number;
      outcome?: 'validation' | 'state' | 'network' | 'server' | 'unknown';
  }) => request<void>('/observability/ux-events', { method: 'POST', body: JSON.stringify(payload) }),
  reportRuntimeEvent: (payload: {
    event: 'frontend_runtime_failed';
    code: 'script_error' | 'unhandled_rejection';
    surface: 'catalog' | 'admin';
  }) => request<void>('/observability/runtime-events', { method: 'POST', body: JSON.stringify(payload) }),
  listSellers: () => request<Seller[]>('/sellers'),
  getSeller: (sellerId: number) => request<Seller>(`/sellers/${sellerId}`),
  createSeller: (payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>('/sellers', { method: 'POST', body: JSON.stringify(payload) }),
  updateSeller: (sellerId: number, payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>(`/sellers/${sellerId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listPlatformConnections: (sellerId: number, workspaceId?: string) =>
    request<PlatformConnection[]>(`/sellers/${sellerId}/platform-connections${queryString({ workspace_id: workspaceId })}`),
  getBasalamOAuthUrl: (sellerId: number, workspaceId?: string) =>
    request<{ configured: boolean; url: string | null; state: string | null; error: string | null }>(
      `/integrations/basalam/oauth-url${queryString({ seller_id: sellerId, workspace_id: workspaceId })}`,
    ),
  searchBasalamCategories: (query: string) =>
    request<BasalamCategory[]>(`/integrations/basalam/categories?query=${encodeURIComponent(query)}&limit=12`),
  createBatch: (sellerId: number) => request<Batch>('/batches', { method: 'POST', body: JSON.stringify({ seller_id: sellerId }) }),
  listBatches: (sellerId: number) => request<Batch[]>(`/batches?seller_id=${sellerId}`),
  getBatch: (batchId: number) => request<Batch>(`/batches/${batchId}`),
  uploadAssets: (batchId: number, files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append('files', file));
    return request<Asset[]>(`/batches/${batchId}/assets`, { method: 'POST', body }).then((assets) => {
      trackEvent('images_uploaded', { platform: 'workspace', asset_count: assets.length });
      return assets;
    });
  },
  listAssets: (batchId: number) => request<Asset[]>(`/batches/${batchId}/assets`),
  deleteAsset: (assetId: number) => request<void>(`/assets/${assetId}`, { method: 'DELETE' }),
  processBatch: (batchId: number) =>
    request<{ job_id: number }>(`/batches/${batchId}/process`, { method: 'POST', body: JSON.stringify({}) }).then((result) => {
      trackEvent('processing_job_started', { operation: 'ai_list' });
      return result;
    }),
  getJob: (jobId: number) => request<Job>(`/jobs/${jobId}`),
  listItems: (batchId: number) => request<ProductItem[]>(`/batches/${batchId}/items`),
  suggestBasalamCategories: (batchId: number) =>
    request<ProductItem[]>(`/batches/${batchId}/categories/basalam/suggest`, { method: 'POST', body: JSON.stringify({}) }),
  updateItem: (
    itemId: number,
    payload: Partial<
      Pick<
        ProductItem,
        | 'title'
        | 'description'
        | 'price_toman'
        | 'stock'
        | 'preparation_days'
        | 'weight_grams'
        | 'package_weight_grams'
        | 'unit_quantity'
      >
    >,
  ) =>
    request<ProductItem>(`/batch-items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  setBasalamCategory: (itemId: number, categoryId: number) =>
    request<ProductItem>(`/batch-items/${itemId}/basalam-category`, { method: 'PATCH', body: JSON.stringify({ category_id: categoryId }) }),
  mergeItems: (sourceItemIds: number[]) =>
    request<ProductItem>('/batch-items/merge', { method: 'POST', body: JSON.stringify({ source_item_ids: sourceItemIds }) }),
  splitItem: (itemId: number, assetIds: number[]) =>
    request<ProductItem>('/batch-items/split', { method: 'POST', body: JSON.stringify({ item_id: itemId, asset_ids: assetIds }) }),
  reorderPhotos: (itemId: number, assetIds: number[]) =>
    request<ProductItem>(`/batch-items/${itemId}/photos/reorder`, { method: 'POST', body: JSON.stringify({ asset_ids: assetIds }) }),
  publishToBasalam: (batchId: number, workspaceId?: string) =>
    request<{ job_id: number }>(`/batches/${batchId}/publish/basalam${queryString({ workspace_id: workspaceId })}`, {
      method: 'POST',
      body: JSON.stringify({}),
    }).then((result) => {
      trackEvent('basalam_publish_started', { platform: 'basalam' });
      return result;
    }),
  getPublishJob: (jobId: number) => request<PublishJob>(`/publish-jobs/${jobId}`),
  listPublishedProducts: (batchId: number) => request<PublishedProduct[]>(`/batches/${batchId}/published-products`),
  createTorobSubmission: (batchId: number, payload: { shop_name: string; contact_mobile: string }) =>
    request<{ id: number; status: string; message: string }>(`/batches/${batchId}/torob-submissions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }).then((result) => {
      trackEvent('torob_submission_created', { platform: 'torob' });
      return result;
    }),
  adminLogin: (password: string) =>
    request<{ ok: boolean }>('/admin/login', { method: 'POST', body: JSON.stringify({ password }) }),
  listTorobSubmissions: (password: string) =>
    request<TorobSubmission[]>('/admin/torob-submissions', { headers: { 'X-Admin-Password': password } }),
  patchTorobSubmission: (
    password: string,
    submissionId: number,
    payload: {
      shop_id?: number | null;
      admin_note?: string | null;
      items?: Array<{ id: number; base_product_rk?: string | null; price?: number | null }>;
    },
  ) =>
    request<TorobSubmission>(`/admin/torob-submissions/${submissionId}`, {
      method: 'PATCH',
      headers: { 'X-Admin-Password': password },
      body: JSON.stringify(payload),
    }),
  publishTorobSubmission: (
    password: string,
    submissionId: number,
    payload: { shop_id: number; items: Array<{ id: number; base_product_rk: string; price: number }> },
  ) =>
    request<TorobSubmission>(`/admin/torob-submissions/${submissionId}/publish`, {
      method: 'POST',
      headers: { 'X-Admin-Password': password },
      body: JSON.stringify(payload),
    }),
};

function queryString(params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}
