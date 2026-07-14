from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Asset, Batch, ProcessingJob
from app.schemas import AiExtraction, AiProduct
from app.services import _normalize_extracted_price_toman, _price_hint_for_product, _price_hints_from_transcript
from app.services import _replace_items_from_extraction, create_processing_job, run_processing_job
from helpers import audio_file, image_bytes, image_file


def test_short_seller_price_is_normalized_to_toman():
    assert _normalize_extracted_price_toman(None) is None
    assert _normalize_extracted_price_toman(0) is None
    assert _normalize_extracted_price_toman(1) == 1_000_000
    assert _normalize_extracted_price_toman(30) == 30_000
    assert _normalize_extracted_price_toman(150) == 150_000
    assert _normalize_extracted_price_toman(300) == 300_000
    assert _normalize_extracted_price_toman(900) == 900_000
    assert _normalize_extracted_price_toman(30_000) == 30_000


def test_price_hints_are_extracted_from_persian_voice_text():
    transcript = (
        "شماره سه قیمتش سی هزار تومنه. "
        "شماره چهار قیمتش ۹۰۰ تومنه. "
        "اسپیکر قیمتش یک تومنه. "
        "شماره شیش قیمتش صد و پنجاه تومنه. "
        "شماره هفت قیمتش دیویست هزار تومنه."
    )
    hints = _price_hints_from_transcript(transcript)

    assert hints["by_image"] == {3: 30_000, 4: 900_000, 6: 150_000, 7: 200_000}
    assert _price_hint_for_product("اسپیکر بلوتوثی", "", [5], hints) == 1_000_000


def test_seller_data_is_isolated_by_seller(client: TestClient, seller: dict):
    second = client.post(
        "/sellers",
        json={"name": "مریم", "mobile": "09121111111", "shop_name": "فروشگاه دوم"},
    ).json()
    first_batch = client.post("/batches", json={"seller_id": seller["id"]}).json()
    second_batch = client.post("/batches", json={"seller_id": second["id"]}).json()

    first_list = client.get(f"/batches?seller_id={seller['id']}").json()
    second_list = client.get(f"/batches?seller_id={second['id']}").json()

    assert [batch["id"] for batch in first_list] == [first_batch["id"]]
    assert [batch["id"] for batch in second_list] == [second_batch["id"]]


def test_seller_can_be_loaded_by_id(client: TestClient, seller: dict):
    client.post(
        "/sellers",
        json={"name": "مریم", "mobile": "09121111111", "shop_name": "فروشگاه دوم"},
    )

    assert client.get("/sellers").json() == []

    loaded = client.get(f"/sellers/{seller['id']}")

    assert loaded.status_code == 200
    assert loaded.json()["id"] == seller["id"]
    assert client.get("/sellers/999999").status_code == 404


def test_upload_order_stays_stable_for_images(client: TestClient, batch: dict):
    response = client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg")],
    )

    assert response.status_code == 201
    assert [asset["upload_order"] for asset in response.json()] == [1, 2, 3]

    assets = client.get(f"/batches/{batch['id']}/assets").json()
    image_orders = [asset["upload_order"] for asset in assets if asset["type"] == "image"]
    assert image_orders == [1, 2, 3]


def test_upload_normalizes_image_content_and_mime_on_the_server(client: TestClient, batch: dict):
    from io import BytesIO

    from PIL import Image

    png = BytesIO()
    Image.new("RGBA", (48, 36), (20, 130, 110, 100)).save(png, format="PNG")

    response = client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("iphone.heic", png.getvalue(), "image/heic")],
    )

    assert response.status_code == 201
    asset = response.json()[0]
    assert asset["mime_type"] == "image/jpeg"
    assert asset["url"].endswith(".jpg")
    stored = client.get(asset["url"])
    assert stored.status_code == 200
    assert stored.headers["content-type"].startswith("image/jpeg")
    with Image.open(BytesIO(stored.content)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"


def test_upload_accepts_real_heic_even_when_browser_omits_mime(client: TestClient, batch: dict):
    from io import BytesIO

    from PIL import Image
    from pillow_heif import from_pillow

    heic = BytesIO()
    from_pillow(Image.new("RGB", (64, 48), "red")).save(heic)

    response = client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("iphone.heic", heic.getvalue(), "application/octet-stream")],
    )

    assert response.status_code == 201
    asset = response.json()[0]
    assert asset["mime_type"] == "image/jpeg"
    assert asset["url"].endswith(".jpg")


