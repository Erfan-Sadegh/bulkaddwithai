from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Asset, Batch
from app.schemas import AiExtraction, AiProduct
from app.services import _normalize_extracted_price_toman, _price_hint_for_product, _price_hints_from_transcript
from app.services import _replace_items_from_extraction
from helpers import audio_file, image_file


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
