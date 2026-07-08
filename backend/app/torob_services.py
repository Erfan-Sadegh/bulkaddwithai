from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from .integrations.torob import TorobBulkItem, TorobClient, TorobClientError
from .models import Batch, BatchItem, BatchItemAsset, TorobSubmission, TorobSubmissionItem, utc_now
from .schemas import (
    TorobPublishRequest,
    TorobSubmissionItemRead,
    TorobSubmissionPatch,
    TorobSubmissionRead,
)


def create_torob_submission(
    session: Session, batch_id: int, shop_name: str, contact_mobile: str
) -> TorobSubmissionRead:
    batch = session.scalar(_batch_for_torob_statement(batch_id))
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not batch.items:
        raise HTTPException(status_code=422, detail="No ready products found")
    shop_name = shop_name.strip()
    contact_mobile = contact_mobile.strip()
    if not shop_name or not contact_mobile:
        raise HTTPException(status_code=422, detail="اطلاعات فروشگاه ترب کامل نیست")
    submission = TorobSubmission(
        seller_id=batch.seller_id,
        batch_id=batch.id,
        shop_name=shop_name,
        contact_mobile=contact_mobile,
        status="pending",
    )
    session.add(submission)
    session.flush()
    for item in batch.items:
        submission.items.append(
            TorobSubmissionItem(
                batch_item_id=item.id,
                price=item.price_toman,
                status="pending",
            )
        )
    session.commit()
    return _submission_to_read(session.scalar(_submission_statement(submission.id)))


def list_torob_submissions(session: Session, status: str | None = None) -> list[TorobSubmissionRead]:
    statement = select(TorobSubmission).options(_submission_options()).order_by(TorobSubmission.created_at.desc())
    if status:
        statement = statement.where(TorobSubmission.status == status)
    return [_submission_to_read(submission) for submission in session.scalars(statement).all()]


def get_torob_submission(session: Session, submission_id: int) -> TorobSubmissionRead:
    submission = session.scalar(_submission_statement(submission_id))
    if not submission:
        raise HTTPException(status_code=404, detail="Torob submission not found")
    return _submission_to_read(submission)


def patch_torob_submission(
    session: Session, submission_id: int, payload: TorobSubmissionPatch
) -> TorobSubmissionRead:
    submission = session.scalar(_submission_statement(submission_id))
    if not submission:
        raise HTTPException(status_code=404, detail="Torob submission not found")
    if payload.shop_id is not None:
        submission.shop_id = payload.shop_id
    if payload.admin_note is not None:
        submission.admin_note = payload.admin_note
    item_by_id = {item.id: item for item in submission.items}
    for item_patch in payload.items or []:
        item = item_by_id.get(item_patch.id)
        if not item:
            raise HTTPException(status_code=422, detail="Torob item does not belong to this submission")
        if item_patch.base_product_rk is not None:
            item.base_product_rk = item_patch.base_product_rk.strip() or None
        if item_patch.price is not None:
            item.price = item_patch.price
    session.commit()
    return _submission_to_read(session.scalar(_submission_statement(submission.id)))