def test_multi_image_upload_is_atomic_when_one_image_is_unreadable(client: TestClient, batch: dict):
    response = client.post(
        f"/batches/{batch['id']}/assets",
        files=[
            image_file("valid.jpg"),
            image_file("broken.jpg", b"not-an-image"),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "این عکس خوانده نشد. یک عکس سالم انتخاب کن و دوباره تلاش کن."
    assert client.get(f"/batches/{batch['id']}/assets").json() == []


def test_uploaded_image_can_be_deleted_before_processing(client: TestClient, batch: dict):
    uploaded = client.post(
        f"/batches/{batch['id']}/assets",
        files=[
            image_file("a.jpg", image_bytes((220, 20, 20))),
            image_file("b.jpg", image_bytes((20, 220, 20))),
            image_file("c.jpg", image_bytes((20, 20, 220))),
        ],
    ).json()

    response = client.delete(f"/assets/{uploaded[0]['id']}")

    assert response.status_code == 204
    assets = client.get(f"/batches/{batch['id']}/assets").json()
    assert [asset["id"] for asset in assets] == [uploaded[1]["id"], uploaded[2]["id"]]
    assert [asset["upload_order"] for asset in assets] == [1, 2]


def test_reupload_after_delete_does_not_overwrite_renumbered_photo_file(client: TestClient, batch: dict):
    uploaded = client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg", image_bytes((220, 20, 20))), image_file("b.jpg", image_bytes((20, 220, 20)))],
    ).json()
    client.delete(f"/assets/{uploaded[0]['id']}")

    reuploaded = client.post(
        f"/batches/{batch['id']}/assets", files=[image_file("c.jpg", image_bytes((20, 20, 220)))]
    ).json()[0]

    assert reuploaded["upload_order"] == 2
    assets = client.get(f"/batches/{batch['id']}/assets").json()
    assert [asset["upload_order"] for asset in assets] == [1, 2]
    session = client.app.state.session_factory()
    try:
        db_assets = session.scalars(
            select(Asset).where(Asset.batch_id == batch["id"], Asset.type == "image").order_by(Asset.upload_order)
        ).all()
        assert len({asset.file_path for asset in db_assets}) == 2
        from PIL import Image

        with Image.open(db_assets[0].file_path) as second:
            second_pixel = second.getpixel((0, 0))
        with Image.open(db_assets[1].file_path) as third:
            third_pixel = third.getpixel((0, 0))
        assert second_pixel[1] > second_pixel[0] and second_pixel[1] > second_pixel[2]
        assert third_pixel[2] > third_pixel[0] and third_pixel[2] > third_pixel[1]
    finally:
        session.close()


def test_uploaded_image_delete_is_rejected_after_it_is_linked_to_product(client: TestClient, batch: dict):
    uploaded = client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")]).json()
    client.post(f"/batches/{batch['id']}/process")

    response = client.delete(f"/assets/{uploaded[0]['id']}")

    assert response.status_code == 422
    assert response.json()["detail"] == "Asset is already attached to a product"


def test_processing_requires_at_least_one_product_image(client: TestClient, batch: dict):
    client.post(f"/batches/{batch['id']}/assets", files=[audio_file()])

    process = client.post(f"/batches/{batch['id']}/process")

    assert process.status_code == 422
    assert process.json()["detail"] == "At least one product image is required"
    assert client.get(f"/batches/{batch['id']}/items").json() == []


def test_processing_reuses_active_job_and_allows_reprocess_after_terminal_state(client: TestClient, batch: dict):
    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    session = client.app.state.session_factory()
    try:
        first_job, first_created = create_processing_job(session, batch["id"])
        second_job, second_created = create_processing_job(session, batch["id"])

        assert first_created is True
        assert second_created is False
        assert second_job.id == first_job.id
        assert len(session.scalars(select(ProcessingJob).where(ProcessingJob.batch_id == batch["id"])).all()) == 1

        first_job.status = "succeeded"
        first_job.step = "ready"
        session.commit()

        reprocess_job, reprocess_created = create_processing_job(session, batch["id"])

        assert reprocess_created is True
        assert reprocess_job.id != first_job.id
        assert len(session.scalars(select(ProcessingJob).where(ProcessingJob.batch_id == batch["id"])).all()) == 2
    finally:
        session.close()


def test_processing_retries_temporary_ai_failures_and_records_attempts(client: TestClient, batch: dict):
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), audio_file()],
    )

    class FlakyProvider:
        def __init__(self):
            self.transcription_calls = 0
            self.extraction_calls = 0

        def transcribe(self, _audio):
            self.transcription_calls += 1
            if self.transcription_calls == 1:
                raise TimeoutError("temporary transcription timeout")
            return "قیمت محصول صد هزار تومان است"

        def extract_products(self, _images, transcript):
            self.extraction_calls += 1
            if self.extraction_calls == 1:
                raise RuntimeError("AI returned invalid extraction JSON")
            return AiExtraction(
                transcript=transcript,
                products=[
                    AiProduct(
                        title="محصول بازیابی‌شده",
                        description="توضیحات محصول",
                        price_toman=100_000,
                        stock=None,
                        preparation_days=None,
                        weight_grams=None,
                        package_weight_grams=None,
                        unit_quantity=None,
                        confidence=0.9,
                        image_numbers=[1],
                    )
                ],
                metadata={"provider": "test"},
            )

    provider = FlakyProvider()
    session = client.app.state.session_factory()
    try:
        job, _ = create_processing_job(session, batch["id"])
    finally:
        session.close()

    run_processing_job(
        client.app.state.session_factory,
        lambda: provider,
        job.id,
        sleep_fn=lambda _seconds: None,
    )

    saved_job = client.get(f"/jobs/{job.id}").json()
    saved_batch = client.get(f"/batches/{batch['id']}").json()
    assert saved_job["status"] == "succeeded"
    assert provider.transcription_calls == 2
    assert provider.extraction_calls == 2
    assert saved_batch["ai_metadata"]["processing_attempts"] == {
        "transcription": 2,
        "extraction": 2,
    }


