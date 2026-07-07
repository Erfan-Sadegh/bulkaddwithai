from fastapi.testclient import TestClient

from app.integrations.torob import TorobBulkItem
from helpers import image_file


class FakeTorobClient:
    def __init__(self):
        self.calls: list[tuple[int, list[TorobBulkItem]]] = []

    def bulk_add(self, shop_id: int, items: list[TorobBulkItem]) -> dict:
        self.calls.append((shop_id, items))
        return {
            "ok": True,
            "shop_id": shop_id,
            "items": [
                {"base_product_rk": item.base_product_rk, "price": item.price}
                for item in items
            ],
        }


def _ready_batch(client: TestClient, batch: dict) -> list[dict]:
    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg")],
    )
    client.post(f"/batches/{batch['id']}/process")
    return client.get(f"/batches/{batch['id']}/items").json()


def test_torob_submission_is_created_for_admin_review(client: TestClient, batch: dict):
    client.app.state.settings.admin_password = "admin-pass"
    items = _ready_batch(client, batch)

    created = client.post(
        f"/batches/{batch['id']}/torob-submissions",
        json={"shop_name": "فروشگاه ترب", "contact_mobile": "09120000000"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    assert "درخواستت ثبت شد" in created.json()["message"]

    assert client.get("/admin/torob-submissions").status_code == 401
    assert client.post("/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/admin/login", json={"password": "admin-pass"}).json() == {"ok": True}

    listed = client.get(
        "/admin/torob-submissions",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()

    assert len(listed) == 1
    submission = listed[0]
    assert submission["shop_name"] == "فروشگاه ترب"
    assert submission["contact_mobile"] == "09120000000"
    assert submission["batch_id"] == batch["id"]
    assert [item["batch_item_id"] for item in submission["items"]] == [item["id"] for item in items]
    assert submission["items"][0]["image_numbers"] == [1, 2]
    assert submission["items"][0]["price"] == items[0]["price_toman"]


def test_admin_can_publish_torob_submission_with_manual_product_ids(client: TestClient, batch: dict):
    client.app.state.settings.admin_password = "admin-pass"
    fake = FakeTorobClient()
    client.app.state.torob_client_factory = lambda _settings: fake
    _ready_batch(client, batch)
    submission = client.post(
        f"/batches/{batch['id']}/torob-submissions",
        json={"shop_name": "فروشگاه ترب", "contact_mobile": "09120000000"},
    ).json()
    first_item = client.get(
        f"/admin/torob-submissions/{submission['id']}",
        headers={"X-Admin-Password": "admin-pass"},
    ).json()["items"][0]

    published = client.post(
        f"/admin/torob-submissions/{submission['id']}/publish",
        headers={"X-Admin-Password": "admin-pass"},
        json={
            "shop_id": 94925,
            "items": [
                {
                    "id": first_item["id"],
                    "base_product_rk": "2809dddc-a7d8-4d71-b28e-0591b146b6c7",
                    "price": 999000000,
                }
            ],
        },
    )

    assert published.status_code == 200
    body = published.json()
    assert body["status"] == "submitted"
    assert body["shop_id"] == 94925
    assert body["items"][0]["status"] == "submitted"
    assert body["items"][0]["base_product_rk"] == "2809dddc-a7d8-4d71-b28e-0591b146b6c7"
    assert fake.calls == [
        (
            94925,
            [
                TorobBulkItem(
                    base_product_rk="2809dddc-a7d8-4d71-b28e-0591b146b6c7",
                    price=999000000,
                )
            ],
        )
    ]
