from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.integrations.basalam import BasalamClientError, BasalamProductPayload, BasalamUploadedFile
from app.models import PlatformConnection, PublishJob
from app.platform_services import create_basalam_publish_job
from helpers import image_file


class FakeBasalamClient:
    def __init__(self):
        self.uploaded_paths: list[str] = []
        self.created_products: list[BasalamProductPayload] = []
        self.refreshed = False

    @property
    def is_configured(self) -> bool:
        return True

    def get_authorization_url(self, state: str) -> str:
        return f"https://basalam.test/accounts/sso?client_id=test-client&state={state}"

    def exchange_code_for_tokens(self, code: str) -> dict:
        assert code == "valid-code"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "vendor.profile.read vendor.product.write",
        }

    def get_current_user(self, access_token: str) -> dict:
        assert access_token == "access-token"
        return {
            "id": 42,
            "mobile": "09120000000",
            "vendor": {
                "id": 476077,
                "identifier": "test-shop",
                "title": "غرفه تست",
            },
        }

    def refresh_tokens(self, refresh_token: str) -> dict:
        self.refreshed = True
        return {
            "access_token": "new-access-token",
            "refresh_token": refresh_token,
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def upload_product_photo(self, connection: PlatformConnection, path: str, mime_type: str) -> BasalamUploadedFile:
        self.uploaded_paths.append(path)
        return BasalamUploadedFile(id=1000 + len(self.uploaded_paths), raw={"path": path, "mime_type": mime_type})

    def get_categories(self) -> dict:
        return {
            "data": [
                {
                    "id": 10,
                    "title": "کالای دیجیتال",
                    "children": [
                        {
                            "id": 20,
                            "title": "گروه شده",
                            "max_preparation_days": 7,
                            "unit_type": {"id": 6304, "title": "عددی"},
                            "children": [],
                        },
                        {
                            "id": 21,
                            "title": "عکس",
                            "max_preparation_days": 5,
                            "unit_type": {"id": 6304, "title": "عددی"},
                            "children": [],
                        },
                        {
                            "id": 22,
                            "title": "بدون واحد",
                            "max_preparation_days": 7,
                            "children": [],
                        },
                        {
                            "id": 23,
                            "title": "واحد وزنی",
                            "max_preparation_days": 7,
                            "unit_type": {"id": 6305, "title": "کیلوگرم"},
                            "children": [],
                        },
                    ],
                }
            ]
        }

    def create_product(
        self,
        connection: PlatformConnection,
        payload: BasalamProductPayload,
    ) -> dict:
        self.created_products.append(payload)
        return {"id": 9000 + len(self.created_products), "url": f"https://basalam.com/p/{9000 + len(self.created_products)}"}


def test_basalam_oauth_url_and_callback_create_platform_connection(client: TestClient, seller: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    url_response = client.get(f"/integrations/basalam/oauth-url?seller_id={seller['id']}")

    assert url_response.status_code == 200
    oauth_url = url_response.json()["url"]
    assert oauth_url.startswith("https://basalam.test/accounts/sso")
    assert "state=" in oauth_url

    state = oauth_url.split("state=", 1)[1]
    callback = client.get(f"/integrations/basalam/callback?code=valid-code&state={state}", follow_redirects=False)

    assert callback.status_code == 307
    assert "basalam_status=success" in callback.headers["location"]

    connections = client.get(f"/sellers/{seller['id']}/platform-connections").json()
    assert len(connections) == 1
    assert connections[0]["platform"] == "basalam"
    assert connections[0]["external_shop_id"] == "476077"
    assert connections[0]["external_shop_name"] == "غرفه تست"


def test_basalam_connection_is_scoped_to_workspace(client: TestClient, seller: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    state = client.get(f"/integrations/basalam/oauth-url?seller_id={seller['id']}&workspace_id=phone").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={state}", follow_redirects=False)

    phone_connections = client.get(f"/sellers/{seller['id']}/platform-connections?workspace_id=phone").json()
    laptop_connections = client.get(f"/sellers/{seller['id']}/platform-connections?workspace_id=laptop").json()

    assert len(phone_connections) == 1
    assert laptop_connections == []


def test_basalam_publish_requires_matching_workspace_connection(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 20})
    state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}&workspace_id=phone").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam?workspace_id=laptop")

    assert publish.status_code == 422
    assert publish.json()["detail"] == "Basalam booth is not connected"
    assert fake.created_products == []