def test_processing_failure_is_safe_and_observable_without_losing_uploads(
    client: TestClient, batch: dict, caplog
):
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), audio_file()],
    )

    class BrokenProvider:
        def transcribe(self, _audio):
            raise TimeoutError("upstream secret diagnostic")

        def extract_products(self, _images, _transcript):
            raise AssertionError("extraction must not run")

    session = client.app.state.session_factory()
    try:
        job, _ = create_processing_job(session, batch["id"])
    finally:
        session.close()

    run_processing_job(
        client.app.state.session_factory,
        BrokenProvider,
        job.id,
        sleep_fn=lambda _seconds: None,
    )

    saved_job = client.get(f"/jobs/{job.id}").json()
    saved_batch = client.get(f"/batches/{batch['id']}").json()
    saved_assets = client.get(f"/batches/{batch['id']}/assets").json()
    failure = saved_batch["ai_metadata"]["last_processing_failure"]
    assert saved_job["status"] == "failed"
    assert saved_job["error"] == "ارتباط با هوش مصنوعی موقتاً برقرار نشد. دوباره تلاش کن."
    assert "secret" not in saved_job["error"]
    assert failure == {
        "code": "provider_temporary",
        "stage": "transcribing",
        "attempts": 3,
        "exception_type": "TimeoutError",
    }
    assert sorted(asset["type"] for asset in saved_assets) == ["audio", "image"]
    assert "processing_job_failed job_id=" in caplog.text
    assert "stage=transcribing code=provider_temporary attempts=3" in caplog.text


