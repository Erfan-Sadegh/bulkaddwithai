import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .ai import CategoryCandidate, CategoryChoiceRequest, CategoryChoiceResult, get_ai_provider
from .basalam_categories import (
    BasalamCategory,
    category_to_dict,
    find_category,
    get_basalam_leaf_categories,
    search_categories,
)
from .config import Settings
from .integrations.basalam import (
    BasalamClient,
    BasalamClientError,
    BasalamProductPayload,
    BasalamUnauthorized,
    BasalamUploadedFile,
)
from .models import (
    Asset,
    Batch,
    BatchItem,
    BatchItemAsset,
    BatchItemPlatformData,
    PlatformConnection,
    PublishedProduct,
    PublishJob,
    Seller,
    utc_now,
)
from .services import _item_to_read

BASALAM_PLATFORM = "basalam"
PUBLISH_STEPS = ("uploading_photos", "creating_products", "ready", "failed")
BASALAM_NUMERIC_UNIT_TYPE_ID = 6304
BASALAM_NUMERIC_UNIT_TYPE_TITLE = "عددی"
BASALAM_ALLOWED_UNIT_TYPE_IDS = {
    6375,
    6374,
    6373,
    6332,
    6331,
    6330,
    6329,
    6328,
    6327,
    6326,
    6325,
    6324,
    6323,
    6322,
    6321,
    6320,
    6319,
    6318,
    6317,
    6316,
    6315,
    6314,
    6313,
    6312,
    6311,
    6310,
    6309,
    6308,
    6307,
    6306,
    6305,
    6304,
    6392,
    6438,
    6466,
}


def list_platform_connections(session: Session, seller_id: int) -> list[PlatformConnection]:
    if not session.get(Seller, seller_id):
        raise HTTPException(status_code=404, detail="Seller not found")
    return session.scalars(
        select(PlatformConnection)
        .where(PlatformConnection.seller_id == seller_id)
        .order_by(PlatformConnection.created_at.desc())
    ).all()


def create_basalam_oauth_url(
    settings: Settings, session: Session, client: BasalamClient, seller_id: int
) -> tuple[str, str]:
    if not session.get(Seller, seller_id):
        raise HTTPException(status_code=404, detail="Seller not found")
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Basalam OAuth is not configured")
    state = _make_oauth_state(settings, seller_id)
    return client.get_authorization_url(state), state


def handle_basalam_callback(
    settings: Settings,
    session: Session,
    client: BasalamClient,
    code: str | None,
    state: str | None,
    error: str | None = None,
    error_description: str | None = None,
) -> str:
    if error:
        return _frontend_redirect(settings, {"basalam_status": "failed", "error": error_description or error})
    if not code or not state:
        return _frontend_redirect(settings, {"basalam_status": "failed", "error": "missing_code_or_state"})

    try:
        state_payload = _read_oauth_state(settings, state)
    except Exception:
        return _frontend_redirect(settings, {"basalam_status": "failed", "error": "invalid_state"})

    seller_id = int(state_payload["seller_id"])
    seller = session.get(Seller, seller_id)
    if not seller:
        return _frontend_redirect(settings, {"basalam_status": "failed", "error": "seller_not_found"})

    try:
        tokens = client.exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
        user = client.get_current_user(access_token)
        vendor = user.get("vendor")
        if not vendor or not vendor.get("id"):
            return _frontend_redirect(settings, {"basalam_status": "failed", "error": "no_vendor_found"})
        connection = upsert_basalam_connection(session, seller, tokens, user, vendor)
    except Exception as exc:
        session.rollback()
        return _frontend_redirect(settings, {"basalam_status": "failed", "error": str(exc)})

    return _frontend_redirect(
        settings,
        {
            "basalam_status": "success",
            "seller_id": str(seller.id),
            "connection_id": str(connection.id),
            "shop_name": connection.external_shop_name,
        },
    )


