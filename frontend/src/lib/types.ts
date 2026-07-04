export type Seller = {
  id: number;
  name: string;
  mobile: string;
  shop_name: string;
  created_at: string;
  updated_at: string;
};

export type Batch = {
  id: number;
  seller_id: number;
  status: string;
  raw_transcript: string | null;
  ai_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type Asset = {
  id: number;
  batch_id: number;
  type: 'image' | 'audio';
  upload_order: number;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  checksum: string;
  url: string;
  created_at: string;
};

export type Job = {
  id: number;
  batch_id: number;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  step: 'upload_ready' | 'transcribing' | 'vision_extracting' | 'matching' | 'ready' | 'failed';
  error: string | null;
};

export type ProductPhoto = {
  asset_id: number;
  upload_order: number;
  url: string;
  role: string;
  sort_order: number;
};

export type ProductItem = {
  id: number;
  batch_id: number;
  title: string;
  description: string;
  price_toman: number | null;
  confidence: number;
  edited_by_user: boolean;
  photos: ProductPhoto[];
  created_at: string;
  updated_at: string;
};
