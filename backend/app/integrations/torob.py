from dataclasses import dataclass

import httpx

from app.config import Settings


class TorobClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class TorobBulkItem:
    base_product_rk: str
    price: int


class TorobClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout = httpx.Timeout(35.0, connect=10.0)

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.torob_bulk_add_key and self.settings.torob_auth_header_value)

    def bulk_add(self, shop_id: int, items: list[TorobBulkItem]) -> dict:
        if not self.is_configured:
            raise TorobClientError("Torob bulk add is not configured")
        if len(items) > 100:
            raise TorobClientError("Torob bulk add supports at most 100 items per request")
        headers = {
            "Content-Type": "application/json",
            self.settings.torob_auth_header_name: self.settings.torob_auth_header_value,
        }
        try:
            response = httpx.post(
                self.settings.torob_bulk_add_url,
                headers=headers,
                json={
                    "bulk_product_adding_key": self.settings.torob_bulk_add_key,
                    "shop_id": shop_id,
                    "items": [
                        {"base_product_rk": item.base_product_rk, "price": item.price}
                        for item in items
                    ],
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise TorobClientError("Torob bulk add request failed") from exc
        if response.is_error:
            raise TorobClientError(f"Torob bulk add failed: {response.status_code} {response.text[:800]}")
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}