def upsert_basalam_connection(
    session: Session, seller: Seller, tokens: dict, user: dict, vendor: dict
) -> PlatformConnection:
    external_shop_id = str(vendor["id"])
    connection = session.scalar(
        select(PlatformConnection).where(
            PlatformConnection.platform == BASALAM_PLATFORM,
            PlatformConnection.external_shop_id == external_shop_id,
        )
    )
    if not connection:
        connection = PlatformConnection(
            seller_id=seller.id,
            platform=BASALAM_PLATFORM,
            external_shop_id=external_shop_id,
            external_shop_name=str(vendor.get("title") or vendor.get("identifier") or external_shop_id),
            access_token=tokens["access_token"],
        )
        session.add(connection)
    connection.seller_id = seller.id
    connection.status = "connected"
    connection.external_user_id = str(user.get("id")) if user.get("id") is not None else None
    connection.external_shop_slug = vendor.get("identifier")
    connection.external_shop_name = str(vendor.get("title") or vendor.get("identifier") or external_shop_id)
    connection.access_token = tokens["access_token"]
    connection.refresh_token = tokens.get("refresh_token") or connection.refresh_token
    connection.token_type = tokens.get("token_type")
    connection.scopes = tokens.get("scope") or tokens.get("scopes")
    connection.expires_at = _expires_at(tokens.get("expires_in"))
    connection.connection_metadata = {"user": _public_user_metadata(user), "vendor": vendor}
    seller.shop_name = connection.external_shop_name
    seller.mobile = str(user.get("mobile") or seller.mobile or "-")
    session.commit()
    session.refresh(connection)
    return connection


