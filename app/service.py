from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from app.config import Settings
from app.ditto import DittoUpdateClient, PermanentDittoApiError
from app.models import (
    EventInProgressError,
    EventStart,
    ProcessOutcome,
    ProcessResult,
    SourceChange,
    WebhookEvent,
    WebhookPayloadError,
)
from app.retry import retry_call
from app.security import (
    SignatureError,
    event_key_from_request,
    verify_ditto_signature,
)
from app.store import TranslationStore
from app.translator import Translator

logger = logging.getLogger(__name__)


class DittoTranslationService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: TranslationStore,
        translator: Translator,
        ditto_client: DittoUpdateClient,
    ) -> None:
        self._settings = settings
        self._store = store
        self._translator = translator
        self._ditto_client = ditto_client

    def process_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> ProcessResult:
        process_started_at = time.perf_counter()
        if self._settings.ditto_webhook_signing_key:
            verify_ditto_signature(
                raw_body=raw_body,
                headers=headers,
                signing_key=self._settings.ditto_webhook_signing_key,
                tolerance_seconds=self._settings.webhook_timestamp_tolerance_seconds,
            )
        elif self._settings.allow_unsigned_webhooks:
            logger.warning("DITTO_WEBHOOK_SIGNING_KEY is not set; skipping signature verification")
        else:
            raise SignatureError(
                "DITTO_WEBHOOK_SIGNING_KEY is required unless ALLOW_UNSIGNED_WEBHOOKS=true"
            )

        event_key = event_key_from_request(raw_body, headers)
        event_start = self._store.begin_event(
            event_key,
            stale_after_seconds=self._settings.in_progress_event_timeout_seconds,
        )
        if event_start == EventStart.DUPLICATE:
            logger.info("Skipping duplicate Ditto webhook event", extra={"event_key": event_key})
            return ProcessResult(
                outcome=ProcessOutcome.DUPLICATE,
                reason="event already processed",
                event_key=event_key,
            )
        if event_start == EventStart.IN_PROGRESS:
            logger.info(
                "Ditto webhook event is already in progress", extra={"event_key": event_key}
            )
            raise EventInProgressError("Ditto webhook event is already in progress")

        change: SourceChange | None = None
        try:
            payload = _json_object(raw_body)
            change = self._extract_change(payload)
            if change is None:
                self._store.finish_event(event_key, status="skipped")
                logger.info(
                    "Skipping unsupported Ditto webhook event",
                    extra={
                        "event_key": event_key,
                        "event": payload.get("event"),
                    },
                )
                return ProcessResult(
                    outcome=ProcessOutcome.SKIPPED,
                    reason="unsupported event or variant",
                    event_key=event_key,
                )

            if self._store.consume_outbound_update(
                project_id=change.project_id,
                developer_id=change.developer_id,
                locale=change.source_locale,
                variant_id=change.source_variant_id,
                text=change.source_text,
            ):
                self._store.finish_event(event_key, status="skipped")
                logger.info(
                    "Skipping self-generated Ditto webhook event",
                    extra={
                        "event_key": event_key,
                        "project_id": change.project_id,
                        "developer_id": change.developer_id,
                        "source_locale": change.source_locale,
                    },
                )
                return ProcessResult(
                    outcome=ProcessOutcome.SKIPPED,
                    reason="self-generated update",
                    event_key=event_key,
                    source_locale=change.source_locale,
                )

            target_locales = tuple(
                locale
                for locale in self._settings.supported_locales
                if locale != change.source_locale
            )

            translation_started_at = time.perf_counter()
            translations = self._translate_with_retry(change, target_locales)
            translation_duration_ms = _duration_ms(translation_started_at)

            ditto_update_started_at = time.perf_counter()
            updated_locales = self._update_ditto_targets(change, translations, target_locales)
            ditto_update_duration_ms = _duration_ms(ditto_update_started_at)

            self._store.finish_event(event_key, status="succeeded")
            logger.info(
                "Processed Ditto translation webhook",
                extra={
                    "event_key": event_key,
                    "project_id": change.project_id,
                    "developer_id": change.developer_id,
                    "source_locale": change.source_locale,
                    "updated_locales": ",".join(updated_locales),
                    "translation_duration_ms": translation_duration_ms,
                    "ditto_update_duration_ms": ditto_update_duration_ms,
                    "duration_ms": _duration_ms(process_started_at),
                },
            )
            return ProcessResult(
                outcome=ProcessOutcome.PROCESSED,
                reason="translated target locales",
                event_key=event_key,
                source_locale=change.source_locale,
                updated_locales=updated_locales,
            )
        except WebhookPayloadError as exc:
            self._store.finish_event(event_key, status="skipped")
            logger.warning(
                "Skipping malformed Ditto webhook event",
                extra={"event_key": event_key, "error": str(exc)},
            )
            return ProcessResult(
                outcome=ProcessOutcome.SKIPPED,
                reason="malformed payload",
                event_key=event_key,
            )
        except PermanentDittoApiError as exc:
            self._store.finish_event(event_key, status="skipped")
            logger.error(
                "Skipping Ditto webhook after permanent Ditto API failure",
                extra={"event_key": event_key, "error": str(exc)},
            )
            return ProcessResult(
                outcome=ProcessOutcome.SKIPPED,
                reason="permanent Ditto API failure",
                event_key=event_key,
                source_locale=change.source_locale if change is not None else None,
            )
        except Exception as exc:
            self._store.fail_event(event_key, exc.__class__.__name__)
            logger.error(
                "Ditto webhook processing failed",
                extra={"event_key": event_key, "error_type": exc.__class__.__name__},
            )
            raise

    def _translate_with_retry(
        self,
        change: SourceChange,
        target_locales: tuple[str, ...],
    ) -> dict[str, str]:
        return retry_call(
            lambda: self._translator.translate(
                source_locale=change.source_locale,
                target_locales=target_locales,
                text=change.source_text,
            ),
            attempts=self._settings.translation_retry_attempts,
            initial_delay_seconds=self._settings.translation_retry_initial_delay_seconds,
            backoff_multiplier=self._settings.retry_backoff_multiplier,
            max_delay_seconds=self._settings.retry_max_delay_seconds,
        )

    def _update_ditto_targets(
        self,
        change: SourceChange,
        translations: dict[str, str],
        target_locales: tuple[str, ...],
    ) -> tuple[str, ...]:
        updated_locales: list[str] = []
        locale_updates: list[tuple[str, str, str | None]] = []

        if change.source_variant_id is None:
            source_variant_id = self._settings.variant_id_for_locale(change.source_locale)
            if source_variant_id is not None:
                locale_updates.append((change.source_locale, change.source_text, source_variant_id))

        locale_updates.extend(
            (
                locale,
                translations[locale],
                self._settings.variant_id_for_locale(locale),
            )
            for locale in target_locales
        )

        for locale, text, variant_id in locale_updates:
            self._store.remember_outbound_update(
                project_id=change.project_id,
                developer_id=change.developer_id,
                locale=locale,
                variant_id=variant_id,
                text=text,
                ttl_seconds=self._settings.outbound_update_ttl_seconds,
            )
            try:
                retry_call(
                    lambda locale=locale, variant_id=variant_id, text=text: (
                        self._ditto_client.update_text_item(
                            project_id=change.project_id,
                            developer_id=change.developer_id,
                            locale=locale,
                            variant_id=variant_id,
                            text=text,
                        )
                    ),
                    attempts=self._settings.ditto_retry_attempts,
                    initial_delay_seconds=self._settings.ditto_retry_initial_delay_seconds,
                    backoff_multiplier=self._settings.retry_backoff_multiplier,
                    max_delay_seconds=self._settings.retry_max_delay_seconds,
                    non_retryable_exceptions=(PermanentDittoApiError,),
                )
            except Exception:
                self._store.forget_outbound_update(
                    project_id=change.project_id,
                    developer_id=change.developer_id,
                    locale=locale,
                    variant_id=variant_id,
                    text=text,
                )
                raise
            updated_locales.append(locale)
        return tuple(updated_locales)

    def _extract_change(self, payload: dict[str, Any]) -> SourceChange | None:
        event = payload.get("event")
        if event not in {
            WebhookEvent.BASE_TEXT_CHANGED.value,
            WebhookEvent.VARIANT_TEXT_CHANGED.value,
        }:
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            raise WebhookPayloadError("Ditto webhook data must be an object")

        if event == WebhookEvent.BASE_TEXT_CHANGED:
            return SourceChange(
                project_id=_required_string(data, "projectId"),
                developer_id=_required_string(data, "textItemId"),
                source_locale=self._settings.base_locale,
                source_text=_required_string(data, "textAfter"),
                source_variant_id=None,
            )

        if event == WebhookEvent.VARIANT_TEXT_CHANGED:
            variant_id = _required_string(data, "variantId")
            source_locale = self._settings.variant_id_to_locale.get(variant_id)
            if source_locale is None:
                return None
            return SourceChange(
                project_id=_required_string(data, "projectId"),
                developer_id=_required_string(data, "textItemId"),
                source_locale=source_locale,
                source_text=_required_string(data, "variantTextAfter"),
                source_variant_id=variant_id,
            )

        return None


def _json_object(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookPayloadError("Ditto webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise WebhookPayloadError("Ditto webhook body must be a JSON object")
    return payload


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise WebhookPayloadError(f"Ditto webhook field {key} must be a string")
    return value


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)