def test_basalam_oauth_callback_connects_each_seller_to_its_own_booth(client: TestClient, seller: dict):
    class MultiVendorBasalamClient(FakeBasalamClient):
        vendors = {
            "seller-one-code": {"id": 111, "identifier": "shop-one", "title": "غرفه اول"},
            "seller-two-code": {"id": 222, "identifier": "shop-two", "title": "غرفه دوم"},
        }

        def exchange_code_for_tokens(self, code: str) -> dict:
            assert code in self.vendors
            return {
                "access_token": f"access-token:{code}",
                "refresh_token": f"refresh-token:{code}",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "vendor.profile.read vendor.product.write",
            }

        def get_current_user(self, access_token: str) -> dict:
            code = access_token.split(":", 1)[1]
            return {
                "id": 7000 + self.vendors[code]["id"],
                "mobile": f"0912{self.vendors[code]['id']}",
                "vendor": self.vendors[code],
            }

    second_seller = client.post(
        "/sellers",
        json={"name": "فروشنده دوم", "mobile": "09120000002", "shop_name": "فروشگاه دوم"},
    ).json()
    fake = MultiVendorBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    first_state = client.get(f"/integrations/basalam/oauth-url?seller_id={seller['id']}").json()["state"]
    second_state = client.get(f"/integrations/basalam/oauth-url?seller_id={second_seller['id']}").json()["state"]

    client.get(
        f"/integrations/basalam/callback?code=seller-one-code&state={first_state}",
        follow_redirects=False,
    )
    client.get(
        f"/integrations/basalam/callback?code=seller-two-code&state={second_state}",
        follow_redirects=False,
    )

    first_connections = client.get(f"/sellers/{seller['id']}/platform-connections").json()
    second_connections = client.get(f"/sellers/{second_seller['id']}/platform-connections").json()

    assert [(connection["external_shop_id"], connection["external_shop_name"]) for connection in first_connections] == [
        ("111", "غرفه اول")
    ]
    assert [(connection["external_shop_id"], connection["external_shop_name"]) for connection in second_connections] == [
        ("222", "غرفه دوم")
    ]
    assert client.get(f"/sellers/{seller['id']}").json()["shop_name"] == "غرفه اول"
    assert client.get(f"/sellers/{second_seller['id']}").json()["shop_name"] == "غرفه دوم"


def test_basalam_oauth_url_reports_unconfigured_without_503(client: TestClient, seller: dict):
    client.app.state.settings.basalam_client_id = None
    client.app.state.settings.basalam_client_secret = None
    client.app.state.settings.basalam_redirect_uri = None

    response = client.get(f"/integrations/basalam/oauth-url?seller_id={seller['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "url": None,
        "state": None,
        "error": "اتصال باسلام در این محیط تنظیم نشده است.",
    }


def test_basalam_callback_with_invalid_state_does_not_create_connection(client: TestClient, seller: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    callback = client.get("/integrations/basalam/callback?code=valid-code&state=invalid-state", follow_redirects=False)

    assert callback.status_code == 307
    assert "basalam_status=failed" in callback.headers["location"]
    assert "error=invalid_state" in callback.headers["location"]
    assert client.get(f"/sellers/{seller['id']}/platform-connections").json() == []


def test_basalam_category_search_and_manual_item_category_selection(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake

    search = client.get("/integrations/basalam/categories?query=گروه").json()
    assert search[0]["id"] == 20
    assert search[0]["path"] == "کالای دیجیتال > گروه شده"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]

    patched = client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 21}).json()

    assert patched["basalam_category"]["category_id"] == 21
    assert patched["basalam_category"]["source"] == "user"
    assert patched["basalam_category"]["unit_type_id"] == 6304