def create_basalam_publish_job(session: Session, batch_id: int) -> tuple[PublishJob, bool]:
    batch = session.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(selectinload(Batch.seller).selectinload(Seller.platform_connections), selectinload(Batch.items))
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not batch.items:
        raise HTTPException(status_code=422, detail="No ready products found")
    connection = next(
        (
            item
            for item in batch.seller.platform_connections
            if item.platform == BASALAM_PLATFORM and item.status == "connected"
        ),
        None,
    )
    if not connection:
        raise HTTPException(status_code=422, detail="Basalam booth is not connected")
    active_job = session.scalar(
        select(PublishJob)
        .where(
            PublishJob.batch_id == batch.id,
            PublishJob.connection_id == connection.id,
            PublishJob.platform == BASALAM_PLATFORM,
            PublishJob.status.in_(("queued", "running")),
        )
        .order_by(PublishJob.created_at.desc(), PublishJob.id.desc())
    )
    if active_job:
        return active_job, False
    job = PublishJob(
        batch_id=batch.id,
        connection_id=connection.id,
        platform=BASALAM_PLATFORM,
        status="queued",
        step="uploading_photos",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def search_basalam_categories(settings: Settings, client: BasalamClient, query: str, limit: int = 20) -> list[dict]:
    categories = get_basalam_leaf_categories(settings, client)
    return [category_to_dict(category) for category in search_categories(categories, query, limit)]


def suggest_basalam_categories_for_batch(
    session: Session, settings: Settings, client: BasalamClient, batch_id: int
):
    batch = _batch_for_category_suggestion(session, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    categories = get_basalam_leaf_categories(settings, client)
    _suggest_missing_categories(session, settings, categories, batch.items, replace_low_confidence=True)
    session.commit()
    return [_item_to_read(item) for item in _batch_for_category_suggestion(session, batch_id).items]


def set_basalam_category_for_item(
    session: Session, settings: Settings, client: BasalamClient, item_id: int, category_id: int
):
    item = _item_for_category(session, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    categories = get_basalam_leaf_categories(settings, client)
    category = find_category(categories, category_id)
    if not category:
        raise HTTPException(status_code=422, detail="Basalam category was not found")
    _upsert_category_data(item, category, source="user", confidence=1.0)
    item.edited_by_user = True
    session.commit()
    return _item_to_read(_item_for_category(session, item_id))


def run_basalam_publish_job(
    settings: Settings,
    session_factory: sessionmaker[Session],
    client_factory,
    job_id: int,
) -> None:
    session = session_factory()
    try:
        job = session.get(PublishJob, job_id)
        if not job:
            return
        job.status = "running"
        job.step = "uploading_photos"
        job.started_at = utc_now()
        session.commit()

        batch = _batch_for_publish(session, job.batch_id)
        connection = session.get(PlatformConnection, job.connection_id)
        if not batch or not connection:
            raise RuntimeError("Publish job data was not found")

        client = client_factory(settings)
        categories = get_basalam_leaf_categories(settings, client)
        _suggest_missing_categories(session, settings, categories, batch.items, replace_low_confidence=False)
        session.commit()

        validation_errors = _publish_validation_errors(settings, batch.items)
        if validation_errors:
            for item, error in validation_errors:
                session.add(
                    PublishedProduct(
                        batch_item_id=item.id,
                        publish_job_id=job.id,
                        connection_id=connection.id,
                        platform=BASALAM_PLATFORM,
                        status="failed",
                        error=error,
                    )
                )
            job.step = "failed"
            job.status = "failed"
            job.error = f"{len(validation_errors)} محصول اطلاعات کامل ندارد"
            job.finished_at = utc_now()
            session.commit()
            return

        uploaded_by_asset_id = _upload_batch_photos(session, client, connection, batch.assets)

        job.step = "creating_products"
        session.commit()

        success_count = 0
        failure_count = 0
        for item in batch.items:
            published = _publish_item(
                session,
                settings,
                client,
                connection,
                job,
                item,
                uploaded_by_asset_id,
                categories,
            )
            if published.status == "published":
                success_count += 1
            else:
                failure_count += 1

        job.step = "ready"
        job.status = "succeeded" if failure_count == 0 else "partial_failed"
        job.error = None if failure_count == 0 else f"{failure_count} محصول ثبت نشد"
        job.finished_at = utc_now()
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(PublishJob, job_id)
        if job:
            job.status = "failed"
            job.step = "failed"
            job.error = str(exc)
            job.finished_at = utc_now()
            session.commit()
    finally:
        session.close()


def list_published_products(session: Session, batch_id: int) -> list[PublishedProduct]:
    if not session.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    return session.scalars(
        select(PublishedProduct)
        .join(BatchItem, PublishedProduct.batch_item_id == BatchItem.id)
        .where(BatchItem.batch_id == batch_id)
        .order_by(PublishedProduct.created_at.desc())
    ).all()


def refresh_connection_tokens(
    session: Session, client: BasalamClient, connection: PlatformConnection
) -> PlatformConnection:
    if not connection.refresh_token:
        raise BasalamClientError("Basalam refresh token is missing")
    tokens = client.refresh_tokens(connection.refresh_token)
    connection.access_token = tokens["access_token"]
    connection.refresh_token = tokens.get("refresh_token") or connection.refresh_token
    connection.token_type = tokens.get("token_type") or connection.token_type
    connection.scopes = tokens.get("scope") or tokens.get("scopes") or connection.scopes
    connection.expires_at = _expires_at(tokens.get("expires_in"))
    session.commit()
    session.refresh(connection)
    return connection


def _upload_batch_photos(
    session: Session, client: BasalamClient, connection: PlatformConnection, assets: list[Asset]
) -> dict[int, BasalamUploadedFile]:
    uploaded: dict[int, BasalamUploadedFile] = {}
    for asset in sorted((asset for asset in assets if asset.type == "image"), key=lambda asset: asset.upload_order):
        uploaded[asset.id] = _with_refresh(
            session,
            client,
            connection,
            lambda: client.upload_product_photo(connection, asset.file_path, asset.mime_type),
        )
    return uploaded


def _publish_validation_errors(settings: Settings, items: list[BatchItem]) -> list[tuple[BatchItem, str]]:
    errors: list[tuple[BatchItem, str]] = []
    for item in items:
        error = _publish_validation_error(settings, item)
        if error:
            errors.append((item, error))
    return errors


def _publish_validation_error(settings: Settings, item: BatchItem) -> str | None:
    if item.price_toman is None:
        return "برای ثبت محصول در باسلام، قیمت لازم است."
    if item.stock is None:
        return "برای ثبت محصول در باسلام، موجودی را وارد کن."
    if item.preparation_days is None:
        return "برای ثبت محصول در باسلام، زمان آماده‌سازی را وارد کن."
    if item.weight_grams is None:
        return "برای ثبت محصول در باسلام، وزن محصول را به گرم وارد کن."
    if item.package_weight_grams is None:
        return "برای ثبت محصول در باسلام، وزن محصول با بسته‌بندی را به گرم وارد کن."
    if item.unit_quantity is None:
        return "برای ثبت محصول در باسلام، مشخص کن هر فروش چندتا محصول دارد."
    category_data = _publishable_category_data(settings, item)
    if not category_data or category_data.category_id is None:
        return "برای ثبت محصول در باسلام، دسته‌بندی این محصول را انتخاب کن."
    if (
        category_data.category_max_preparation_days
        and item.preparation_days > category_data.category_max_preparation_days
    ):
        return f"زمان آماده‌سازی این دسته‌بندی حداکثر {category_data.category_max_preparation_days} روز است."
    if not item.asset_links:
        return "برای ثبت محصول در باسلام، حداقل یک عکس لازم است."
    return None


def _publish_item(
    session: Session,
    settings: Settings,
    client: BasalamClient,
    connection: PlatformConnection,
    job: PublishJob,
    item: BatchItem,
    uploaded_by_asset_id: dict[int, BasalamUploadedFile],
    categories: list[BasalamCategory],
) -> PublishedProduct:
    published = PublishedProduct(
        batch_item_id=item.id,
        publish_job_id=job.id,
        connection_id=connection.id,
        platform=BASALAM_PLATFORM,
        status="pending",
    )
    session.add(published)
    session.flush()
    try:
        response = _create_product_with_category_retries(
            session,
            settings,
            client,
            connection,
            item,
            uploaded_by_asset_id,
            categories,
        )
        external_id = response.get("id") or response.get("product_id") or response.get("data", {}).get("id")
        published.external_product_id = str(external_id) if external_id is not None else None
        published.external_url = response.get("url") or response.get("data", {}).get("url")
        published.status = "published"
        published.response_metadata = response
    except Exception as exc:
        published.status = "failed"
        published.error = str(exc)
        published.response_metadata = _basalam_failure_metadata(exc)
    session.commit()
    session.refresh(published)
    return published


def _basalam_failure_metadata(exc: Exception) -> dict:
    metadata = {"technical_error": str(exc)[:800]}
    if not isinstance(exc, BasalamClientError):
        return metadata

    if exc.status_code is not None:
        metadata["http_status"] = exc.status_code
    if exc.response_text:
        metadata["response_text"] = exc.response_text[:800]
    if exc.request_payload:
        payload = exc.request_payload
        metadata["request_payload_keys"] = sorted(payload.keys())
        metadata["request_payload_has_status"] = "status" in payload
        metadata["request_payload_status"] = payload.get("status")
        metadata["request_payload_category_id"] = payload.get("category_id")
        metadata["request_payload_unit_type"] = payload.get("unit_type")
        metadata["request_payload_primary_price"] = payload.get("primary_price")
        metadata["request_payload_photo_count"] = len(payload.get("photos") or [])
    return metadata


def _create_product_with_category_retries(
    session: Session,
    settings: Settings,
    client: BasalamClient,
    connection: PlatformConnection,
    item: BatchItem,
    uploaded_by_asset_id: dict[int, BasalamUploadedFile],
    categories: list[BasalamCategory],
) -> dict:
    category_data = _basalam_platform_data(item)
    original_category = _category_data_snapshot(category_data)
    last_error: Exception | None = None
    tried_category_ids: set[int] = set()

    for alternative in [None, *_category_retry_candidates(settings, categories, item)]:
        if alternative:
            _upsert_category_data(
                item,
                alternative,
                source="auto",
                confidence=max(alternative.confidence or 0.0, settings.basalam_category_suggestion_threshold),
                metadata={
                    "strategy": "publish_retry",
                    "reason": "previous_category_rejected",
                    "candidate_id": alternative.id,
                },
            )
            session.flush()

        current_category = _basalam_platform_data(item)
        if current_category and current_category.category_id:
            if current_category.category_id in tried_category_ids:
                continue
            tried_category_ids.add(current_category.category_id)

        try:
            payload = _item_to_basalam_payload(settings, item, uploaded_by_asset_id)
            try:
                return _with_refresh(session, client, connection, lambda: client.create_product(connection, payload))
            except Exception as exc:
                if not _can_retry_with_numeric_unit(exc, payload):
                    raise
                numeric_payload = _item_to_basalam_payload(
                    settings,
                    item,
                    uploaded_by_asset_id,
                    unit_type_override=BASALAM_NUMERIC_UNIT_TYPE_ID,
                )
                _mark_category_numeric_unit_fallback(item)
                session.flush()
                return _with_refresh(session, client, connection, lambda: client.create_product(connection, numeric_payload))
        except Exception as exc:
            last_error = exc
            if not _can_retry_with_another_category(exc, category_data):
                _restore_category_data(item, original_category)
                raise

    _restore_category_data(item, original_category)
    if last_error:
        raise last_error
    raise RuntimeError("Basalam product create failed")


def _category_retry_candidates(
    settings: Settings,
    categories: list[BasalamCategory],
    item: BatchItem,
    limit: int = 3,
) -> list[BasalamCategory]:
    data = _basalam_platform_data(item)
    if not data or data.category_source != "auto" or not data.category_id:
        return []

    metadata = data.platform_metadata or {}
    candidate_ids = metadata.get("candidate_ids")
    candidates_by_id = {category.id: category for category in categories}
    retry_candidates: list[BasalamCategory] = []
    metadata_candidate_ids: set[int] = set()

    if isinstance(candidate_ids, list):
        for raw_id in candidate_ids:
            try:
                candidate_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            candidate = candidates_by_id.get(candidate_id)
            if candidate and candidate.id != data.category_id:
                metadata_candidate_ids.add(candidate.id)
                retry_candidates.append(candidate)

    scored_candidates = search_categories(categories, f"{item.title} {item.description}", limit=8)
    retry_candidates.extend(scored_candidates)

    unique: list[BasalamCategory] = []
    seen: set[int] = {data.category_id}
    for candidate in retry_candidates:
        if candidate.id in seen:
            continue
        if (
            candidate.id not in metadata_candidate_ids
            and (candidate.confidence or 0) < max(0.45, settings.basalam_category_suggestion_threshold - 0.18)
        ):
            continue
        seen.add(candidate.id)
        unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def _can_retry_with_another_category(exc: Exception, category_data: BatchItemPlatformData | None) -> bool:
    if not category_data or category_data.category_source != "auto":
        return False
    normalized = str(exc).lower()
    if any(
        token in normalized
        for token in ("stock", "inventory", "price", "preparation", "weight", "unit_quantity", "unit_type", "unit type")
    ):
        return False
    return any(token in normalized for token in ("category", "attribute", "product(s) failed", "422", "دسته", "ویژگی"))


def _can_retry_with_numeric_unit(exc: Exception, payload: BasalamProductPayload) -> bool:
    if payload.unit_type == BASALAM_NUMERIC_UNIT_TYPE_ID:
        return False
    normalized = str(exc).lower()
    if "unit_quantity" in normalized:
        return False
    return any(token in normalized for token in ("unit_type", "unit type", '"unit"', "واحد"))


def _mark_category_numeric_unit_fallback(item: BatchItem) -> None:
    data = _basalam_platform_data(item)
    if not data:
        return
    data.category_unit_type_id = BASALAM_NUMERIC_UNIT_TYPE_ID
    data.category_unit_type_title = BASALAM_NUMERIC_UNIT_TYPE_TITLE
    metadata = data.platform_metadata or {}
    data.platform_metadata = {
        **metadata,
        "unit_type_fallback": "numeric",
        "unit_type_fallback_at": utc_now().isoformat(),
    }


def _category_data_snapshot(data: BatchItemPlatformData | None) -> dict | None:
    if not data:
        return None
    return {
        "category_id": data.category_id,
        "category_title": data.category_title,
        "category_path": data.category_path,
        "category_confidence": data.category_confidence,
        "category_source": data.category_source,
        "category_unit_type_id": data.category_unit_type_id,
        "category_unit_type_title": data.category_unit_type_title,
        "category_max_preparation_days": data.category_max_preparation_days,
        "platform_metadata": data.platform_metadata,
    }


def _restore_category_data(item: BatchItem, snapshot: dict | None) -> None:
    if snapshot is None:
        return
    data = _basalam_platform_data(item)
    if not data:
        return
    for key, value in snapshot.items():
        setattr(data, key, value)


def _item_to_basalam_payload(
    settings: Settings,
    item: BatchItem,
    uploaded_by_asset_id: dict[int, BasalamUploadedFile],
    unit_type_override: int | None = None,
) -> BasalamProductPayload:
    if item.price_toman is None:
        raise ValueError("برای ثبت محصول در باسلام، قیمت لازم است.")
    if item.stock is None:
        raise ValueError("برای ثبت محصول در باسلام، موجودی را وارد کن.")
    if item.preparation_days is None:
        raise ValueError("برای ثبت محصول در باسلام، زمان آماده‌سازی را وارد کن.")
    if item.weight_grams is None:
        raise ValueError("برای ثبت محصول در باسلام، وزن محصول را به گرم وارد کن.")
    if item.package_weight_grams is None:
        raise ValueError("برای ثبت محصول در باسلام، وزن محصول با بسته‌بندی را به گرم وارد کن.")
    if item.unit_quantity is None:
        raise ValueError("برای ثبت محصول در باسلام، مشخص کن هر فروش چندتا محصول دارد.")
    category_data = _publishable_category_data(settings, item)
    category_id = category_data.category_id if category_data else None
    if category_id is None:
        raise ValueError("برای ثبت محصول در باسلام، دسته‌بندی این محصول را انتخاب کن.")
    if (
        category_data
        and category_data.category_max_preparation_days
        and item.preparation_days > category_data.category_max_preparation_days
    ):
        raise ValueError(
            f"زمان آماده‌سازی این دسته‌بندی حداکثر {category_data.category_max_preparation_days} روز است."
        )
    unit_type = _basalam_unit_type_id(category_data, unit_type_override)
    photo_ids = [
        uploaded_by_asset_id[link.asset_id].id
        for link in sorted(item.asset_links, key=lambda link: link.sort_order)
        if link.asset_id in uploaded_by_asset_id
    ]
    if not photo_ids:
        raise ValueError("برای ثبت محصول در باسلام، حداقل یک عکس لازم است.")
    return BasalamProductPayload(
        name=item.title,
        description=item.description or item.title,
        primary_price=_toman_to_rial(item.price_toman),
        photo_ids=photo_ids,
        category_id=category_id,
        stock=item.stock,
        status=settings.basalam_default_status,
        preparation_days=item.preparation_days,
        weight=item.weight_grams,
        package_weight=item.package_weight_grams,
        unit_quantity=item.unit_quantity,
        unit_type=unit_type,
    )


def _basalam_unit_type_id(category_data: BatchItemPlatformData | None, override: int | None = None) -> int:
    if override in BASALAM_ALLOWED_UNIT_TYPE_IDS:
        return override
    if category_data and category_data.category_unit_type_id in BASALAM_ALLOWED_UNIT_TYPE_IDS:
        return category_data.category_unit_type_id
    return BASALAM_NUMERIC_UNIT_TYPE_ID


def _toman_to_rial(price_toman: int) -> int:
    return price_toman * 10


def _with_refresh(session: Session, client: BasalamClient, connection: PlatformConnection, operation):
    try:
        return operation()
    except BasalamUnauthorized:
        refresh_connection_tokens(session, client, connection)
        return operation()


def _batch_for_publish(session: Session, batch_id: int) -> Batch | None:
    return session.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(
            selectinload(Batch.assets),
            selectinload(Batch.items)
            .selectinload(BatchItem.asset_links)
            .selectinload(BatchItemAsset.asset),
            selectinload(Batch.items).selectinload(BatchItem.platform_data),
        )
    )


def _batch_for_category_suggestion(session: Session, batch_id: int) -> Batch | None:
    return session.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(
            selectinload(Batch.items)
            .selectinload(BatchItem.asset_links)
            .selectinload(BatchItemAsset.asset),
            selectinload(Batch.items).selectinload(BatchItem.platform_data),
        )
    )


def _item_for_category(session: Session, item_id: int) -> BatchItem | None:
    return session.scalar(
        select(BatchItem)
        .where(BatchItem.id == item_id)
        .options(
            selectinload(BatchItem.asset_links).selectinload(BatchItemAsset.asset),
            selectinload(BatchItem.platform_data),
        )
    )


def _suggest_missing_categories(
    session: Session,
    settings: Settings,
    categories: list[BasalamCategory],
    items: list[BatchItem],
    replace_low_confidence: bool,
) -> None:
    ai_provider = get_ai_provider(settings)
    pending: list[tuple[BatchItem, list[BasalamCategory], CategoryChoiceRequest]] = []
    for item in items:
        current = _basalam_platform_data(item)
        if current and current.category_source == "user":
            continue
        if current and current.category_id and not replace_low_confidence:
            continue
        if current and current.category_id and (current.category_confidence or 0) >= settings.basalam_category_suggestion_threshold:
            continue
        candidates = search_categories(categories, f"{item.title} {item.description}", limit=14)
        if not candidates:
            continue
        pending.append(
            (
                item,
                candidates,
                CategoryChoiceRequest(
                    item_key=str(item.id),
                    title=item.title,
                    description=item.description,
                    candidates=[
                        CategoryCandidate(
                            id=category.id,
                            title=category.title,
                            path=category.path,
                            confidence=category.confidence,
                        )
                        for category in candidates
                    ],
                ),
            )
        )
    if not pending:
        session.flush()
        return
    requests = [request for _, _, request in pending]
    try:
        choices = ai_provider.choose_basalam_categories(requests)
        choice_by_key = {choice.item_key: choice for choice in choices}
        ai_error = None
    except Exception as exc:
        choice_by_key = {}
        ai_error = str(exc)[:400]

    for item, candidates, request in pending:
        if ai_error:
            fallback = candidates[0]
            suggested, metadata = fallback, {
                "strategy": "scored_fallback",
                "reason": "ai_failed",
                "error": ai_error,
                "candidate_ids": [category.id for category in candidates],
            }
        else:
            suggested, metadata = _category_from_ai_choice(candidates, choice_by_key.get(request.item_key))
        if suggested:
            _upsert_category_data(
                item,
                suggested,
                source="auto",
                confidence=suggested.confidence or 0,
                metadata=metadata,
            )
    session.flush()


def _category_from_ai_choice(
    candidates: list[BasalamCategory], choice: CategoryChoiceResult | None
) -> tuple[BasalamCategory | None, dict]:
    fallback = candidates[0]
    if not choice:
        return fallback, {
            "strategy": "scored_fallback",
            "reason": "ai_missing_choice",
            "candidate_ids": [category.id for category in candidates],
        }
    if choice.candidate_id is None:
        return None, {
            "strategy": "ai_batch_shortlist",
            "reason": choice.reason,
            "ai_confidence": choice.confidence,
            "candidate_ids": [category.id for category in candidates],
        }
    selected = find_category(candidates, choice.candidate_id)
    if not selected:
        return fallback, {
            "strategy": "scored_fallback",
            "reason": "ai_selected_missing_candidate",
            "ai_confidence": choice.confidence,
            "candidate_ids": [category.id for category in candidates],
        }
    selected = BasalamCategory(
        id=selected.id,
        title=selected.title,
        path=selected.path,
        unit_type_id=selected.unit_type_id,
        unit_type_title=selected.unit_type_title,
        max_preparation_days=selected.max_preparation_days,
        confidence=max(selected.confidence or 0.0, choice.confidence),
    )
    return selected, {
        "strategy": "ai_batch_shortlist",
        "reason": choice.reason,
        "ai_confidence": choice.confidence,
        "scored_confidence": selected.confidence,
        "candidate_ids": [category.id for category in candidates],
    }


def _upsert_category_data(
    item: BatchItem, category: BasalamCategory, source: str, confidence: float, metadata: dict | None = None
) -> BatchItemPlatformData:
    data = _basalam_platform_data(item)
    if not data:
        data = BatchItemPlatformData(batch_item_id=item.id, platform=BASALAM_PLATFORM)
        item.platform_data.append(data)
    data.category_id = category.id
    data.category_title = category.title
    data.category_path = category.path
    data.category_confidence = confidence
    data.category_source = source
    data.category_unit_type_id = category.unit_type_id
    data.category_unit_type_title = category.unit_type_title
    data.category_max_preparation_days = category.max_preparation_days
    data.platform_metadata = {"matched_at": utc_now().isoformat(), **(metadata or {})}
    return data


def _basalam_platform_data(item: BatchItem) -> BatchItemPlatformData | None:
    return next((data for data in item.platform_data if data.platform == BASALAM_PLATFORM), None)


def _publishable_category_data(settings: Settings, item: BatchItem) -> BatchItemPlatformData | None:
    data = _basalam_platform_data(item)
    if not data or not data.category_id:
        return None
    return data


def _make_oauth_state(settings: Settings, seller_id: int) -> str:
    payload = {
        "seller_id": seller_id,
        "iat": int(time.time()),
    }
    encoded = _urlsafe_b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_state_secret(settings), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _read_oauth_state(settings: Settings, state: str) -> dict:
    try:
        encoded, signature = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid OAuth state") from exc
    expected = hmac.new(_state_secret(settings), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid OAuth state signature")
    payload = json.loads(_urlsafe_b64_decode(encoded))
    if int(time.time()) - int(payload.get("iat", 0)) > 1800:
        raise ValueError("OAuth state expired")
    return payload


def _state_secret(settings: Settings) -> bytes:
    secret = settings.basalam_client_secret or "local-dev-state-secret"
    return secret.encode("utf-8")


def _urlsafe_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _expires_at(expires_in: int | str | None):
    if not expires_in:
        return None
    return utc_now() + timedelta(seconds=int(expires_in))


def _frontend_redirect(settings: Settings, params: dict[str, str]) -> str:
    return f"{settings.frontend_url.rstrip('/')}?{urlencode(params)}"


def _public_user_metadata(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "mobile": user.get("mobile"),
    }
