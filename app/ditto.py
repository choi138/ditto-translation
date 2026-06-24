from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)
MAX_ERROR_RESPONSE_LOG_CHARS = 1000


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

        logger.info(
            "Updating Ditto text item project=%s developer_id=%s locale=%s "
            "variant_id=%s force_variant_creation=%s",
            project_id,
            developer_id,
            locale,
            variant_id,
            self._force_variant_creation,
        )
        response = self._client.patch(
            "textItems",
            headers={"Authorization": self._api_token.strip()},
            json=payload,
        )
        if 200 <= response.status_code < 300:
            return

        error_type = (
            PermanentDittoApiError if _is_permanent_status(response.status_code) else DittoApiError
        )
        logger.error(
            "Ditto text update failed project=%s developer_id=%s locale=%s "
            "variant_id=%s force_variant_creation=%s status_code=%s response_body=%s",
            project_id,
            developer_id,
            locale,
            variant_id,
            self._force_variant_creation,
            response.status_code,
            _safe_response_excerpt(
                response.text,
                sensitive_values=(text, self._api_token),
            ),
        )
        raise error_type(
            "Ditto text update failed "
            f"for project={project_id} developer_id={developer_id} locale={locale}: "
            f"status_code={response.status_code}"
        )


def _is_permanent_status(status_code: int) -> bool:
    return 400 <= status_code < 500 and status_code != 429


def _safe_response_excerpt(response_text: str, *, sensitive_values: tuple[str, ...]) -> str:
    excerpt = response_text
    representations = {
        representation
        for value in sensitive_values
        for representation in _sensitive_representations(value)
    }
    for representation in sorted(representations, key=len, reverse=True):
        excerpt = excerpt.replace(representation, "[redacted]")
    return excerpt[:MAX_ERROR_RESPONSE_LOG_CHARS]


def _sensitive_representations(value: str) -> tuple[str, ...]:
    if not value:
        return ()

    representations = {
        value,
        json.dumps(value),
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False),
        json.dumps(value, ensure_ascii=False)[1:-1],
    }
    return tuple(sorted(representations, key=len, reverse=True))