def test_publish_ready_batch_to_basalam_uses_uploaded_photos_and_product_payload(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(
        f"/batches/{batch['id']}/assets",
        files=[image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg")],
    )
    client.post(f"/batches/{batch['id']}/process")
    ready_items = client.get(f"/batches/{batch['id']}/items").json()
    for item in ready_items:
        client.patch(
            f"/batch-items/{item['id']}",
            json={
                "price_toman": item["price_toman"] or 456000,
                "stock": 5,
                "preparation_days": 2,
                "weight_grams": 300,
                "package_weight_grams": 500,
                "unit_quantity": 1,
            },
        )
    suggested = client.post(f"/batches/{batch['id']}/categories/basalam/suggest").json()
    assert suggested[0]["basalam_category"]["category_id"] == 20

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert job["step"] == "ready"

    published = client.get(f"/batches/{batch['id']}/published-products").json()
    assert len(published) == 2
    assert len(fake.uploaded_paths) == 3
    assert [product.name for product in fake.created_products] == [item["title"] for item in client.get(f"/batches/{batch['id']}/items").json()]
    assert fake.created_products[0].photo_ids == [1001, 1002]
    assert fake.created_products[0].primary_price == 4560000
    assert fake.created_products[0].category_id == 20
    assert fake.created_products[0].stock == 5
    assert fake.created_products[0].preparation_days == 2
    assert fake.created_products[0].weight == 300
    assert fake.created_products[0].package_weight == 500
    assert fake.created_products[0].unit_quantity == 1
    assert fake.created_products[0].status == 2976
    assert fake.created_products[0].to_json()["status"] == 2976


def test_create_basalam_publish_job_reuses_active_job_and_allows_retry_after_finish(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    session = client.app.state.session_factory()
    try:
        first_job, first_created = create_basalam_publish_job(session, batch["id"])
        second_job, second_created = create_basalam_publish_job(session, batch["id"])

        assert first_created is True
        assert second_created is False
        assert second_job.id == first_job.id
        assert len(session.scalars(select(PublishJob).where(PublishJob.batch_id == batch["id"])).all()) == 1

        first_job.status = "succeeded"
        first_job.step = "ready"
        session.commit()

        retry_job, retry_created = create_basalam_publish_job(session, batch["id"])

        assert retry_created is True
        assert retry_job.id != first_job.id
        assert len(session.scalars(select(PublishJob).where(PublishJob.batch_id == batch["id"])).all()) == 2
    finally:
        session.close()


def test_publish_retries_valid_status_when_basalam_rejects_configured_status(client: TestClient, batch: dict):
    class StatusRetryBasalamClient(FakeBasalamClient):
        def __init__(self):
            super().__init__()
            self.attempted_statuses: list[int] = []

        def create_product(
            self,
            connection: PlatformConnection,
            payload: BasalamProductPayload,
        ) -> dict:
            self.attempted_statuses.append(payload.status)
            if payload.status == 1:
                raise BasalamClientError(
                    'Basalam product create failed: 422 {"messages":[{"fields":["status"],"message":"وضعیت محصول نامعتبر می باشد"}]}'
                )
            return super().create_product(connection, payload)

    fake = StatusRetryBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"
    client.app.state.settings.basalam_default_status = 1

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": 600000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 20})
    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert fake.attempted_statuses == [1, 2976]
    assert fake.created_products[0].status == 2976
    assert fake.created_products[0].primary_price == 6000000


def test_publish_retries_next_auto_category_when_basalam_rejects_category(client: TestClient, batch: dict):
    class CategoryRetryBasalamClient(FakeBasalamClient):
        def create_product(
            self,
            connection: PlatformConnection,
            payload: BasalamProductPayload,
        ) -> dict:
            if payload.category_id == 20:
                raise BasalamClientError("Basalam product create failed: 422 category_id is invalid")
            return super().create_product(connection, payload)

    fake = CategoryRetryBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg"), image_file("b.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    suggested = client.post(f"/batches/{batch['id']}/categories/basalam/suggest").json()
    assert suggested[0]["basalam_category"]["category_id"] == 20

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert fake.created_products[0].category_id == 21
    updated_item = client.get(f"/batches/{batch['id']}/items").json()[0]
    assert updated_item["basalam_category"]["category_id"] == 21
    assert updated_item["basalam_category"]["source"] == "auto"


def test_publish_uses_numeric_unit_when_selected_category_has_no_unit_type(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    patched = client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 22}).json()
    assert patched["basalam_category"]["unit_type_id"] is None

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert fake.created_products[0].category_id == 22
    assert fake.created_products[0].unit_type == 6304


def test_publish_retries_numeric_unit_when_basalam_rejects_category_unit(client: TestClient, batch: dict):
    class UnitRetryBasalamClient(FakeBasalamClient):
        def __init__(self):
            super().__init__()
            self.attempted_unit_types: list[int] = []

        def create_product(
            self,
            connection: PlatformConnection,
            payload: BasalamProductPayload,
        ) -> dict:
            self.attempted_unit_types.append(payload.unit_type)
            if payload.unit_type != 6304:
                raise BasalamClientError("Basalam product create failed: 422 unit_type is invalid")
            return super().create_product(connection, payload)

    fake = UnitRetryBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    patched = client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 23}).json()
    assert patched["basalam_category"]["unit_type_id"] == 6305

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert fake.attempted_unit_types == [6305, 6304]
    assert fake.created_products[0].category_id == 23
    assert fake.created_products[0].unit_type == 6304
    updated_item = client.get(f"/batches/{batch['id']}/items").json()[0]
    assert updated_item["basalam_category"]["category_id"] == 23
    assert updated_item["basalam_category"]["unit_type_id"] == 6304


