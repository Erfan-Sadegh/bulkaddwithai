import type { Asset, BasalamCategory, Batch, Job, PlatformConnection, ProductItem, PublishedProduct, PublishJob, Seller } from './types';

export const API_BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(toFriendlyApiError(text, response.status));
  }
  return response.json() as Promise<T>;
}

function toFriendlyApiError(text: string, status: number): string {
  const detail = extractDetail(text);
  const normalized = detail.toLowerCase();
  if (normalized.includes('batch not found')) return 'این نوبت محصول پیدا نشد. برای اضافه کردن عکس جدید، از «افزودن محصولات جدید» استفاده کن.';
  if (normalized.includes('seller not found')) return 'اطلاعات فروشنده پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('batch item not found')) return 'این محصول پیدا نشد. صفحه را دوباره باز کن.';
  if (normalized.includes('no ready products found')) return 'هنوز محصول آماده‌ای برای ثبت وجود ندارد.';
  if (normalized.includes('basalam booth is not connected')) return 'غرفه باسلام هنوز وصل نیست.';
  if (normalized.includes('basalam category was not found')) return 'این دسته‌بندی در باسلام پیدا نشد. دسته دیگری انتخاب کن.';
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
  listSellers: () => request<Seller[]>('/sellers'),
  createSeller: (payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>('/sellers', { method: 'POST', body: JSON.stringify(payload) }),
  updateSeller: (sellerId: number, payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>(`/sellers/${sellerId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listPlatformConnections: (sellerId: number) => request<PlatformConnection[]>(`/sellers/${sellerId}/platform-connections`),
  getBasalamOAuthUrl: (sellerId: number) =>
    request<{ configured: boolean; url: string | null; state: string | null; error: string | null }>(`/integrations/basalam/oauth-url?seller_id=${sellerId}`),
  searchBasalamCategories: (query: string) =>
    request<BasalamCategory[]>(`/integrations/basalam/categories?query=${encodeURIComponent(query)}&limit=12`),
  createBatch: (sellerId: number) => request<Batch>('/batches', { method: 'POST', body: JSON.stringify({ seller_id: sellerId }) }),
  listBatches: (sellerId: number) => request<Batch[]>(`/batches?seller_id=${sellerId}`),
  uploadAssets: (batchId: number, files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append('files', file));
    return request<Asset[]>(`/batches/${batchId}/assets`, { method: 'POST', body });
  },
  listAssets: (batchId: number) => request<Asset[]>(`/batches/${batchId}/assets`),
  processBatch: (batchId: number) => request<{ job_id: number }>(`/batches/${batchId}/process`, { method: 'POST', body: JSON.stringify({}) }),
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
  publishToBasalam: (batchId: number) =>
    request<{ job_id: number }>(`/batches/${batchId}/publish/basalam`, { method: 'POST', body: JSON.stringify({}) }),
  getPublishJob: (jobId: number) => request<PublishJob>(`/publish-jobs/${jobId}`),
  listPublishedProducts: (batchId: number) => request<PublishedProduct[]>(`/batches/${batchId}/published-products`),
};
