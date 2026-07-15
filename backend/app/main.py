from collections.abc import Generator
from datetime import datetime
from pathlib import Path
import json
import logging
import secrets

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .ai import get_ai_provider
from .config import Settings, get_settings
from .database import create_tables, make_engine, make_session_factory
from .integrations.basalam import BasalamClient
from .integrations.torob import TorobClient
from .models import Asset, Batch, OperationalEvent, ProcessingJob, PublishedProduct, PublishJob, Seller
from .observability import configure_event_store, configure_observability, observe_http_request
from .platform_services import (
    create_basalam_oauth_url,
    create_basalam_publish_job,
    handle_basalam_callback,
    list_platform_connections,
    list_published_products,
    run_basalam_publish_job,
    search_basalam_categories,
    set_basalam_category_for_item,
    suggest_basalam_categories_for_batch,
)
from .schemas import (
    AssetRead,
    BasalamCategoryPatch,
    BasalamCategoryRead,
    BatchCreate,
    BatchItemPatch,
    BatchItemRead,
    BatchRead,
    JobRead,
    MergeItemsRequest,
    OAuthUrlResponse,
    PlatformConnectionRead,
    PublishedProductRead,
    PublishJobRead,
    PublishStartResponse,
    ProcessStartResponse,
    ReorderPhotosRequest,
    SellerCreate,
    SellerPatch,
    SellerRead,
    SplitItemRequest,
    AdminLoginRequest,
    AdminLoginResponse,
    TorobPublishRequest,
    TorobSubmissionCreate,
    TorobSubmissionPatch,
    TorobSubmissionRead,
    TorobSubmissionStartResponse,
    UxEventCreate,
)
from .services import (
    create_batch,
    create_processing_job,
    create_seller,
    delete_asset,
    export_csv,
    export_json,
    list_items,
    merge_items,
    reorder_photos,
    run_processing_job,
    split_item,
    store_uploads,
    update_item,
    update_seller,
)
from .torob_services import (
    create_torob_submission,
    get_torob_submission,
    list_torob_submissions,
    patch_torob_submission,
    publish_torob_submission,
)


SAFE_PROVIDER_FAILURE_FIELDS = {
    "package_weight",
    "weight",
    "status",
    "category_id",
    "unit_type",
    "primary_price",
    "stock",
    "preparation_days",
    "photos",
    "name",
}


def _safe_failure_field(metadata: dict) -> str | None:
    response_text = metadata.get("response_text")
    if not isinstance(response_text, str):
        return None
    try:
        payload = json.loads(response_text)
    except (TypeError, ValueError):
        return None
    candidates = payload.get("messages") or payload.get("openapi_raw_data") or [] if isinstance(payload, dict) else []
    for candidate in candidates if isinstance(candidates, list) else []:
        fields = candidate.get("fields") if isinstance(candidate, dict) else None
        for field in fields if isinstance(fields, list) else []:
            if field in SAFE_PROVIDER_FAILURE_FIELDS:
                return field
    return None


