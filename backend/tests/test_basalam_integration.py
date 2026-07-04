from fastapi.testclient import TestClient

from app.config import Settings
from app.integrations.basalam import BasalamProductPayload, BasalamUploadedFile
from app.models import PlatformConnection
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
        if item["price_toman"] is None:
            client.patch(f"/batch-items/{item['id']}", json={"price_toman": 456000})
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
    assert fake.created_products[0].primary_price == 456000
    assert fake.created_products[0].category_id == 20


def test_empty_optional_basalam_numeric_settings_are_ignored():
    settings = Settings(basalam_default_category_id="", basalam_default_status="")

    assert settings.basalam_default_category_id is None
    assert settings.basalam_default_status is None
