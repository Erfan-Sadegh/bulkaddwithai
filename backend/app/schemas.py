from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SellerCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    mobile: str | None = Field(default=None, max_length=32)
    shop_name: str | None = Field(default=None, max_length=180)


class SellerRead(SellerCreate):
    id: int
    name: str
    mobile: str
    shop_name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SellerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    mobile: str | None = Field(default=None, max_length=32)
    shop_name: str | None = Field(default=None, max_length=180)


class BatchCreate(BaseModel):
    seller_id: int


class BatchRead(BaseModel):
    id: int
    seller_id: int
    status: str
    raw_transcript: str | None = None
    ai_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssetRead(BaseModel):
    id: int
    batch_id: int
    type: str
    upload_order: int
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobRead(BaseModel):
    id: int
    batch_id: int
    status: str
    step: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchItemAssetRead(BaseModel):
    asset_id: int
    upload_order: int
    url: str
    role: str
    sort_order: int


class BasalamCategoryRead(BaseModel):
    id: int
    title: str
    path: str
    unit_type_id: int | None = None
    unit_type_title: str | None = None
    max_preparation_days: int | None = None
    confidence: float | None = None


class BatchItemBasalamCategoryRead(BaseModel):
    category_id: int | None = None
    title: str | None = None
    path: str | None = None
    confidence: float | None = None
    source: str | None = None
    unit_type_id: int | None = None
    unit_type_title: str | None = None
    max_preparation_days: int | None = None


class BatchItemRead(BaseModel):
    id: int
    batch_id: int
    title: str
    description: str
    price_toman: int | None
    stock: int | None = None
    preparation_days: int | None = None
    weight_grams: int | None = None
    package_weight_grams: int | None = None
    unit_quantity: int | None = None
    confidence: float
    edited_by_user: bool
    photos: list[BatchItemAssetRead]
    basalam_category: BatchItemBasalamCategoryRead | None = None
    created_at: datetime
    updated_at: datetime


class BatchItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = None
    price_toman: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    preparation_days: int | None = Field(default=None, ge=1)
    weight_grams: int | None = Field(default=None, ge=1)
    package_weight_grams: int | None = Field(default=None, ge=1)
    unit_quantity: int | None = Field(default=None, ge=1)


class BasalamCategoryPatch(BaseModel):
    category_id: int = Field(ge=1)


class MergeItemsRequest(BaseModel):
    source_item_ids: list[int] = Field(min_length=2)
    title: str | None = Field(default=None, max_length=220)
    description: str | None = None
    price_toman: int | None = Field(default=None, ge=0)


class SplitItemRequest(BaseModel):
    item_id: int
    asset_ids: list[int] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=220)
    description: str | None = None
    price_toman: int | None = Field(default=None, ge=0)


class ReorderPhotosRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


class ProcessStartResponse(BaseModel):
    job_id: int


class AiProductPhoto(BaseModel):
    upload_order: int


class AiProduct(BaseModel):
    title: str
    description: str
    price_toman: int | None
    stock: int | None = None
    preparation_days: int | None = None
    weight_grams: int | None = None
    package_weight_grams: int | None = None
    unit_quantity: int | None = None
    confidence: float = Field(ge=0, le=1)
    image_numbers: list[int] = Field(min_length=1)


class AiExtraction(BaseModel):
    transcript: str | None = None
    products: list[AiProduct]
    metadata: dict = Field(default_factory=dict)


class PlatformConnectionRead(BaseModel):
    id: int
    seller_id: int
    platform: str
    status: str
    external_user_id: str | None = None
    external_shop_id: str
    external_shop_slug: str | None = None
    external_shop_name: str
    scopes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OAuthUrlResponse(BaseModel):
    configured: bool
    url: str | None = None
    state: str | None = None
    error: str | None = None


class PublishStartResponse(BaseModel):
    job_id: int


class PublishJobRead(BaseModel):
    id: int
    batch_id: int
    connection_id: int
    platform: str
    status: str
    step: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublishedProductRead(BaseModel):
    id: int
    batch_item_id: int
    publish_job_id: int
    connection_id: int
    platform: str
    external_product_id: str | None = None
    external_url: str | None = None
    status: str
    error: str | None = None
    response_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