def test_publish_allows_auto_category_below_review_threshold(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"
    client.app.state.settings.basalam_category_suggestion_threshold = 0.99

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    suggested = client.post(f"/batches/{batch['id']}/categories/basalam/suggest").json()
    suggested_category_id = suggested[0]["basalam_category"]["category_id"]
    assert suggested_category_id is not None
    assert suggested[0]["basalam_category"]["confidence"] < 0.99

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert fake.created_products[0].category_id == suggested_category_id


def test_failed_basalam_publish_stores_safe_request_debug_metadata(client: TestClient, batch: dict):
    class StatusRequiredBasalamClient(FakeBasalamClient):
        def create_product(
            self,
            connection: PlatformConnection,
            payload: BasalamProductPayload,
        ) -> dict:
            request_payload = payload.to_json()
            raise BasalamClientError(
                'Basalam product create failed: 400 {"openapi_raw_data":[{"fields":["status"],"message":"Field required"}]}',
                status_code=400,
                response_text='{"openapi_raw_data":[{"fields":["status"],"message":"Field required"}]}',
                request_payload=request_payload,
            )

    fake = StatusRequiredBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
        json={
            "price_toman": item["price_toman"] or 456000,
            "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 20})

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "partial_failed"
    published = client.get(f"/batches/{batch['id']}/published-products").json()
    assert published[0]["status"] == "failed"
    metadata = published[0]["response_metadata"]
    assert metadata["http_status"] == 400
    assert metadata["request_payload_has_status"] is True
    assert metadata["request_payload_status"] == 2976
    assert metadata["request_payload_category_id"] == 20
    assert metadata["request_payload_unit_type"] == 6304
    assert metadata["request_payload_primary_price"] == 4560000
    assert metadata["request_payload_photo_count"] == 1
    assert "status" in metadata["request_payload_keys"]
    assert "name" in metadata["request_payload_keys"]
    assert "request_payload" not in metadata


def test_publish_requires_seller_operational_fields(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(f"/batch-items/{item['id']}", json={"price_toman": 456000})
    client.patch(f"/batch-items/{item['id']}/basalam-category", json={"category_id": 20})

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "failed"
    published = client.get(f"/batches/{batch['id']}/published-products").json()
    assert published[0]["status"] == "failed"
    assert "موجودی" in published[0]["error"]
    assert fake.created_products == []
    assert fake.uploaded_paths == []


def test_publish_does_not_guess_category_for_ambiguous_product(client: TestClient, batch: dict):
    fake = FakeBasalamClient()
    client.app.state.basalam_client_factory = lambda _settings: fake
    client.app.state.settings.basalam_client_id = "test-client"
    client.app.state.settings.basalam_client_secret = "test-secret"
    client.app.state.settings.basalam_redirect_uri = "http://testserver/integrations/basalam/callback"

    client.post(f"/batches/{batch['id']}/assets", files=[image_file("a.jpg")])
    client.post(f"/batches/{batch['id']}/process")
    item = client.get(f"/batches/{batch['id']}/items").json()[0]
    client.patch(
        f"/batch-items/{item['id']}",
            json={
                "title": "محصول نامشخص",
                "description": "برای استفاده روزانه مناسب است",
                "price_toman": 456000,
                "stock": 5,
            "preparation_days": 2,
            "weight_grams": 300,
            "package_weight_grams": 500,
            "unit_quantity": 1,
        },
    )
    suggested = client.post(f"/batches/{batch['id']}/categories/basalam/suggest").json()

    assert suggested[0]["basalam_category"] is None

    callback_state = client.get(f"/integrations/basalam/oauth-url?seller_id={batch['seller_id']}").json()["state"]
    client.get(f"/integrations/basalam/callback?code=valid-code&state={callback_state}", follow_redirects=False)

    publish = client.post(f"/batches/{batch['id']}/publish/basalam")

    assert publish.status_code == 202
    job = client.get(f"/publish-jobs/{publish.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert "اطلاعات کامل ندارد" in job["error"]
    published = client.get(f"/batches/{batch['id']}/published-products").json()
    assert published[0]["status"] == "failed"
    assert "دسته‌بندی" in published[0]["error"]
    assert fake.created_products == []
    assert fake.uploaded_paths == []


def test_empty_basalam_status_uses_published_default():
    settings = Settings(basalam_default_status="")

    assert settings.basalam_default_status == 2976