def test_processing_without_voice_reports_an_unreadable_image_and_keeps_uploads(
    client: TestClient, batch: dict
):
    uploaded = client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")]).json()[0]
    session = client.app.state.session_factory()
    try:
        asset = session.get(Asset, uploaded["id"])
        assert asset is not None
        asset_path = asset.file_path
        job, _ = create_processing_job(session, batch["id"])
    finally:
        session.close()
    Path(asset_path).write_bytes(b"damaged-after-upload")

    from types import SimpleNamespace

    from app.ai import AvalAiProvider
    from app.config import Settings

    provider = AvalAiProvider(Settings(AVALAI_API_KEY="test-key"))
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: pytest.fail("provider must not be called"))
        )
    )

    run_processing_job(
        client.app.state.session_factory,
        lambda: provider,
        job.id,
        sleep_fn=lambda _seconds: None,
    )

    saved_job = client.get(f"/jobs/{job.id}").json()
    saved_batch = client.get(f"/batches/{batch['id']}").json()
    saved_assets = client.get(f"/batches/{batch['id']}/assets").json()
    assert saved_job["status"] == "failed"
    assert saved_job["error"] == "یکی از عکس‌ها خوانده نشد. آن عکس را حذف کن، دوباره اضافه کن و تلاش کن."
    assert saved_batch["ai_metadata"]["last_processing_failure"] == {
        "code": "image_invalid",
        "stage": "vision_extracting",
        "attempts": 1,
        "exception_type": "InvalidProductImageError",
        "image_number": 1,
    }
    assert len(saved_assets) == 1


def test_fake_processing_creates_editable_items_and_exports(client: TestClient, batch: dict):
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg"), audio_file()],
    )

    process = client.post(f"/batches/{batch['id']}/process")
    assert process.status_code == 202

    job = client.get(f"/jobs/{process.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert job["step"] == "ready"

    items = client.get(f"/batches/{batch['id']}/items").json()
    assert len(items) == 2
    assert [photo["upload_order"] for photo in items[0]["photos"]] == [1, 2]
    assert items[0]["price_toman"] == 123000

    patched = client.patch(
        f"/batch-items/{items[0]['id']}",
        json={"title": "عنوان اصلاح شده", "description": "توضیح اصلاحی", "price_toman": 456000},
    ).json()
    assert patched["edited_by_user"] is True
    assert patched["title"] == "عنوان اصلاح شده"

    exported_json = client.get(f"/batches/{batch['id']}/export.json").json()
    assert exported_json["batch"]["transcript"]
    assert exported_json["items"][0]["photos"][0]["asset_id"]

    exported_csv = client.get(f"/batches/{batch['id']}/export.csv").text
    assert "seller_name,seller_mobile,shop_name,batch_id,item_id,title" in exported_csv
    assert "عنوان اصلاح شده" in exported_csv


def test_operational_fields_from_voice_extraction_are_saved(client: TestClient, batch: dict):
    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    session = client.app.state.session_factory()
    try:
        batch_model = session.get(Batch, batch["id"])
        images = session.scalars(select(Asset).where(Asset.batch_id == batch["id"], Asset.type == "image")).all()
        _replace_items_from_extraction(
            session,
            batch_model,
            images,
            AiExtraction(
                transcript="موجودی ۵ تا، آماده سازی ۲ روز، وزن محصول ۳۰۰ گرم، وزن با بسته بندی ۵۰۰ گرم.",
                products=[
                    AiProduct(
                        title="محصول با اطلاعات کامل",
                        description="توضیح",
                        price_toman=300_000,
                        stock=5,
                        preparation_days=2,
                        weight_grams=300,
                        package_weight_grams=500,
                        unit_quantity=1,
                        confidence=0.9,
                        image_numbers=[1],
                    )
                ],
                metadata={},
            ),
        )
        session.commit()
    finally:
        session.close()

    saved = client.get(f"/batches/{batch['id']}/items").json()[0]

    assert saved["stock"] == 5
    assert saved["preparation_days"] == 2
    assert saved["weight_grams"] == 300
    assert saved["package_weight_grams"] == 500
    assert saved["unit_quantity"] == 1


def test_reprocess_merges_voice_extraction_without_dropping_existing_items(client: TestClient, batch: dict):
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg")],
    )
    session = client.app.state.session_factory()
    try:
        batch_model = session.get(Batch, batch["id"])
        images = session.scalars(select(Asset).where(Asset.batch_id == batch["id"], Asset.type == "image")).all()
        _replace_items_from_extraction(
            session,
            batch_model,
            images,
            AiExtraction(
                transcript=None,
                products=[
                    AiProduct(
                        title="محصول اول AI",
                        description="توضیح اول",
                        price_toman=100_000,
                        stock=None,
                        preparation_days=None,
                        weight_grams=None,
                        package_weight_grams=None,
                        unit_quantity=None,
                        confidence=0.8,
                        image_numbers=[1],
                    ),
                    AiProduct(
                        title="محصول دوم AI",
                        description="توضیح دوم",
                        price_toman=200_000,
                        stock=None,
                        preparation_days=None,
                        weight_grams=None,
                        package_weight_grams=None,
                        unit_quantity=None,
                        confidence=0.8,
                        image_numbers=[2],
                    ),
                ],
                metadata={},
            ),
        )
        session.commit()
    finally:
        session.close()

    initial_items = client.get(f"/batches/{batch['id']}/items").json()
    first_id = initial_items[0]["id"]
    second_id = initial_items[1]["id"]
    client.patch(
        f"/batch-items/{first_id}",
        json={"title": "نام دستی فروشنده", "description": "توضیح دستی فروشنده"},
    )

    session = client.app.state.session_factory()
    try:
        batch_model = session.get(Batch, batch["id"])
        images = session.scalars(select(Asset).where(Asset.batch_id == batch["id"], Asset.type == "image")).all()
        _replace_items_from_extraction(
            session,
            batch_model,
            images,
            AiExtraction(
                transcript="موجودی محصول اول ۸ تاست.",
                products=[
                    AiProduct(
                        title="نام جدید AI",
                        description="توضیح جدید AI",
                        price_toman=None,
                        stock=8,
                        preparation_days=2,
                        weight_grams=None,
                        package_weight_grams=None,
                        unit_quantity=None,
                        confidence=0.91,
                        image_numbers=[1],
                    )
                ],
                metadata={},
            ),
        )
        session.commit()
    finally:
        session.close()

    saved_items = client.get(f"/batches/{batch['id']}/items").json()
    assert [item["id"] for item in saved_items] == [first_id, second_id]
    assert saved_items[0]["title"] == "نام دستی فروشنده"
    assert saved_items[0]["description"] == "توضیح دستی فروشنده"
    assert saved_items[0]["price_toman"] == 100_000
    assert saved_items[0]["stock"] == 8
    assert saved_items[0]["preparation_days"] == 2
    assert saved_items[1]["title"] == "محصول دوم AI"
    assert saved_items[1]["price_toman"] == 200_000


