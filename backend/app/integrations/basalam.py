from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import Settings


class BasalamClientError(RuntimeError):
    pass


class BasalamUnauthorized(BasalamClientError):
    pass


@dataclass(frozen=True)
class BasalamUploadedFile:
    id: int
    raw: dict


@dataclass(frozen=True)
class BasalamProductPayload:
    name: str
    description: str
    primary_price: int
    photo_ids: list[int]
    category_id: int | None
    stock: int
    status: int | None
    preparation_days: int
    weight: int
    package_weight: int
    unit_quantity: int
    unit_type: int

    def to_json(self) -> dict:
        payload = {
            "name": self.name,
            "description": self.description,
            "brief": self.description[:250],
            "primary_price": self.primary_price,
            "photo": self.photo_ids[0],
            "photos": self.photo_ids,
            "stock": self.stock,
            "preparation_days": self.preparation_days,
            "weight": self.weight,
            "package_weight": self.package_weight,
            "unit_quantity": self.unit_quantity,
            "unit_type": self.unit_type,
            "is_wholesale": False,
        }
        if self.category_id is not None:
            payload["category_id"] = self.category_id
        if self.status is not None:
            payload["status"] = self.status
        return payload


class BasalamClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout = httpx.Timeout(35.0, connect=10.0)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.basalam_client_id
            and self.settings.basalam_client_secret
            and self.settings.basalam_redirect_uri
        )

    def get_authorization_url(self, state: str) -> str:
        if not self.is_configured:
            raise BasalamClientError("Basalam OAuth is not configured")
        params = {
            "client_id": self.settings.basalam_client_id,
            "redirect_uri": self.settings.basalam_redirect_uri,
            "scope": self.settings.basalam_scopes,
            "state": state,
            "response_type": "code",
        }
        return f"{self.settings.basalam_auth_url}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> dict:
        response = httpx.post(
            self.settings.basalam_token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.settings.basalam_client_id,
                "client_secret": self.settings.basalam_client_secret,
                "redirect_uri": self.settings.basalam_redirect_uri,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        return self._json_or_raise(response, "Basalam token exchange failed")

    def refresh_tokens(self, refresh_token: str) -> dict:
        response = httpx.post(
            self.settings.basalam_token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": self.settings.basalam_client_id,
                "client_secret": self.settings.basalam_client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        return self._json_or_raise(response, "Basalam token refresh failed")

    def get_current_user(self, access_token: str) -> dict:
        response = httpx.get(
            f"{self.settings.basalam_api_base_url.rstrip('/')}/v1/users/me",
            headers=self._auth_headers(access_token),
            timeout=self.timeout,
        )
        if response.status_code == 404:
            response = httpx.get(
                f"{self.settings.basalam_legacy_core_base_url.rstrip('/')}/v3/users/me",
                headers=self._auth_headers(access_token),
                timeout=self.timeout,
            )
        return self._json_or_raise(response, "Basalam user profile request failed")

    def upload_product_photo(self, connection, path: str, mime_type: str) -> BasalamUploadedFile:
        with Path(path).open("rb") as file:
            response = httpx.post(
                f"{self.settings.basalam_api_base_url.rstrip('/')}/v1/files",
                headers=self._auth_headers(connection.access_token),
                files={"file": (Path(path).name, file, mime_type)},
                data={"file_type": "product.photo"},
                timeout=self.timeout,
            )
        data = self._json_or_raise(response, "Basalam photo upload failed")
        return BasalamUploadedFile(id=int(data["id"]), raw=data)

    def create_product(self, connection, payload: BasalamProductPayload) -> dict:
        response = httpx.post(
            f"{self.settings.basalam_api_base_url.rstrip('/')}/v1/vendors/{connection.external_shop_id}/products",
            headers={**self._auth_headers(connection.access_token), "Prefer": "return=representation"},
            json=payload.to_json(),
            timeout=self.timeout,
        )
        return self._json_or_raise(response, "Basalam product create failed")

    def get_categories(self) -> dict:
        response = httpx.get(
            f"{self.settings.basalam_api_base_url.rstrip('/')}/v1/categories",
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        return self._json_or_raise(response, "Basalam categories request failed")

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def _json_or_raise(self, response: httpx.Response, message: str) -> dict:
        if response.status_code == 401:
            raise BasalamUnauthorized(message)
        if response.is_error:
            detail = response.text[:800]
            raise BasalamClientError(f"{message}: {response.status_code} {detail}")
        return response.json()
