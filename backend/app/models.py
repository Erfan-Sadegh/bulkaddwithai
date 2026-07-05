from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    mobile: Mapped[str] = mapped_column(String(32), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(180), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batches: Mapped[list["Batch"]] = relationship(back_populates="seller")
    platform_connections: Mapped[list["PlatformConnection"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    seller: Mapped[Seller] = relationship(back_populates="batches")
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="Asset.upload_order"
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="batch")
    publish_jobs: Mapped[list["PublishJob"]] = relationship(back_populates="batch")
    items: Mapped[list["BatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    upload_order: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[Batch] = relationship(back_populates="assets")
    item_links: Mapped[list["BatchItemAsset"]] = relationship(back_populates="asset")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    step: Mapped[str] = mapped_column(String(64), default="upload_ready", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[Batch] = relationship(back_populates="jobs")


class BatchItem(Base):
    __tablename__ = "batch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price_toman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preparation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_weight_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batch: Mapped[Batch] = relationship(back_populates="items")
    asset_links: Mapped[list["BatchItemAsset"]] = relationship(
        back_populates="batch_item", cascade="all, delete-orphan", order_by="BatchItemAsset.sort_order"
    )
    platform_data: Mapped[list["BatchItemPlatformData"]] = relationship(
        back_populates="batch_item", cascade="all, delete-orphan"
    )
    published_products: Mapped[list["PublishedProduct"]] = relationship(back_populates="batch_item")


class BatchItemAsset(Base):
    __tablename__ = "batch_item_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_item_id: Mapped[int] = mapped_column(
        ForeignKey("batch_items.id"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), default="product_photo", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    batch_item: Mapped[BatchItem] = relationship(back_populates="asset_links")
    asset: Mapped[Asset] = relationship(back_populates="item_links")


class BatchItemPlatformData(Base):
    __tablename__ = "batch_item_platform_data"
    __table_args__ = (
        UniqueConstraint("batch_item_id", "platform", name="uq_batch_item_platform_data"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_item_id: Mapped[int] = mapped_column(ForeignKey("batch_items.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category_title: Mapped[str | None] = mapped_column(String(220), nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category_unit_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_unit_type_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category_max_preparation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batch_item: Mapped[BatchItem] = relationship(back_populates="platform_data")


class PlatformConnection(Base):
    __tablename__ = "platform_connections"
    __table_args__ = (
        UniqueConstraint("platform", "external_shop_id", name="uq_platform_external_shop"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="connected", nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_shop_id: Mapped[str] = mapped_column(String(80), nullable=False)
    external_shop_slug: Mapped[str | None] = mapped_column(String(180), nullable=True)
    external_shop_name: Mapped[str] = mapped_column(String(220), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connection_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    seller: Mapped[Seller] = relationship(back_populates="platform_connections")
    publish_jobs: Mapped[list["PublishJob"]] = relationship(back_populates="connection")
    published_products: Mapped[list["PublishedProduct"]] = relationship(back_populates="connection")


class PublishJob(Base):
    __tablename__ = "publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("platform_connections.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    step: Mapped[str] = mapped_column(String(64), default="uploading_photos", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[Batch] = relationship(back_populates="publish_jobs")
    connection: Mapped[PlatformConnection] = relationship(back_populates="publish_jobs")
    products: Mapped[list["PublishedProduct"]] = relationship(
        back_populates="publish_job", cascade="all, delete-orphan"
    )


class PublishedProduct(Base):
    __tablename__ = "published_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_item_id: Mapped[int] = mapped_column(ForeignKey("batch_items.id"), nullable=False, index=True)
    publish_job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id"), nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("platform_connections.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_product_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batch_item: Mapped[BatchItem] = relationship(back_populates="published_products")
    publish_job: Mapped[PublishJob] = relationship(back_populates="products")
    connection: Mapped[PlatformConnection] = relationship(back_populates="published_products")