def _safe_published_product_failure(item: PublishedProduct, settings: Settings) -> dict:
    metadata = item.response_metadata if isinstance(item.response_metadata, dict) else {}
    return {
        "event": "basalam_product_failed",
        "severity": "warning",
        "environment": settings.environment,
        "release": settings.release,
        "job_id": item.publish_job_id,
        "item_id": item.batch_item_id,
        "platform": item.platform,
        "http_status": metadata.get("http_status"),
        "category_id": metadata.get("request_payload_category_id"),
        "unit_type": metadata.get("request_payload_unit_type"),
        "request_status": metadata.get("request_payload_status"),
        "photo_count": metadata.get("request_payload_photo_count"),
        "failure_field": _safe_failure_field(metadata),
        "last_seen_at": item.created_at,
        "count": 1,
        "evidence_source": "published_products",
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_observability(settings)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    create_tables(engine)
    configure_event_store(session_factory, settings)
    ux_logger = logging.getLogger("app.ux")

    app = FastAPI(title="Bulk Add With AI", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.basalam_client_factory = lambda app_settings: BasalamClient(app_settings)
    app.state.torob_client_factory = lambda app_settings: TorobClient(app_settings)

    app.middleware("http")(observe_http_request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.mount("/files", StaticFiles(directory=Path(settings.upload_dir)), name="files")

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def provider_factory():
        return get_ai_provider(settings)

    def basalam_client_factory():
        return app.state.basalam_client_factory(settings)

    def torob_client_factory():
        return app.state.torob_client_factory(settings)

    def require_admin(x_admin_password: str | None = Header(default=None)):
        if not settings.admin_password:
            raise HTTPException(status_code=503, detail="Admin password is not configured")
        if x_admin_password != settings.admin_password:
            raise HTTPException(status_code=401, detail="Admin password is invalid")

    def require_observability_reader(authorization: str | None = Header(default=None)):
        expected = settings.observability_read_token
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not expected or not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Observability token is invalid")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/observability/events", dependencies=[Depends(require_observability_reader)])
    def get_operational_events(
        since: datetime | None = None,
        limit: int = 200,
        session: Session = Depends(get_session),
    ):
        safe_limit = min(max(limit, 1), 500)
        statement = select(OperationalEvent).order_by(OperationalEvent.created_at.desc()).limit(safe_limit)
        if since is not None:
            statement = statement.where(OperationalEvent.created_at >= since)
        events = session.scalars(statement).all()
        operational = [
            {
                "event": item.event,
                "severity": item.severity,
                "environment": item.environment,
                "release": item.release,
                "request_id": item.request_id,
                "job_id": item.job_id,
                "batch_id": item.batch_id,
                "stage": item.stage,
                "code": item.code,
                "last_seen_at": item.created_at,
                "count": 1,
                **(item.context or {}),
            }
            for item in events
        ]
        failed_statement = (
            select(PublishedProduct)
            .where(PublishedProduct.status == "failed")
            .order_by(PublishedProduct.created_at.desc())
            .limit(safe_limit)
        )
        if since is not None:
            failed_statement = failed_statement.where(PublishedProduct.created_at >= since)
        durable_failures = [_safe_published_product_failure(item, settings) for item in session.scalars(failed_statement)]
        combined = [*operational, *durable_failures]
        combined.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
        return combined[:safe_limit]

    @app.post("/observability/ux-events", status_code=204)
    def post_ux_event(payload: UxEventCreate):
        # The schema accepts no user text, URL, identifier, or arbitrary event.
        if payload.event == "ui_rage_click":
            ux_logger.warning("%s control=%s click_count=%s", payload.event, payload.control, payload.click_count)
        elif payload.event.startswith("ui_action_"):
            log = ux_logger.warning if payload.event in {"ui_action_blocked", "ui_action_failed"} else ux_logger.info
            log(
                "%s control=%s attempt_id=%s outcome=%s",
                payload.event,
                payload.control,
                payload.attempt_id,
                payload.outcome or "none",
            )
        elif payload.event == "image_picker_blocked":
            ux_logger.info("%s control=%s reason=%s", payload.event, payload.control, payload.reason)
        elif payload.event == "image_files_selected":
            ux_logger.info(
                "%s control=%s attempt_id=%s file_count=%s",
                payload.event,
                payload.control,
                payload.attempt_id,
                payload.file_count,
            )
        else:
            ux_logger.info("%s control=%s attempt_id=%s", payload.event, payload.control, payload.attempt_id)
        return Response(status_code=204)

    @app.post("/admin/login", response_model=AdminLoginResponse)
    def post_admin_login(payload: AdminLoginRequest):
        if not settings.admin_password:
            raise HTTPException(status_code=503, detail="Admin password is not configured")
        if payload.password != settings.admin_password:
            raise HTTPException(status_code=401, detail="Admin password is invalid")
        return AdminLoginResponse(ok=True)

    @app.post("/sellers", response_model=SellerRead, status_code=201)
    def post_seller(payload: SellerCreate, session: Session = Depends(get_session)):
        return create_seller(session, payload.name, payload.mobile, payload.shop_name)

    @app.get("/sellers", response_model=list[SellerRead])
    def get_sellers(session: Session = Depends(get_session)):
        return []

    @app.get("/sellers/{seller_id}", response_model=SellerRead)
    def get_seller(seller_id: int, session: Session = Depends(get_session)):
        seller = session.get(Seller, seller_id)
        if not seller:
            raise HTTPException(status_code=404, detail="Seller not found")
        return seller

    @app.patch("/sellers/{seller_id}", response_model=SellerRead)
    def patch_seller(seller_id: int, payload: SellerPatch, session: Session = Depends(get_session)):
        return update_seller(session, seller_id, **payload.model_dump(exclude_unset=True))

    @app.post("/batches", response_model=BatchRead, status_code=201)
    def post_batch(payload: BatchCreate, session: Session = Depends(get_session)):
        return create_batch(session, payload.seller_id)

    @app.get("/batches", response_model=list[BatchRead])
    def get_batches(seller_id: int | None = None, session: Session = Depends(get_session)):
        statement = select(Batch).order_by(Batch.created_at.desc())
        if seller_id is not None:
            statement = statement.where(Batch.seller_id == seller_id)
        return session.scalars(statement).all()

    @app.get("/batches/{batch_id}", response_model=BatchRead)
    def get_batch(batch_id: int, session: Session = Depends(get_session)):
        batch = session.get(Batch, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch

    @app.post("/batches/{batch_id}/assets", response_model=list[AssetRead], status_code=201)
    def post_assets(
        batch_id: int,
        files: list[UploadFile] = File(...),
        session: Session = Depends(get_session),
    ):
        assets = store_uploads(settings, session, batch_id, files)
        return [_asset_to_read(asset) for asset in assets]

    @app.get("/batches/{batch_id}/assets", response_model=list[AssetRead])
    def get_assets(batch_id: int, session: Session = Depends(get_session)):
        assets = session.scalars(
            select(Asset).where(Asset.batch_id == batch_id).order_by(Asset.type, Asset.upload_order)
        ).all()
        return [_asset_to_read(asset) for asset in assets]

    @app.delete("/assets/{asset_id}", status_code=204)
    def delete_upload_asset(asset_id: int, session: Session = Depends(get_session)):
        delete_asset(session, asset_id)
        return Response(status_code=204)

    @app.post("/batches/{batch_id}/process", response_model=ProcessStartResponse, status_code=202)
    def post_process(
        batch_id: int,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_session),
    ):
        job, created = create_processing_job(session, batch_id)
        if created:
            background_tasks.add_task(run_processing_job, session_factory, provider_factory, job.id)
        return ProcessStartResponse(job_id=job.id)

    @app.get("/jobs/{job_id}", response_model=JobRead)
    def get_job(job_id: int, session: Session = Depends(get_session)):
        job = session.get(ProcessingJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/sellers/{seller_id}/platform-connections", response_model=list[PlatformConnectionRead])
    def get_platform_connections(
        seller_id: int, workspace_id: str | None = None, session: Session = Depends(get_session)
    ):
        return list_platform_connections(session, seller_id, workspace_id)

    @app.get("/integrations/basalam/oauth-url", response_model=OAuthUrlResponse)
    def get_basalam_oauth_url(
        seller_id: int, workspace_id: str | None = None, session: Session = Depends(get_session)
    ):
        try:
            url, state = create_basalam_oauth_url(settings, session, basalam_client_factory(), seller_id, workspace_id)
        except HTTPException as exc:
            if exc.status_code == 503:
                return OAuthUrlResponse(
                    configured=False,
                    url=None,
                    state=None,
                    error="اتصال باسلام در این محیط تنظیم نشده است.",
                )
            raise
        return OAuthUrlResponse(configured=True, url=url, state=state)

    @app.get("/integrations/basalam/categories", response_model=list[BasalamCategoryRead])
    def get_basalam_categories(query: str = "", limit: int = 20):
        return search_basalam_categories(settings, basalam_client_factory(), query, min(max(limit, 1), 50))

    @app.post("/batches/{batch_id}/categories/basalam/suggest", response_model=list[BatchItemRead])
    def post_suggest_basalam_categories(batch_id: int, session: Session = Depends(get_session)):
        return suggest_basalam_categories_for_batch(session, settings, basalam_client_factory(), batch_id)

    @app.patch("/batch-items/{item_id}/basalam-category", response_model=BatchItemRead)
    def patch_batch_item_basalam_category(
        item_id: int, payload: BasalamCategoryPatch, session: Session = Depends(get_session)
    ):
        return set_basalam_category_for_item(
            session, settings, basalam_client_factory(), item_id, payload.category_id
        )

    @app.get("/integrations/basalam/callback")
    def get_basalam_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
        session: Session = Depends(get_session),
    ):
        redirect_url = handle_basalam_callback(
            settings,
            session,
            basalam_client_factory(),
            code,
            state,
            error,
            error_description,
        )
        return RedirectResponse(redirect_url)

    @app.get("/api/oauth/callback")
    def get_legacy_basalam_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
        session: Session = Depends(get_session),
    ):
        redirect_url = handle_basalam_callback(
            settings,
            session,
            basalam_client_factory(),
            code,
            state,
            error,
            error_description,
        )
        return RedirectResponse(redirect_url)

    @app.get("/batches/{batch_id}/items", response_model=list[BatchItemRead])
    def get_batch_items(batch_id: int, session: Session = Depends(get_session)):
        if not session.get(Batch, batch_id):
            raise HTTPException(status_code=404, detail="Batch not found")
        return list_items(session, batch_id)

    @app.patch("/batch-items/{item_id}", response_model=BatchItemRead)
    def patch_batch_item(
        item_id: int, payload: BatchItemPatch, session: Session = Depends(get_session)
    ):
        return update_item(session, item_id, **payload.model_dump(exclude_unset=True))

    @app.post("/batch-items/merge", response_model=BatchItemRead)
    def post_merge(payload: MergeItemsRequest, session: Session = Depends(get_session)):
        return merge_items(
            session,
            payload.source_item_ids,
            payload.title,
            payload.description,
            payload.price_toman,
        )

    @app.post("/batch-items/split", response_model=BatchItemRead)
    def post_split(payload: SplitItemRequest, session: Session = Depends(get_session)):
        return split_item(
            session,
            payload.item_id,
            payload.asset_ids,
            payload.title,
            payload.description,
            payload.price_toman,
        )

    @app.post("/batch-items/{item_id}/photos/reorder", response_model=BatchItemRead)
    def post_reorder(
        item_id: int, payload: ReorderPhotosRequest, session: Session = Depends(get_session)
    ):
        return reorder_photos(session, item_id, payload.asset_ids)

    @app.get("/batches/{batch_id}/export.json")
    def get_export_json(batch_id: int, session: Session = Depends(get_session)):
        return JSONResponse(export_json(session, batch_id))

    @app.get("/batches/{batch_id}/export.csv")
    def get_export_csv(batch_id: int, session: Session = Depends(get_session)):
        return PlainTextResponse(
            export_csv(session, batch_id),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="batch-{batch_id}.csv"'},
        )

    @app.post("/batches/{batch_id}/publish/basalam", response_model=PublishStartResponse, status_code=202)
    def post_publish_basalam(
        batch_id: int,
        background_tasks: BackgroundTasks,
        workspace_id: str | None = None,
        session: Session = Depends(get_session),
    ):
        job, created = create_basalam_publish_job(session, batch_id, workspace_id)
        if created:
            background_tasks.add_task(
                run_basalam_publish_job,
                settings,
                session_factory,
                app.state.basalam_client_factory,
                job.id,
            )
        return PublishStartResponse(job_id=job.id)

    @app.post("/batches/{batch_id}/torob-submissions", response_model=TorobSubmissionStartResponse, status_code=201)
    def post_torob_submission(
        batch_id: int, payload: TorobSubmissionCreate, session: Session = Depends(get_session)
    ):
        submission = create_torob_submission(session, batch_id, payload.shop_name, payload.contact_mobile)
        return TorobSubmissionStartResponse(
            id=submission.id,
            status=submission.status,
            message="درخواستت ثبت شد. به زودی برای اضافه شدن محصولات به ترب بررسی می‌شود.",
        )

    @app.get("/admin/torob-submissions", response_model=list[TorobSubmissionRead], dependencies=[Depends(require_admin)])
    def get_admin_torob_submissions(status: str | None = None, session: Session = Depends(get_session)):
        return list_torob_submissions(session, status)

    @app.get("/admin/torob-submissions/{submission_id}", response_model=TorobSubmissionRead, dependencies=[Depends(require_admin)])
    def get_admin_torob_submission(submission_id: int, session: Session = Depends(get_session)):
        return get_torob_submission(session, submission_id)

    @app.patch("/admin/torob-submissions/{submission_id}", response_model=TorobSubmissionRead, dependencies=[Depends(require_admin)])
    def patch_admin_torob_submission(
        submission_id: int, payload: TorobSubmissionPatch, session: Session = Depends(get_session)
    ):
        return patch_torob_submission(session, submission_id, payload)

    @app.post("/admin/torob-submissions/{submission_id}/publish", response_model=TorobSubmissionRead, dependencies=[Depends(require_admin)])
    def post_admin_torob_publish(
        submission_id: int, payload: TorobPublishRequest, session: Session = Depends(get_session)
    ):
        return publish_torob_submission(session, torob_client_factory(), submission_id, payload)

    @app.get("/publish-jobs/{job_id}", response_model=PublishJobRead)
    def get_publish_job(job_id: int, session: Session = Depends(get_session)):
        job = session.get(PublishJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Publish job not found")
        return job

    @app.get("/batches/{batch_id}/published-products", response_model=list[PublishedProductRead])
    def get_published_products(batch_id: int, session: Session = Depends(get_session)):
        return list_published_products(session, batch_id)

    if settings.frontend_dist_dir and settings.frontend_dist_dir.exists():
        @app.get("/admin")
        @app.get("/admin/{path:path}")
        def get_admin_frontend(path: str = ""):
            return FileResponse(settings.frontend_dist_dir / "index.html")

        app.mount("/", StaticFiles(directory=Path(settings.frontend_dist_dir), html=True), name="frontend")

    return app


def _asset_to_read(asset: Asset) -> AssetRead:
    return AssetRead(
        id=asset.id,
        batch_id=asset.batch_id,
        type=asset.type,
        upload_order=asset.upload_order,
        original_filename=asset.original_filename,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        checksum=asset.checksum,
        url=f"/files/{asset.batch_id}/{asset.type}/{Path(asset.file_path).name}",
        created_at=asset.created_at,
    )


app = create_app()
