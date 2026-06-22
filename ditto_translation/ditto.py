from __future__ import annotations

from typing import Protocol

import httpx


class DittoUpdateClient(Protocol):
    def update_text_item(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        variant_id: str | None,
        text: str,
    ) -> None: ...


class DittoApiError(RuntimeError):
    """Raised when Ditto rejects an update request."""


class PermanentDittoApiError(DittoApiError):
    """Raised when retrying the same Ditto request cannot succeed."""


class DittoApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        force_variant_creation: bool,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_token = api_token
        self._force_variant_creation = force_variant_creation
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=timeout_seconds,
            transport=transport,
        )

    def update_text_item(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        variant_id: str | None,
        text: str,
    ) -> None:
        if not self._api_token:
            raise DittoApiError("DITTO_API_TOKEN is required to update Ditto text items")

        payload: dict[str, object] = {
            "projectId": project_id,
            "updates": [
                {
                    "developerId": developer_id,
                    "text": text,
                }
            ],
        }
        if variant_id is not None:
            payload["variantId"] = variant_id
            if self._force_variant_creation:
                payload["forceVariantCreation"] = True

        response = self._client.patch(
            "textItems",
            headers={"Authorization": self._api_token},
            json=payload,
        )
        if 200 <= response.status_code < 300:
            return

        error_type = (
            PermanentDittoApiError if _is_permanent_status(response.status_code) else DittoApiError
        )
        raise error_type(
            "Ditto text update failed "
            f"for project={project_id} developer_id={developer_id} locale={locale}: "
            f"status_code={response.status_code}"
        )


def _is_permanent_status(status_code: int) -> bool:
    return 400 <= status_code < 500 and status_code != 429
