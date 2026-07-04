from collections.abc import Generator
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .ai import get_ai_provider
from .config import Settings, get_settings
from .database import create_tables, make_engine, make_session_factory
from .models import Asset, Batch, ProcessingJob, Seller
from .schemas import (
    AssetRead,
    BatchCreate,
    BatchItemPatch,
    BatchItemRead,
    BatchRead,
    JobRead,
    MergeItemsRequest,
    ProcessStartResponse,
    ReorderPhotosRequest,
    SellerCreate,
    SellerPatch,
    SellerRead,
    SplitItemRequest,
)
from .services import (
    create_batch,
    create_processing_job,
    create_seller,
    export_csv,
    export_json,
    list_items,
    merge_items,
    reorder_photos,
    run_processing_job,
    split_item,
    store_upload,
    update_item,
    update_seller,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    create_tables(engine)

    app = FastAPI(title="Bulk Add With AI", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/sellers", response_model=SellerRead, status_code=201)
    def post_seller(payload: SellerCreate, session: Session = Depends(get_session)):
        return create_seller(session, payload.name, payload.mobile, payload.shop_name)

    @app.get("/sellers", response_model=list[SellerRead])
    def get_sellers(session: Session = Depends(get_session)):
        return session.scalars(select(Seller).order_by(Seller.created_at.desc())).all()

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
        assets = [store_upload(settings, session, batch_id, file) for file in files]
        return [_asset_to_read(asset) for asset in assets]

    @app.get("/batches/{batch_id}/assets", response_model=list[AssetRead])
    def get_assets(batch_id: int, session: Session = Depends(get_session)):
        assets = session.scalars(
            select(Asset).where(Asset.batch_id == batch_id).order_by(Asset.type, Asset.upload_order)
        ).all()
        return [_asset_to_read(asset) for asset in assets]

    @app.post("/batches/{batch_id}/process", response_model=ProcessStartResponse, status_code=202)
    def post_process(
        batch_id: int,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_session),
    ):
        job = create_processing_job(session, batch_id)
        background_tasks.add_task(run_processing_job, session_factory, provider_factory, job.id)
        return ProcessStartResponse(job_id=job.id)

    @app.get("/jobs/{job_id}", response_model=JobRead)
    def get_job(job_id: int, session: Session = Depends(get_session)):
        job = session.get(ProcessingJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

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

    if settings.frontend_dist_dir and settings.frontend_dist_dir.exists():
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
