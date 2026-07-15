from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


JOURNEY_STAGES = {
    "asset_manage": {"picker_opened", "files_selected", "upload_complete", "asset_deleted", "asset_reordered"},
    "catalog_build": {"build_started", "job_created", "processing_complete", "list_rendered"},
    "product_edit": {"edit_started", "save_started", "save_complete", "reload_verified"},
    "basalam_connect_restore": {"oauth_redirect", "batch_restored", "assets_restored", "items_restored", "restore_complete"},
    "basalam_publish": {"validation", "publish_started", "photos_uploaded", "products_created", "publish_complete"},
    "torob_submit": {"validation", "submit_started", "submission_created", "submit_complete"},
}


class UxEventCreate(BaseModel):
    event: Literal[
        "image_picker_blocked", "image_picker_opened", "image_files_selected", "image_picker_cancelled",
        "ui_rage_click", "ui_dead_click", "ui_action_started", "ui_action_accepted", "ui_action_blocked", "ui_action_failed",
    ]
    control: Literal[
        "photo_drop_zone", "add_photo_button", "build_product_list", "publish_basalam",
        "submit_torob", "connect_basalam", "record_voice", "change_platform",
        "delete_photo", "split_photo", "start_new_products", "category_picker",
        "fill_missing_fields", "apply_preparation_days",
    ]
    reason: Literal["list_exists", "processing"] | None = None
    attempt_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    file_count: int | None = Field(default=None, ge=1, le=100)
    click_count: int | None = Field(default=None, ge=3, le=12)
    outcome: Literal["validation", "state", "network", "server", "unknown"] | None = None
    failure_field: Literal[
        "title", "price_toman", "stock", "preparation_days", "weight_grams",
        "package_weight_grams", "unit_quantity", "category", "shop_name", "contact_mobile",
    ] | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_event_shape(self):
        if self.event.startswith("ui_action_"):
            if self.attempt_id is None or any(value is not None for value in (self.reason, self.file_count, self.click_count)):
                raise ValueError("action event shape is invalid")
            if self.event in {"ui_action_started", "ui_action_accepted"}:
                if self.outcome is not None or self.failure_field is not None:
                    raise ValueError("action start/accept must not include outcome")
            elif self.event == "ui_action_blocked":
                if self.outcome not in {"validation", "state"}:
                    raise ValueError("blocked action outcome is invalid")
                if self.outcome == "state" and self.failure_field is not None:
                    raise ValueError("state-blocked action cannot include a validation field")
            elif self.outcome not in {"network", "server", "unknown"}:
                raise ValueError("failed action outcome is invalid")
            elif self.failure_field is not None:
                raise ValueError("failed action cannot include a validation field")
            return self
        if self.event == "ui_rage_click":
            if self.failure_field is not None:
                raise ValueError("rage click event shape is invalid")
            if self.click_count is None or any(value is not None for value in (self.reason, self.attempt_id, self.file_count, self.outcome)):
                raise ValueError("rage click event shape is invalid")
            return self
        if self.event == "ui_dead_click":
            if any(value is not None for value in (self.reason, self.attempt_id, self.file_count, self.click_count, self.outcome, self.failure_field)):
                raise ValueError("dead click event shape is invalid")
            return self
        if self.control not in {"photo_drop_zone", "add_photo_button"} or self.click_count is not None or self.outcome is not None or self.failure_field is not None:
            raise ValueError("image picker control shape is invalid")
        if self.event == "image_picker_blocked":
            if self.reason is None or self.attempt_id is not None or self.file_count is not None:
                raise ValueError("blocked picker event shape is invalid")
            return self
        if self.attempt_id is None or self.reason is not None:
            raise ValueError("picker lifecycle event shape is invalid")
        if (self.event == "image_files_selected") != (self.file_count is not None):
            raise ValueError("selected picker event requires file_count")
        return self


class RuntimeEventCreate(BaseModel):
    event: Literal["frontend_runtime_failed"]
    code: Literal["script_error", "unhandled_rejection"]
    surface: Literal["catalog", "admin"]

    model_config = ConfigDict(extra="forbid")


class WorkflowIntegrityEventCreate(BaseModel):
    event: Literal[
        "basalam_oauth_restore_started",
        "basalam_oauth_restore_succeeded",
        "basalam_oauth_restore_failed",
    ]
    stage: Literal["redirect", "batch", "assets", "items", "complete"]
    reason: Literal["request_failed", "seller_mismatch", "count_mismatch"] | None = None
    expected_asset_count: int = Field(ge=0, le=10_000)
    expected_item_count: int = Field(ge=0, le=10_000)
    restored_asset_count: int | None = Field(default=None, ge=0, le=10_000)
    restored_item_count: int | None = Field(default=None, ge=0, le=10_000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_workflow_shape(self):
        restored = (self.restored_asset_count, self.restored_item_count)
        if self.event == "basalam_oauth_restore_started":
            if self.stage != "redirect" or self.reason is not None or any(value is not None for value in restored):
                raise ValueError("restore start event shape is invalid")
        elif self.event == "basalam_oauth_restore_succeeded":
            if self.stage != "complete" or self.reason is not None or any(value is None for value in restored):
                raise ValueError("restore success event shape is invalid")
        elif self.stage == "redirect" or self.reason is None:
            raise ValueError("restore failure event shape is invalid")
        return self


class JourneyEventCreate(BaseModel):
    """A privacy-safe Black Box state transition; arbitrary user data is forbidden."""

    event: Literal["journey_step"]
    journey: Literal[
        "asset_manage", "catalog_build", "product_edit", "basalam_connect_restore",
        "basalam_publish", "torob_submit",
    ]
    journey_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    stage: str = Field(min_length=2, max_length=48, pattern=r"^[a-z][a-z0-9_]+$")
    outcome: Literal["started", "progress", "succeeded", "failed", "blocked"]
    reason: Literal[
        "request_failed", "count_mismatch", "seller_mismatch", "validation",
        "network", "server", "timeout", "unknown",
    ] | None = None
    expected_asset_count: int | None = Field(default=None, ge=0, le=10_000)
    actual_asset_count: int | None = Field(default=None, ge=0, le=10_000)
    expected_item_count: int | None = Field(default=None, ge=0, le=10_000)
    actual_item_count: int | None = Field(default=None, ge=0, le=10_000)
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_contract(self):
        if self.stage not in JOURNEY_STAGES[self.journey]:
            raise ValueError("stage is not part of the journey contract")
        if self.outcome in {"failed", "blocked"} and self.reason is None:
            raise ValueError("failed journey step requires a safe reason")
        if self.outcome not in {"failed", "blocked"} and self.reason is not None:
            raise ValueError("successful journey step cannot include a reason")
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
