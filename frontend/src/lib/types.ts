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
  stock: number | null;
  preparation_days: number | null;
  weight_grams: number | null;
  package_weight_grams: number | null;
  unit_quantity: number | null;
  confidence: number;
  edited_by_user: boolean;
  photos: ProductPhoto[];
  basalam_category: ProductBasalamCategory | null;
  created_at: string;
  updated_at: string;
};

export type ProductBasalamCategory = {
  category_id: number | null;
  title: string | null;
  path: string | null;
  confidence: number | null;
  source: 'auto' | 'user' | string | null;
  unit_type_id: number | null;
  unit_type_title: string | null;
  max_preparation_days: number | null;
};

export type BasalamCategory = {
  id: number;
  title: string;
  path: string;
  unit_type_id: number | null;
  unit_type_title: string | null;
  max_preparation_days: number | null;
  confidence: number | null;
};

export type PlatformConnection = {
  id: number;
  seller_id: number;
  platform: 'basalam' | string;
  status: string;
  external_user_id: string | null;
  external_shop_id: string;
  external_shop_slug: string | null;
  external_shop_name: string;
  scopes: string | null;
  created_at: string;
  updated_at: string;
};

export type PublishJob = {
  id: number;
  batch_id: number;
  connection_id: number;
  platform: string;
  status: 'queued' | 'running' | 'succeeded' | 'partial_failed' | 'failed';
  step: 'uploading_photos' | 'creating_products' | 'ready' | 'failed';
  error: string | null;
};

export type PublishedProduct = {
  id: number;
  batch_item_id: number;
  publish_job_id: number;
  connection_id: number;
  platform: string;
  external_product_id: string | null;
  external_url: string | null;
  status: 'pending' | 'published' | 'failed';
  error: string | null;
  response_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};
