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


class BatchItemRead(BaseModel):
    id: int
    batch_id: int
    title: str
    description: str
    price_toman: int | None
    confidence: float
    edited_by_user: bool
    photos: list[BatchItemAssetRead]
    created_at: datetime
    updated_at: datetime


class BatchItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = None
    price_toman: int | None = Field(default=None, ge=0)


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
    confidence: float = Field(ge=0, le=1)
    image_numbers: list[int] = Field(min_length=1)


class AiExtraction(BaseModel):
    transcript: str | None = None
    products: list[AiProduct]
    metadata: dict = Field(default_factory=dict)