def publish_torob_submission(
    session: Session, client: TorobClient, submission_id: int, payload: TorobPublishRequest
) -> TorobSubmissionRead:
    submission = session.scalar(_submission_statement(submission_id))
    if not submission:
        raise HTTPException(status_code=404, detail="Torob submission not found")
    if len(payload.items) > 100:
        raise HTTPException(status_code=422, detail="Torob bulk add supports at most 100 items per request")

    item_by_id = {item.id: item for item in submission.items}
    bulk_items: list[TorobBulkItem] = []
    selected_ids: set[int] = set()
    for payload_item in payload.items:
        item = item_by_id.get(payload_item.id)
        if not item:
            raise HTTPException(status_code=422, detail="Torob item does not belong to this submission")
        selected_ids.add(item.id)
        item.base_product_rk = payload_item.base_product_rk.strip()
        item.price = payload_item.price
        item.status = "pending"
        item.error = None
        bulk_items.append(TorobBulkItem(base_product_rk=item.base_product_rk, price=item.price))

    submission.shop_id = payload.shop_id
    submission.status = "submitting"
    submission.error = None
    session.commit()

    try:
        response = client.bulk_add(payload.shop_id, bulk_items)
    except TorobClientError as exc:
        submission.status = "failed"
        submission.error = "ارسال به ترب انجام نشد. تنظیمات یا پاسخ ترب را بررسی کن."
        submission.response_metadata = {"technical_error": str(exc)}
        for item_id in selected_ids:
            item_by_id[item_id].status = "failed"
            item_by_id[item_id].error = "ثبت در ترب انجام نشد."
        session.commit()
        return _submission_to_read(session.scalar(_submission_statement(submission.id)))

    submission.status = "submitted"
    submission.submitted_at = utc_now()
    submission.response_metadata = response
    for item_id in selected_ids:
        item_by_id[item_id].status = "submitted"
        item_by_id[item_id].error = None
        item_by_id[item_id].response_metadata = response
    session.commit()
    return _submission_to_read(session.scalar(_submission_statement(submission.id)))


def _batch_for_torob_statement(batch_id: int) -> Select:
    return (
        select(Batch)
        .where(Batch.id == batch_id)
        .options(
            selectinload(Batch.items)
            .selectinload(BatchItem.asset_links)
            .selectinload(BatchItemAsset.asset)
        )
    )


def _submission_options():
    return (
        selectinload(TorobSubmission.items)
        .selectinload(TorobSubmissionItem.batch_item)
        .selectinload(BatchItem.asset_links)
        .selectinload(BatchItemAsset.asset)
    )


def _submission_statement(submission_id: int) -> Select:
    return select(TorobSubmission).where(TorobSubmission.id == submission_id).options(_submission_options())


def _submission_to_read(submission: TorobSubmission) -> TorobSubmissionRead:
    return TorobSubmissionRead(
        id=submission.id,
        seller_id=submission.seller_id,
        batch_id=submission.batch_id,
        shop_name=submission.shop_name,
        contact_mobile=submission.contact_mobile,
        status=submission.status,
        shop_id=submission.shop_id,
        admin_note=submission.admin_note,
        error=submission.error,
        response_metadata=submission.response_metadata,
        items=[_submission_item_to_read(item) for item in submission.items],
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


def _submission_item_to_read(item: TorobSubmissionItem) -> TorobSubmissionItemRead:
    batch_item = item.batch_item
    links = sorted(batch_item.asset_links, key=lambda link: link.sort_order)
    return TorobSubmissionItemRead(
        id=item.id,
        batch_item_id=batch_item.id,
        title=batch_item.title,
        description=batch_item.description,
        price=item.price,
        base_product_rk=item.base_product_rk,
        candidates=_torob_candidates(item),
        status=item.status,
        error=item.error,
        image_numbers=[link.asset.upload_order for link in links],
        image_urls=[_asset_url(link.asset) for link in links],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _torob_candidates(item: TorobSubmissionItem) -> list[dict]:
    metadata = item.response_metadata or {}
    raw_candidates = metadata.get("candidates", []) if isinstance(metadata, dict) else []
    if not isinstance(raw_candidates, list):
        return []
    candidates: list[dict] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            continue
        base_product_rk = str(candidate.get("base_product_rk") or "").strip()
        title = str(candidate.get("title") or "").strip()
        if not base_product_rk or not title:
            continue
        score = candidate.get("score")
        candidates.append(
            {
                "base_product_rk": base_product_rk,
                "title": title,
                "subtitle": candidate.get("subtitle"),
                "image_url": candidate.get("image_url"),
                "price_text": candidate.get("price_text"),
                "source": str(candidate.get("source") or "torob"),
                "score": float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
            }
        )
    return candidates[:8]


def _asset_url(asset) -> str:
    return f"/files/{asset.batch_id}/{asset.type}/{Path(asset.file_path).name}"