def test_merge_split_and_reorder(client: TestClient, batch: dict):
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg")],
    )
    client.post(f"/batches/{batch['id']}/process")
    items = client.get(f"/batches/{batch['id']}/items").json()
    first, second = items

    merged = client.post(
        "/batch-items/merge",
        json={
            "source_item_ids": [first["id"], second["id"]],
            "title": "محصول ادغام‌شده",
            "description": "همه عکس‌ها در یک محصول",
            "price_toman": 999,
        },
    ).json()
    assert len(merged["photos"]) == 3

    reordered = client.post(
        f"/batch-items/{merged['id']}/photos/reorder",
        json={"asset_ids": [merged["photos"][2]["asset_id"], merged["photos"][1]["asset_id"], merged["photos"][0]["asset_id"]]},
    ).json()
    assert [photo["sort_order"] for photo in reordered["photos"]] == [1, 2, 3]
    assert reordered["photos"][0]["asset_id"] == merged["photos"][2]["asset_id"]

    split = client.post(
        "/batch-items/split",
        json={
            "item_id": merged["id"],
            "asset_ids": [reordered["photos"][0]["asset_id"]],
            "title": "محصول جدا",
            "description": "یک عکس جدا شد",
            "price_toman": None,
        },
    ).json()
    assert split["title"] == "محصول جدا"
    assert len(split["photos"]) == 1
