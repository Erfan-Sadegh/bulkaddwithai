from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UxEventCreate(BaseModel):
    event: Literal["image_picker_blocked", "image_picker_opened", "image_files_selected", "image_picker_cancelled"]
    control: Literal["photo_drop_zone", "add_photo_button"]
    reason: Literal["list_exists", "processing"] | None = None
    attempt_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    file_count: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_event_shape(self):
        if self.event == "image_picker_blocked":
            if self.reason is None or self.attempt_id is not None or self.file_count is not None:
                raise ValueError("blocked picker event shape is invalid")
            return self
        if self.attempt_id is None or self.reason is not None:
            raise ValueError("picker lifecycle event shape is invalid")
        if (self.event == "image_files_selected") != (self.file_count is not None):
            raise ValueError("selected picker event requires file_count")
        return self


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


class TorobSubmissionCreate(BaseModel):
    shop_name: str = Field(min_length=1, max_length=220)
    contact_mobile: str = Field(min_length=5, max_length=32)


class TorobSubmissionStartResponse(BaseModel):
    id: int
    status: str
    message: str


class TorobCandidateRead(BaseModel):
    base_product_rk: str
    title: str
    subtitle: str | None = None
    image_url: str | None = None
    price_text: str | None = None
    source: str = "torob"
    score: float | None = None


class TorobSubmissionItemRead(BaseModel):
    id: int
    batch_item_id: int
    title: str
    description: str
    price: int | None = None
    base_product_rk: str | None = None
    candidates: list[TorobCandidateRead] = Field(default_factory=list)
    status: str
    error: str | None = None
    image_numbers: list[int]
    image_urls: list[str]
    created_at: datetime
    updated_at: datetime


class TorobSubmissionRead(BaseModel):
    id: int
    seller_id: int
    batch_id: int
    shop_name: str
    contact_mobile: str
    status: str
    shop_id: int | None = None
    admin_note: str | None = None
    error: str | None = None
    response_metadata: dict | None = None
    items: list[TorobSubmissionItemRead]
    created_at: datetime
    updated_at: datetime


class TorobSubmissionItemPatch(BaseModel):
    base_product_rk: str | None = Field(default=None, max_length=80)
    price: int | None = Field(default=None, ge=0)


class TorobSubmissionItemPatchWithId(TorobSubmissionItemPatch):
    id: int


class TorobSubmissionPatch(BaseModel):
    shop_id: int | None = Field(default=None, ge=1)
    admin_note: str | None = None
    items: list[TorobSubmissionItemPatchWithId] | None = None


class TorobPublishItem(BaseModel):
    id: int
    base_product_rk: str = Field(min_length=1, max_length=80)
    price: int = Field(ge=0)


class TorobPublishRequest(BaseModel):
    shop_id: int = Field(ge=1)
    items: list[TorobPublishItem] = Field(min_length=1, max_length=100)


class AdminLoginResponse(BaseModel):
    ok: bool


class AdminLoginRequest(BaseModel):
    password: str
