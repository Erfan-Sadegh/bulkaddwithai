import type { Asset, Batch, Job, ProductItem, Seller } from './types';

export const API_BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listSellers: () => request<Seller[]>('/sellers'),
  createSeller: (payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>('/sellers', { method: 'POST', body: JSON.stringify(payload) }),
  updateSeller: (sellerId: number, payload: Partial<Pick<Seller, 'name' | 'mobile' | 'shop_name'>>) =>
    request<Seller>(`/sellers/${sellerId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
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
  updateItem: (itemId: number, payload: Partial<Pick<ProductItem, 'title' | 'description' | 'price_toman'>>) =>
    request<ProductItem>(`/batch-items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  mergeItems: (sourceItemIds: number[]) =>
    request<ProductItem>('/batch-items/merge', { method: 'POST', body: JSON.stringify({ source_item_ids: sourceItemIds }) }),
  splitItem: (itemId: number, assetIds: number[]) =>
    request<ProductItem>('/batch-items/split', { method: 'POST', body: JSON.stringify({ item_id: itemId, asset_ids: assetIds }) }),
  reorderPhotos: (itemId: number, assetIds: number[]) =>
    request<ProductItem>(`/batch-items/${itemId}/photos/reorder`, { method: 'POST', body: JSON.stringify({ asset_ids: assetIds }) }),
};
