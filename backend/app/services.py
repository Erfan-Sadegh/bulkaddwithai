import csv
import hashlib
import io
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from fastapi import HTTPException, UploadFile
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .ai import AiProvider
from .config import Settings
from .image_processing import InvalidProductImageError, normalize_image_file
from .models import Asset, Batch, BatchItem, BatchItemAsset, BatchItemPlatformData, ProcessingJob, Seller, utc_now
from .schemas import AiExtraction, AiProduct, BatchItemAssetRead, BatchItemBasalamCategoryRead, BatchItemRead


IMAGE_MIME_PREFIX = "image/"
AUDIO_MIME_PREFIX = "audio/"
IMAGE_FILE_SUFFIXES = {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
AUDIO_FILE_SUFFIXES = {".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}
JOB_STEPS = ("upload_ready", "transcribing", "vision_extracting", "matching", "ready", "failed")
AI_STAGE_MAX_ATTEMPTS = 3
AI_RETRY_DELAYS_SECONDS = (1.0, 2.5)

logger = logging.getLogger(__name__)
StageResult = TypeVar("StageResult")


class ProcessingStageFailure(RuntimeError):
    def __init__(self, *, stage: str, code: str, attempts: int, original: Exception):
        super().__init__(_processing_error_message(code))
        self.stage = stage
        self.code = code
        self.attempts = attempts
        self.original = original


def create_seller(session: Session, name: str | None, mobile: str | None, shop_name: str | None) -> Seller:
    clean_name = (name or "").strip() or "فروشنده"
    clean_mobile = (mobile or "").strip() or "-"
    clean_shop_name = (shop_name or "").strip() or "فروشگاه"
    seller = Seller(name=clean_name, mobile=clean_mobile, shop_name=clean_shop_name)
    session.add(seller)
    session.commit()
    session.refresh(seller)
    return seller


def update_seller(
    session: Session, seller_id: int, name: str | None, mobile: str | None, shop_name: str | None
) -> Seller:
    seller = session.get(Seller, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    if name is not None:
        seller.name = name.strip() or "فروشنده"
    if mobile is not None:
        seller.mobile = mobile.strip() or "-"
    if shop_name is not None:
        seller.shop_name = shop_name.strip() or "فروشگاه"
    session.commit()
    session.refresh(seller)
    return seller


def create_batch(session: Session, seller_id: int) -> Batch:
    seller = session.get(Seller, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    batch = Batch(seller_id=seller_id, status="draft")
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def store_upload(
    settings: Settings,
    session: Session,
    batch_id: int,
    file: UploadFile,
    *,
    commit: bool = True,
) -> Asset:
    batch = session.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    content_type = file.content_type or "application/octet-stream"
    asset_type = _asset_type_from_mime(content_type, file.filename)
    if asset_type not in {"image", "audio"}:
        raise HTTPException(status_code=415, detail="Only image and audio uploads are supported")

    upload_order = _next_upload_order(session, batch_id, asset_type)
    target_dir = Path(settings.upload_dir) / str(batch_id) / asset_type
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg" if asset_type == "image" else Path(file.filename or "upload").suffix
    target_path = _unique_upload_path(target_dir, upload_order, suffix)
    temporary_path = target_dir / f".{uuid.uuid4().hex}.upload"

    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                output.write(chunk)
        if size == 0:
            raise InvalidProductImageError("empty image") if asset_type == "image" else HTTPException(
                status_code=422, detail="صدای ضبط‌شده خالی است. دوباره ضبط کن."
            )
        if asset_type == "image":
            normalize_image_file(temporary_path, target_path)
            content_type = "image/jpeg"
        else:
            temporary_path.replace(target_path)
        normalized_size = target_path.stat().st_size
        with target_path.open("rb") as stored:
            while chunk := stored.read(1024 * 1024):
                digest.update(chunk)
    except InvalidProductImageError as exc:
        temporary_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        logger.warning(
            "image_upload_rejected batch_id=%s suffix=%s declared_mime=%s input_bytes=%s error_type=%s",
            batch_id,
            Path(file.filename or "").suffix.lower(),
            content_type,
            size,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=422,
            detail="این عکس خوانده نشد. یک عکس سالم انتخاب کن و دوباره تلاش کن.",
        ) from exc
    except Exception:
        temporary_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)

    asset = Asset(
        batch_id=batch_id,
        type=asset_type,
        upload_order=upload_order,
        file_path=str(target_path),
        original_filename=file.filename or target_path.name,
        mime_type=content_type,
        size_bytes=normalized_size,
        checksum=digest.hexdigest(),
    )
    batch.status = "upload_ready"
    session.add(asset)
    if commit:
        session.commit()
        session.refresh(asset)
    else:
        session.flush()
    return asset


def store_uploads(settings: Settings, session: Session, batch_id: int, files: list[UploadFile]) -> list[Asset]:
    assets: list[Asset] = []
    try:
        for file in files:
            assets.append(store_upload(settings, session, batch_id, file, commit=False))
        session.commit()
        for asset in assets:
            session.refresh(asset)
        return assets
    except Exception as exc:
        session.rollback()
        for asset in assets:
            Path(asset.file_path).unlink(missing_ok=True)
        if not isinstance(exc, HTTPException):
            logger.exception(
                "upload_batch_failed batch_id=%s file_count=%s stored_before_failure=%s exception_type=%s",
                batch_id,
                len(files),
                len(assets),
                type(exc).__name__,
            )
        raise


def delete_asset(session: Session, asset_id: int) -> None:
    asset = session.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.item_links:
        raise HTTPException(status_code=422, detail="Asset is already attached to a product")

    batch_id = asset.batch_id
    asset_type = asset.type
    path = Path(asset.file_path)
    session.delete(asset)
    session.flush()
    _renumber_upload_orders(session, batch_id, asset_type)
    session.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def create_processing_job(session: Session, batch_id: int) -> tuple[ProcessingJob, bool]:
    batch = session.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not any(asset.type == "image" for asset in batch.assets):
        raise HTTPException(status_code=422, detail="At least one product image is required")
    active_job = session.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.batch_id == batch_id, ProcessingJob.status.in_(("queued", "running")))
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
    )
    if active_job:
        return active_job, False
    job = ProcessingJob(batch_id=batch_id, status="queued", step="upload_ready")
    batch.status = "processing"
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def run_processing_job(
    session_factory: sessionmaker[Session],
    provider_factory: Callable[[], AiProvider],
    job_id: int,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    session = session_factory()
    try:
        job = session.get(ProcessingJob, job_id)
        if not job:
            return
        batch = _batch_with_assets(session, job.batch_id)
        if not batch:
            raise RuntimeError("Batch not found")

        _mark_job(session, job, status="running", step="transcribing", started=True)
        images = [asset for asset in batch.assets if asset.type == "image"]
        audio_assets = sorted(
            (asset for asset in batch.assets if asset.type == "audio"),
            key=lambda asset: asset.upload_order,
            reverse=True,
        )
        audio = audio_assets[0] if audio_assets else None
        provider = provider_factory()
        attempts = {"transcription": 0, "extraction": 0}
        transcript = None
        if audio:
            transcript, attempts["transcription"] = _run_ai_stage_with_retry(
                lambda: provider.transcribe(audio),
                stage="transcribing",
                job_id=job.id,
                batch_id=batch.id,
                sleep_fn=sleep_fn,
            )

        _mark_job(session, job, status="running", step="vision_extracting")
        extraction, attempts["extraction"] = _run_ai_stage_with_retry(
            lambda: _extract_non_empty_products(provider, images, transcript),
            stage="vision_extracting",
            job_id=job.id,
            batch_id=batch.id,
            sleep_fn=sleep_fn,
        )

        _mark_job(session, job, status="running", step="matching")
        _replace_items_from_extraction(session, batch, images, extraction, extraction.transcript or transcript)

        batch.raw_transcript = extraction.transcript or transcript
        batch.ai_metadata = {
            **(extraction.metadata or {}),
            "processing_attempts": attempts,
        }
        batch.status = "ready"
        _mark_job(session, job, status="succeeded", step="ready", finished=True)
        logger.info(
            "processing_job_succeeded job_id=%s batch_id=%s image_count=%s audio_present=%s product_count=%s transcription_attempts=%s extraction_attempts=%s",
            job.id,
            batch.id,
            len(images),
            bool(audio),
            len(extraction.products),
            attempts["transcription"],
            attempts["extraction"],
        )
    except Exception as exc:
        session.rollback()
        job = session.get(ProcessingJob, job_id)
        if job:
            batch = session.get(Batch, job.batch_id)
            failure = _processing_failure_details(exc, job.step)
            if batch:
                batch.status = "failed"
                batch.ai_metadata = {
                    **(batch.ai_metadata or {}),
                    "last_processing_failure": failure,
                }
            job.status = "failed"
            job.step = "failed"
            job.error = _processing_error_message(failure["code"])
            job.finished_at = utc_now()
            session.commit()
            logger.exception(
                "processing_job_failed job_id=%s batch_id=%s stage=%s code=%s attempts=%s exception_type=%s image_number=%s",
                job.id,
                job.batch_id,
                failure["stage"],
                failure["code"],
                failure["attempts"],
                failure["exception_type"],
                failure.get("image_number"),
            )
    finally:
        session.close()


def _run_ai_stage_with_retry(
    operation: Callable[[], StageResult],
    *,
    stage: str,
    job_id: int,
    batch_id: int,
    sleep_fn: Callable[[float], None],
) -> tuple[StageResult, int]:
    for attempt in range(1, AI_STAGE_MAX_ATTEMPTS + 1):
        try:
            return operation(), attempt
        except Exception as exc:
            code, retryable = _classify_processing_error(exc, stage)
            if not retryable or attempt >= AI_STAGE_MAX_ATTEMPTS:
                raise ProcessingStageFailure(
                    stage=stage,
                    code=code,
                    attempts=attempt,
                    original=exc,
                ) from exc
            logger.warning(
                "processing_stage_retry job_id=%s batch_id=%s stage=%s attempt=%s code=%s exception_type=%s",
                job_id,
                batch_id,
                stage,
                attempt,
                code,
                type(exc).__name__,
            )
            sleep_fn(AI_RETRY_DELAYS_SECONDS[attempt - 1])
    raise AssertionError("AI retry loop ended unexpectedly")


def _extract_non_empty_products(provider: AiProvider, images: list[Asset], transcript: str | None) -> AiExtraction:
    extraction = provider.extract_products(images, transcript)
    if not extraction.products:
        raise RuntimeError("AI returned no products")
    return extraction


def _classify_processing_error(exc: Exception, stage: str) -> tuple[str, bool]:
    normalized = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code is None and getattr(exc, "response", None) is not None:
        status_code = getattr(exc.response, "status_code", None)

    original = exc.original if isinstance(exc, ProcessingStageFailure) else exc
    if isinstance(original, InvalidProductImageError):
        return "image_invalid", False
    if stage == "transcribing" and (
        status_code in {400, 413, 415}
        or any(token in normalized for token in ("unsupported audio", "invalid audio", "audio format", "empty file"))
    ):
        return "audio_invalid", False
    if "invalid extraction json" in normalized:
        return "invalid_output", True
    if "returned no products" in normalized:
        return "empty_output", True
    if (
        isinstance(exc, (TimeoutError, ConnectionError))
        or status_code in {408, 409, 429}
        or isinstance(status_code, int) and status_code >= 500
        or any(
            token in normalized
            for token in ("timeout", "timed out", "connection", "rate limit", "temporarily unavailable")
        )
    ):
        return "provider_temporary", True
    return ("transcription_failed" if stage == "transcribing" else "extraction_failed"), False


def _processing_failure_details(exc: Exception, fallback_stage: str) -> dict:
    if isinstance(exc, ProcessingStageFailure):
        details = {
            "code": exc.code,
            "stage": exc.stage,
            "attempts": exc.attempts,
            "exception_type": type(exc.original).__name__,
        }
        if isinstance(exc.original, InvalidProductImageError) and exc.original.upload_order is not None:
            details["image_number"] = exc.original.upload_order
        return details
    code, _retryable = _classify_processing_error(exc, fallback_stage)
    return {
        "code": code,
        "stage": fallback_stage,
        "attempts": 1,
        "exception_type": type(exc).__name__,
    }


def _processing_error_message(code: str) -> str:
    if code == "provider_temporary":
        return "ارتباط با هوش مصنوعی موقتاً برقرار نشد. دوباره تلاش کن."
    if code == "audio_invalid":
        return "صدای ضبط‌شده خوانده نشد. دوباره ضبط کن یا بدون صدا ادامه بده."
    if code == "image_invalid":
        return "یکی از عکس‌ها خوانده نشد. آن عکس را حذف کن، دوباره اضافه کن و تلاش کن."
    if code in {"invalid_output", "empty_output"}:
        return "هوش مصنوعی نتوانست لیست معتبر بسازد. دوباره تلاش کن."
    if code == "transcription_failed":
        return "خواندن صدای ضبط‌شده انجام نشد. دوباره ضبط کن یا بدون صدا ادامه بده."
    return "ساخت لیست کامل نشد. عکس‌ها باقی مانده‌اند؛ دوباره تلاش کن."


def list_items(session: Session, batch_id: int) -> list[BatchItemRead]:
    statement = _items_statement(batch_id)
    items = session.scalars(statement).all()
    return [_item_to_read(item) for item in items]


def update_item(session: Session, item_id: int, **changes) -> BatchItemRead:
    item = session.scalar(_item_by_id_statement(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    for key, value in changes.items():
        if key == "title" and value is None:
            continue
        setattr(item, key, value)
    item.edited_by_user = True
    session.commit()
    session.refresh(item)
    item = session.scalar(_item_by_id_statement(item_id))
    return _item_to_read(item)


def merge_items(
    session: Session, source_item_ids: list[int], title: str | None, description: str | None, price_toman: int | None
) -> BatchItemRead:
    items = [session.scalar(_item_by_id_statement(item_id)) for item_id in source_item_ids]
    if any(item is None for item in items):
        raise HTTPException(status_code=404, detail="One or more items were not found")
    batch_ids = {item.batch_id for item in items if item}
    if len(batch_ids) != 1:
        raise HTTPException(status_code=422, detail="Items must belong to the same batch")

    primary = items[0]
    primary.title = title or primary.title
    primary.description = description if description is not None else primary.description
    primary.price_toman = price_toman if price_toman is not None else primary.price_toman
    primary.edited_by_user = True

    existing_asset_ids = {link.asset_id for link in primary.asset_links}
    next_sort = len(primary.asset_links) + 1
    for item in items[1:]:
        for link in item.asset_links:
            if link.asset_id not in existing_asset_ids:
                primary.asset_links.append(
                    BatchItemAsset(asset_id=link.asset_id, role=link.role, sort_order=next_sort)
                )
                existing_asset_ids.add(link.asset_id)
                next_sort += 1
        session.delete(item)
    session.commit()
    return _item_to_read(session.scalar(_item_by_id_statement(primary.id)))


def split_item(
    session: Session,
    item_id: int,
    asset_ids: list[int],
    title: str | None,
    description: str | None,
    price_toman: int | None,
) -> BatchItemRead:
    item = session.scalar(_item_by_id_statement(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    current_ids = {link.asset_id for link in item.asset_links}
    if not set(asset_ids).issubset(current_ids):
        raise HTTPException(status_code=422, detail="Selected photos must belong to the item")
    if len(current_ids) == len(set(asset_ids)):
        raise HTTPException(status_code=422, detail="Split must leave at least one photo in the source item")

    for link in list(item.asset_links):
        if link.asset_id in asset_ids:
            session.delete(link)

    new_item = BatchItem(
        batch_id=item.batch_id,
        title=title or f"{item.title} - جدا شده",
        description=description if description is not None else item.description,
        price_toman=price_toman,
        confidence=item.confidence,
        edited_by_user=True,
    )
    session.add(new_item)
    session.flush()
    for index, asset_id in enumerate(asset_ids, start=1):
        session.add(
            BatchItemAsset(
                batch_item_id=new_item.id,
                asset_id=asset_id,
                role="product_photo",
                sort_order=index,
            )
        )
    item.edited_by_user = True
    session.commit()
    return _item_to_read(session.scalar(_item_by_id_statement(new_item.id)))


def reorder_photos(session: Session, item_id: int, asset_ids: list[int]) -> BatchItemRead:
    item = session.scalar(_item_by_id_statement(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    current_ids = {link.asset_id for link in item.asset_links}
    if set(asset_ids) != current_ids:
        raise HTTPException(status_code=422, detail="Reorder list must include exactly the item photos")
    order_map = {asset_id: index for index, asset_id in enumerate(asset_ids, start=1)}
    for link in item.asset_links:
        link.sort_order = order_map[link.asset_id]
    item.edited_by_user = True
    session.commit()
    return _item_to_read(session.scalar(_item_by_id_statement(item_id)))


def export_json(session: Session, batch_id: int) -> dict:
    batch = session.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(selectinload(Batch.seller), selectinload(Batch.assets), selectinload(Batch.items))
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch": {
            "id": batch.id,
            "status": batch.status,
            "transcript": batch.raw_transcript,
            "ai_metadata": batch.ai_metadata,
        },
        "seller": {
            "id": batch.seller.id,
            "name": batch.seller.name,
            "mobile": batch.seller.mobile,
            "shop_name": batch.seller.shop_name,
        },
        "items": [item.model_dump(mode="json") for item in list_items(session, batch_id)],
    }


def export_csv(session: Session, batch_id: int) -> str:
    batch = session.scalar(select(Batch).where(Batch.id == batch_id).options(selectinload(Batch.seller)))
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "seller_name",
            "seller_mobile",
            "shop_name",
            "batch_id",
            "item_id",
            "title",
            "description",
            "price_toman",
            "stock",
            "preparation_days",
            "weight_grams",
            "package_weight_grams",
            "unit_quantity",
            "image_numbers",
            "image_paths",
        ],
    )
    writer.writeheader()
    for item in list_items(session, batch_id):
        writer.writerow(
            {
                "seller_name": batch.seller.name,
                "seller_mobile": batch.seller.mobile,
                "shop_name": batch.seller.shop_name,
                "batch_id": batch.id,
                "item_id": item.id,
                "title": item.title,
                "description": item.description,
                "price_toman": item.price_toman or "",
                "stock": item.stock if item.stock is not None else "",
                "preparation_days": item.preparation_days if item.preparation_days is not None else "",
                "weight_grams": item.weight_grams if item.weight_grams is not None else "",
                "package_weight_grams": item.package_weight_grams if item.package_weight_grams is not None else "",
                "unit_quantity": item.unit_quantity if item.unit_quantity is not None else "",
                "image_numbers": ",".join(str(photo.upload_order) for photo in item.photos),
                "image_paths": ",".join(photo.url for photo in item.photos),
            }
        )
    return output.getvalue()


def clean_storage(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _replace_items_from_extraction(
    session: Session, batch: Batch, images: list[Asset], extraction: AiExtraction, transcript: str | None = None
) -> None:
    by_order = {asset.upload_order: asset for asset in images}
    existing_items = list(batch.items)
    existing_by_assets: dict[tuple[int, ...], list[BatchItem]] = {}
    for item in existing_items:
        asset_key = _item_asset_key(item)
        if asset_key:
            existing_by_assets.setdefault(asset_key, []).append(item)

    used_item_ids: set[int] = set()
    used_assets: set[int] = set()
    price_hints = _price_hints_from_transcript(transcript)
    for product in extraction.products:
        assets = [by_order[number] for number in product.image_numbers if number in by_order]
        if not assets:
            continue
        price_toman = _normalize_extracted_price_toman(product.price_toman)
        if price_toman is None:
            price_toman = _price_hint_for_product(product.title, product.description, product.image_numbers, price_hints)
        item = _first_unused_item(existing_by_assets.get(_asset_key(assets), []), used_item_ids)
        if item:
            _merge_extracted_product_into_item(item, product, price_toman)
            used_item_ids.add(item.id)
        else:
            item = BatchItem(
                batch_id=batch.id,
                title=product.title.strip() or "محصول بدون نام",
                description=product.description.strip(),
                price_toman=price_toman,
                stock=_normalize_non_negative_int(product.stock),
                preparation_days=_normalize_positive_int(product.preparation_days),
                weight_grams=_normalize_positive_int(product.weight_grams),
                package_weight_grams=_normalize_positive_int(product.package_weight_grams),
                unit_quantity=_normalize_positive_int(product.unit_quantity),
                confidence=product.confidence,
                edited_by_user=False,
            )
            session.add(item)
            session.flush()
            for index, asset in enumerate(assets, start=1):
                session.add(
                    BatchItemAsset(
                        batch_item_id=item.id,
                        asset_id=asset.id,
                        role="product_photo",
                        sort_order=index,
                    )
                )
        for asset in assets:
            used_assets.add(asset.id)

    for asset in images:
        if asset.id in used_assets or any(asset.id in _item_asset_ids(item) for item in existing_items):
            continue
        item = BatchItem(
            batch_id=batch.id,
            title=f"محصول عکس {asset.upload_order}",
            description="",
            price_toman=None,
            stock=None,
            preparation_days=None,
            weight_grams=None,
            package_weight_grams=None,
            unit_quantity=None,
            confidence=0.0,
            edited_by_user=False,
        )
        session.add(item)
        session.flush()
        session.add(
            BatchItemAsset(
                batch_item_id=item.id,
                asset_id=asset.id,
                role="product_photo",
                sort_order=1,
            )
        )
    session.flush()


def _asset_key(assets: list[Asset]) -> tuple[int, ...]:
    return tuple(sorted(asset.id for asset in assets))


def _item_asset_ids(item: BatchItem) -> set[int]:
    return {link.asset_id for link in item.asset_links}


def _item_asset_key(item: BatchItem) -> tuple[int, ...]:
    return tuple(sorted(_item_asset_ids(item)))


def _first_unused_item(items: list[BatchItem], used_item_ids: set[int]) -> BatchItem | None:
    return next((item for item in items if item.id not in used_item_ids), None)


def _merge_extracted_product_into_item(item: BatchItem, product: AiProduct, price_toman: int | None) -> None:
    if not item.edited_by_user:
        item.title = product.title.strip() or item.title or "محصول بدون نام"
        item.description = product.description.strip() or item.description
        if price_toman is not None:
            item.price_toman = price_toman
    else:
        if not item.title.strip():
            item.title = product.title.strip() or "محصول بدون نام"
        if not item.description.strip():
            item.description = product.description.strip()
        if item.price_toman is None and price_toman is not None:
            item.price_toman = price_toman

    _fill_or_update_extracted_number(item, "stock", _normalize_non_negative_int(product.stock))
    _fill_or_update_extracted_number(item, "preparation_days", _normalize_positive_int(product.preparation_days))
    _fill_or_update_extracted_number(item, "weight_grams", _normalize_positive_int(product.weight_grams))
    _fill_or_update_extracted_number(item, "package_weight_grams", _normalize_positive_int(product.package_weight_grams))
    _fill_or_update_extracted_number(item, "unit_quantity", _normalize_positive_int(product.unit_quantity))
    item.confidence = product.confidence


def _fill_or_update_extracted_number(item: BatchItem, field: str, value: int | None) -> None:
    if value is None:
        return
    current = getattr(item, field)
    if current is None or not item.edited_by_user:
        setattr(item, field, value)


def _normalize_extracted_price_toman(price_toman: int | None) -> int | None:
    if price_toman is None:
        return None
    if price_toman <= 0:
        return None
    if price_toman < 21:
        return price_toman * 1_000_000
    if price_toman < 1_000:
        return price_toman * 1_000
    return price_toman


def _normalize_positive_int(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _normalize_non_negative_int(value: int | None) -> int | None:
    if value is None or value < 0:
        return None
    return value


_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUMBER_WORDS = {
    "صفر": 0,
    "یه": 1,
    "یک": 1,
    "ی": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "شیش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
    "ده": 10,
    "یازده": 11,
    "دوازده": 12,
    "سیزده": 13,
    "چهارده": 14,
    "پانزده": 15,
    "شانزده": 16,
    "هفده": 17,
    "هجده": 18,
    "نوزده": 19,
    "بیست": 20,
    "سی": 30,
    "چهل": 40,
    "پنجاه": 50,
    "شصت": 60,
    "هفتاد": 70,
    "هشتاد": 80,
    "نود": 90,
    "صد": 100,
    "یکصد": 100,
    "دویست": 200,
    "دیویست": 200,
    "سیصد": 300,
    "چهارصد": 400,
    "پانصد": 500,
    "ششصد": 600,
    "هفتصد": 700,
    "هشتصد": 800,
    "نهصد": 900,
}


def _price_hints_from_transcript(transcript: str | None) -> dict[str, object]:
    if not transcript:
        return {"by_image": {}, "by_keyword": []}
    text = _normalize_persian_text(transcript)
    number_mentions = list(re.finditer(r"شماره\s+(?P<number>\d+|[آ-ی]+)", text))
    by_image: dict[int, int] = {}
    for index, mention in enumerate(number_mentions):
        image_number = _parse_small_number(mention.group("number"))
        if image_number is None:
            continue
        end = number_mentions[index + 1].start() if index + 1 < len(number_mentions) else len(text)
        segment = text[mention.end() : end]
        price = _first_price_in_text(segment)
        if price is not None:
            by_image[image_number] = price

    by_keyword: list[tuple[str, int]] = []
    for match in re.finditer(r"(?P<label>[آ-یA-Za-z\s]{2,35})\s+قیمتش\s+(?P<price>[^.،,\n]{1,35}?)(?:تومن|تومان|تومنه)", text):
        price = _parse_price_phrase(match.group("price"))
        if price is None:
            continue
        label_words = [word for word in match.group("label").split() if len(word) > 2]
        if label_words:
            by_keyword.append((label_words[-1], price))
    return {"by_image": by_image, "by_keyword": by_keyword}


def _price_hint_for_product(
    title: str, description: str, image_numbers: list[int], hints: dict[str, object]
) -> int | None:
    by_image = hints.get("by_image", {})
    if isinstance(by_image, dict):
        for image_number in image_numbers:
            price = by_image.get(image_number)
            if isinstance(price, int):
                return price

    searchable = _normalize_persian_text(f"{title} {description}")
    by_keyword = hints.get("by_keyword", [])
    if isinstance(by_keyword, list):
        for keyword, price in by_keyword:
            if isinstance(keyword, str) and isinstance(price, int) and keyword in searchable:
                return price
    return None


def _first_price_in_text(text: str) -> int | None:
    match = re.search(r"قیمتش\s+(?P<price>[^.،,\n]{1,35}?)(?:تومن|تومان|تومنه)", text)
    if not match:
        return None
    return _parse_price_phrase(match.group("price"))


def _parse_price_phrase(phrase: str) -> int | None:
    clean = _normalize_persian_text(phrase)
    multiplier = 1
    if "میلیون" in clean:
        multiplier = 1_000_000
        clean = clean.split("میلیون", 1)[0]
    elif "هزار" in clean:
        multiplier = 1_000
        clean = clean.split("هزار", 1)[0]

    number = _parse_small_number(clean)
    if number is None:
        return None
    if multiplier > 1:
        return number * multiplier
    return _normalize_extracted_price_toman(number)


def _parse_small_number(value: str) -> int | None:
    clean = _normalize_persian_text(value)
    digit_match = re.search(r"\d+", clean)
    if digit_match:
        return int(digit_match.group(0))
    total = 0
    found = False
    for token in re.split(r"\s+و\s+|\s+", clean):
        token = token.strip()
        if not token:
            continue
        if token in _NUMBER_WORDS:
            total += _NUMBER_WORDS[token]
            found = True
    return total if found else None


def _normalize_persian_text(value: str) -> str:
    return (
        value.translate(_DIGIT_TRANSLATION)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .strip()
    )


def _mark_job(
    session: Session,
    job: ProcessingJob,
    status: str,
    step: str,
    started: bool = False,
    finished: bool = False,
) -> None:
    job.status = status
    job.step = step
    if started:
        job.started_at = utc_now()
    if finished:
        job.finished_at = utc_now()
    session.commit()


def _asset_type_from_mime(mime_type: str, filename: str | None = None) -> str:
    if mime_type.startswith(IMAGE_MIME_PREFIX):
        return "image"
    if mime_type.startswith(AUDIO_MIME_PREFIX):
        return "audio"
    suffix = Path(filename or "").suffix.lower()
    if suffix in IMAGE_FILE_SUFFIXES:
        return "image"
    if suffix in AUDIO_FILE_SUFFIXES:
        return "audio"
    return "unknown"


def _next_upload_order(session: Session, batch_id: int, asset_type: str) -> int:
    existing = session.scalars(
        select(Asset.upload_order)
        .where(Asset.batch_id == batch_id, Asset.type == asset_type)
        .order_by(Asset.upload_order.desc())
        .limit(1)
    ).first()
    return (existing or 0) + 1


def _unique_upload_path(target_dir: Path, upload_order: int, suffix: str) -> Path:
    candidate = target_dir / f"{upload_order:04d}{suffix}"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = target_dir / f"{upload_order:04d}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _renumber_upload_orders(session: Session, batch_id: int, asset_type: str) -> None:
    assets = session.scalars(
        select(Asset)
        .where(Asset.batch_id == batch_id, Asset.type == asset_type)
        .order_by(Asset.upload_order, Asset.id)
    ).all()
    for index, item in enumerate(assets, start=1):
        item.upload_order = index


def _asset_url(asset: Asset) -> str:
    return f"/files/{asset.batch_id}/{asset.type}/{Path(asset.file_path).name}"


def _batch_with_assets(session: Session, batch_id: int) -> Batch | None:
    return session.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(
            selectinload(Batch.assets),
            selectinload(Batch.items).selectinload(BatchItem.asset_links),
        )
    )


def _items_statement(batch_id: int) -> Select:
    return (
        select(BatchItem)
        .where(BatchItem.batch_id == batch_id)
        .options(
            selectinload(BatchItem.asset_links).selectinload(BatchItemAsset.asset),
            selectinload(BatchItem.platform_data),
        )
        .order_by(BatchItem.id)
    )


def _item_by_id_statement(item_id: int) -> Select:
    return (
        select(BatchItem)
        .where(BatchItem.id == item_id)
        .options(
            selectinload(BatchItem.asset_links).selectinload(BatchItemAsset.asset),
            selectinload(BatchItem.platform_data),
        )
    )


def _item_to_read(item: BatchItem) -> BatchItemRead:
    basalam_data = _platform_data(item, "basalam")
    return BatchItemRead(
        id=item.id,
        batch_id=item.batch_id,
        title=item.title,
        description=item.description,
        price_toman=item.price_toman,
        stock=item.stock,
        preparation_days=item.preparation_days,
        weight_grams=item.weight_grams,
        package_weight_grams=item.package_weight_grams,
        unit_quantity=item.unit_quantity,
        confidence=item.confidence,
        edited_by_user=item.edited_by_user,
        photos=[
            BatchItemAssetRead(
                asset_id=link.asset_id,
                upload_order=link.asset.upload_order,
                url=_asset_url(link.asset),
                role=link.role,
                sort_order=link.sort_order,
            )
            for link in sorted(item.asset_links, key=lambda link: link.sort_order)
        ],
        basalam_category=_platform_data_to_basalam_read(basalam_data) if basalam_data else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _platform_data(item: BatchItem, platform: str) -> BatchItemPlatformData | None:
    return next((data for data in item.platform_data if data.platform == platform), None)


def _platform_data_to_basalam_read(data: BatchItemPlatformData) -> BatchItemBasalamCategoryRead:
    return BatchItemBasalamCategoryRead(
        category_id=data.category_id,
        title=data.category_title,
        path=data.category_path,
        confidence=data.category_confidence,
        source=data.category_source,
        unit_type_id=data.category_unit_type_id,
        unit_type_title=data.category_unit_type_title,
        max_preparation_days=data.category_max_preparation_days,
    )
