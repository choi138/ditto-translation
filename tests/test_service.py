from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ditto import (
    DittoApiClient,
    DittoApiError,
    DittoUpdateClient,
    PermanentDittoApiError,
)
from app.models import EventInProgressError, EventStart, ProcessOutcome, ProcessResult
from app.security import signed_headers
from app.service import DittoTranslationService
from app.store import TranslationStore
from app.translator import Translator


@dataclass
class DittoUpdate:
    project_id: str
    developer_id: str
    locale: str
    variant_id: str | None
    text: str


class FakeTranslator(Translator):
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], str]] = []
        self.failures_remaining = 0

    def translate(
        self,
        *,
        source_locale: str,
        target_locales: tuple[str, ...],
        text: str,
    ) -> dict[str, str]:
        self.calls.append((source_locale, target_locales, text))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("temporary translation failure")
        return {locale: f"{text} [{locale}]" for locale in target_locales}


class FakeDittoClient(DittoUpdateClient):
    def __init__(self) -> None:
        self.updates: list[DittoUpdate] = []
        self.attempts = 0
        self.failures_remaining = 0
        self.permanent_failure = False

    def update_text_item(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        variant_id: str | None,
        text: str,
    ) -> None:
        self.attempts += 1
        if self.permanent_failure:
            raise PermanentDittoApiError("permanent Ditto failure status_code=400")
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("temporary Ditto failure")
        self.updates.append(
            DittoUpdate(
                project_id=project_id,
                developer_id=developer_id,
                locale=locale,
                variant_id=variant_id,
                text=text,
            )
        )


@pytest.fixture
def signing_key() -> str:
    return "test-signing-key-123"


@pytest.fixture
def settings(tmp_path: Path, signing_key: str) -> Settings:
    return Settings(
        ditto_api_token="token",
        ditto_webhook_signing_key=signing_key,
        sqlite_path=tmp_path / "events.sqlite3",
        ditto_locale_variant_ids={"ko": None, "en": "en", "ja": "ja"},
        translation_retry_initial_delay_seconds=0,
        ditto_retry_initial_delay_seconds=0,
    )


@pytest.fixture
def fakes() -> tuple[FakeTranslator, FakeDittoClient]:
    return FakeTranslator(), FakeDittoClient()


@pytest.fixture
def service(
    settings: Settings,
    fakes: tuple[FakeTranslator, FakeDittoClient],
) -> DittoTranslationService:
    translator, ditto = fakes
    return DittoTranslationService(
        settings=settings,
        store=TranslationStore(settings.sqlite_path),
        translator=translator,
        ditto_client=ditto,
    )


def test_ko_base_change_updates_only_en_and_ja(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    payload = base_payload(text_after="안녕하세요")

    result = process(service, payload, signing_key, "req-1")

    assert result.outcome == ProcessOutcome.PROCESSED
    assert result.source_locale == "ko"
    assert result.updated_locales == ("en", "ja")
    assert translator.calls == [("ko", ("en", "ja"), "안녕하세요")]
    assert [update.locale for update in ditto.updates] == ["en", "ja"]
    assert [update.variant_id for update in ditto.updates] == ["en", "ja"]
    assert all(update.locale != "ko" for update in ditto.updates)


def test_en_variant_change_uses_variant_text_after_and_updates_ko_and_ja(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    payload = variant_payload(variant_id="en", text_after="Checkout")

    result = process(service, payload, signing_key, "req-2")

    assert result.outcome == ProcessOutcome.PROCESSED
    assert result.source_locale == "en"
    assert result.updated_locales == ("ko", "ja")
    assert translator.calls == [("en", ("ko", "ja"), "Checkout")]
    assert [(update.locale, update.variant_id) for update in ditto.updates] == [
        ("ko", None),
        ("ja", "ja"),
    ]


def test_duplicate_request_id_is_skipped(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    _, ditto = fakes
    payload = base_payload(text_after="다음")

    first = process(service, payload, signing_key, "same-request")
    second = process(service, payload, signing_key, "same-request")

    assert first.outcome == ProcessOutcome.PROCESSED
    assert second.outcome == ProcessOutcome.DUPLICATE
    assert len(ditto.updates) == 2


def test_in_progress_redelivery_is_not_acknowledged(
    settings: Settings,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    store = TranslationStore(settings.sqlite_path)
    store.begin_event(
        "request:req-active",
        stale_after_seconds=settings.in_progress_event_timeout_seconds,
    )
    service = DittoTranslationService(
        settings=settings,
        store=store,
        translator=translator,
        ditto_client=ditto,
    )

    with pytest.raises(EventInProgressError):
        process(service, base_payload(text_after="진행 중"), signing_key, "req-active")

    assert translator.calls == []
    assert ditto.updates == []


def test_failed_event_can_be_retried(
    settings: Settings,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    translator.failures_remaining = 3
    service = DittoTranslationService(
        settings=settings,
        store=TranslationStore(settings.sqlite_path),
        translator=translator,
        ditto_client=ditto,
    )
    payload = base_payload(text_after="실패 후 재시도")

    with pytest.raises(RuntimeError):
        process(service, payload, signing_key, "retry-request")

    translator.failures_remaining = 0
    result = process(service, payload, signing_key, "retry-request")

    assert result.outcome == ProcessOutcome.PROCESSED
    assert len(ditto.updates) == 2


def test_failed_event_retry_claim_is_single_owner(settings: Settings) -> None:
    first_store = TranslationStore(settings.sqlite_path)
    second_store = TranslationStore(settings.sqlite_path)
    event_key = "request:req-atomic-retry"

    assert (
        first_store.begin_event(
            event_key,
            stale_after_seconds=settings.in_progress_event_timeout_seconds,
        )
        == EventStart.STARTED
    )
    first_store.fail_event(event_key, "temporary failure")

    assert (
        first_store.begin_event(
            event_key,
            stale_after_seconds=settings.in_progress_event_timeout_seconds,
        )
        == EventStart.RETRY_STARTED
    )
    assert (
        second_store.begin_event(
            event_key,
            stale_after_seconds=settings.in_progress_event_timeout_seconds,
        )
        == EventStart.IN_PROGRESS
    )


def test_self_generated_outbound_webhook_is_skipped(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    result = process(service, base_payload(text_after="저장"), signing_key, "req-source")
    assert result.outcome == ProcessOutcome.PROCESSED

    outbound_en_text = next(update.text for update in ditto.updates if update.locale == "en")
    echoed_payload = variant_payload(variant_id="en", text_after=outbound_en_text)
    echoed = process(service, echoed_payload, signing_key, "req-echo")

    assert echoed.outcome == ProcessOutcome.SKIPPED
    assert echoed.reason == "self-generated update"
    assert len(translator.calls) == 1
    assert len(ditto.updates) == 2


def test_outbound_marker_exists_before_ditto_update(
    settings: Settings,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, _ = fakes
    store = TranslationStore(settings.sqlite_path)

    class EchoCheckingDittoClient(DittoUpdateClient):
        def __init__(self) -> None:
            self.marker_seen: list[bool] = []

        def update_text_item(
            self,
            *,
            project_id: str,
            developer_id: str,
            locale: str,
            variant_id: str | None,
            text: str,
        ) -> None:
            self.marker_seen.append(
                store.consume_outbound_update(
                    project_id=project_id,
                    developer_id=developer_id,
                    locale=locale,
                    text=text,
                )
            )

    ditto = EchoCheckingDittoClient()
    service = DittoTranslationService(
        settings=settings,
        store=store,
        translator=translator,
        ditto_client=ditto,
    )

    result = process(service, base_payload(text_after="즉시 에코"), signing_key, "req-echo-race")

    assert result.outcome == ProcessOutcome.PROCESSED
    assert ditto.marker_seen == [True, True]


def test_repeated_self_generated_outbound_webhooks_are_skipped_until_ttl(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    result = process(service, base_payload(text_after="반복"), signing_key, "req-repeated-source")
    assert result.outcome == ProcessOutcome.PROCESSED

    outbound_en_text = next(update.text for update in ditto.updates if update.locale == "en")
    echoed_payload = variant_payload(variant_id="en", text_after=outbound_en_text)

    first_echo = process(service, echoed_payload, signing_key, "req-repeated-echo-1")
    second_echo = process(service, echoed_payload, signing_key, "req-repeated-echo-2")

    assert first_echo.outcome == ProcessOutcome.SKIPPED
    assert second_echo.outcome == ProcessOutcome.SKIPPED
    assert len(translator.calls) == 1
    assert len(ditto.updates) == 2


def test_translation_failures_are_retried(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    translator.failures_remaining = 2

    result = process(
        service, base_payload(text_after="재시도"), signing_key, "req-retry-translation"
    )

    assert result.outcome == ProcessOutcome.PROCESSED
    assert len(translator.calls) == 3
    assert len(ditto.updates) == 2


def test_ditto_update_failures_are_retried(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    _, ditto = fakes
    ditto.failures_remaining = 2

    result = process(
        service, base_payload(text_after="업데이트 재시도"), signing_key, "req-retry-ditto"
    )

    assert result.outcome == ProcessOutcome.PROCESSED
    assert len(ditto.updates) == 2


def test_failed_ditto_update_does_not_create_self_generated_marker(
    settings: Settings,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    ditto.failures_remaining = settings.ditto_retry_attempts
    service = DittoTranslationService(
        settings=settings,
        store=TranslationStore(settings.sqlite_path),
        translator=translator,
        ditto_client=ditto,
    )
    source_payload = base_payload(text_after="실패한 업데이트")

    with pytest.raises(RuntimeError):
        process(service, source_payload, signing_key, "req-failed-ditto-update")

    real_en_edit = variant_payload(variant_id="en", text_after="실패한 업데이트 [en]")
    result = process(service, real_en_edit, signing_key, "req-real-en-after-failure")

    assert result.outcome == ProcessOutcome.PROCESSED
    assert len(translator.calls) == 2


def test_permanent_ditto_update_failure_is_not_retried(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    ditto.permanent_failure = True

    result = process(
        service, base_payload(text_after="권한 오류"), signing_key, "req-permanent-ditto"
    )
    duplicate = process(
        service,
        base_payload(text_after="권한 오류"),
        signing_key,
        "req-permanent-ditto",
    )

    assert result.outcome == ProcessOutcome.SKIPPED
    assert result.reason == "permanent Ditto API failure"
    assert result.source_locale == "ko"
    assert duplicate.outcome == ProcessOutcome.DUPLICATE
    assert len(translator.calls) == 1
    assert ditto.attempts == 1
    assert ditto.updates == []


def test_invalid_signature_is_rejected(
    service: DittoTranslationService,
    signing_key: str,
) -> None:
    payload = base_payload(text_after="안전")
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = signed_headers(
        payload=payload,
        signing_key=signing_key,
        request_id="req-bad-signature",
        timestamp=str(int(time.time() * 1000)),
    )
    headers["x-ditto-signature"] = "bad"

    with pytest.raises(ValueError, match="Invalid Ditto webhook signature"):
        service.process_webhook(raw_body, headers)


def test_signature_verification_accepts_exact_raw_body(
    service: DittoTranslationService,
    signing_key: str,
) -> None:
    payload = base_payload(text_after="안전")
    raw_body = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    headers = signed_headers(
        raw_body=raw_body,
        signing_key=signing_key,
        request_id="req-raw-body-signature",
        timestamp=str(int(time.time() * 1000)),
    )

    result = service.process_webhook(raw_body, headers)

    assert result.outcome == ProcessOutcome.PROCESSED


def test_malformed_supported_webhook_is_skipped_without_retry(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    payload: dict[str, object] = {
        "event": "TextItem_Base_Text_Changed",
        "data": {
            "textItemId": "welcome-title",
            "projectId": "app",
        },
    }

    result = process(service, payload, signing_key, "req-malformed")
    duplicate = process(service, payload, signing_key, "req-malformed")

    assert result.outcome == ProcessOutcome.SKIPPED
    assert result.reason == "malformed payload"
    assert duplicate.outcome == ProcessOutcome.DUPLICATE
    assert translator.calls == []
    assert ditto.updates == []


def test_invalid_json_webhook_is_skipped_without_retry(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    raw_body = b'{"event": "TextItem_Base_Text_Changed", "data":'
    headers = signed_headers(
        raw_body=raw_body,
        signing_key=signing_key,
        request_id="req-invalid-json",
        timestamp=str(int(time.time() * 1000)),
    )

    result = service.process_webhook(raw_body, headers)

    assert result.outcome == ProcessOutcome.SKIPPED
    assert result.reason == "malformed payload"
    assert translator.calls == []
    assert ditto.updates == []


def test_invalid_utf8_webhook_is_skipped_without_retry(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes
    raw_body = b'{"event": "TextItem_Base_Text_Changed", "data": "\xff"}'
    headers = signed_headers(
        raw_body=raw_body,
        signing_key=signing_key,
        request_id="req-invalid-utf8",
        timestamp=str(int(time.time() * 1000)),
    )

    result = service.process_webhook(raw_body, headers)
    duplicate = service.process_webhook(raw_body, headers)

    assert result.outcome == ProcessOutcome.SKIPPED
    assert result.reason == "malformed payload"
    assert duplicate.outcome == ProcessOutcome.DUPLICATE
    assert translator.calls == []
    assert ditto.updates == []


def test_missing_signing_key_is_rejected_by_default(
    tmp_path: Path,
    fakes: tuple[FakeTranslator, FakeDittoClient],
) -> None:
    translator, ditto = fakes
    settings = Settings(
        ditto_api_token="token",
        ditto_webhook_signing_key=None,
        sqlite_path=tmp_path / "unsigned.sqlite3",
        translation_retry_initial_delay_seconds=0,
        ditto_retry_initial_delay_seconds=0,
    )
    service = DittoTranslationService(
        settings=settings,
        store=TranslationStore(settings.sqlite_path),
        translator=translator,
        ditto_client=ditto,
    )
    raw_body = json.dumps(base_payload(text_after="unsigned"), separators=(",", ":")).encode()

    with pytest.raises(ValueError, match="DITTO_WEBHOOK_SIGNING_KEY is required"):
        service.process_webhook(raw_body, {})


def test_unsigned_webhooks_can_be_explicitly_allowed_for_local_development(
    tmp_path: Path,
    fakes: tuple[FakeTranslator, FakeDittoClient],
) -> None:
    translator, ditto = fakes
    settings = Settings(
        ditto_api_token="token",
        ditto_webhook_signing_key=None,
        allow_unsigned_webhooks=True,
        sqlite_path=tmp_path / "unsigned-allowed.sqlite3",
        translation_retry_initial_delay_seconds=0,
        ditto_retry_initial_delay_seconds=0,
    )
    service = DittoTranslationService(
        settings=settings,
        store=TranslationStore(settings.sqlite_path),
        translator=translator,
        ditto_client=ditto,
    )
    raw_body = json.dumps(base_payload(text_after="local"), separators=(",", ":")).encode()

    result = service.process_webhook(raw_body, {})

    assert result.outcome == ProcessOutcome.PROCESSED
    assert translator.calls == [("ko", ("en", "ja"), "local")]


def test_unknown_variant_is_skipped(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
) -> None:
    translator, ditto = fakes

    result = process(
        service,
        variant_payload(variant_id="fr", text_after="Bonjour"),
        signing_key,
        "req-unknown-variant",
    )

    assert result.outcome == ProcessOutcome.SKIPPED
    assert translator.calls == []
    assert ditto.updates == []


def test_unsupported_event_without_text_change_data_is_skipped(
    service: DittoTranslationService,
    fakes: tuple[FakeTranslator, FakeDittoClient],
    signing_key: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    translator, ditto = fakes
    caplog.set_level(logging.INFO)
    payload: dict[str, object] = {
        "event": "Project_Name_Changed",
        "data": {
            "projectId": "app",
            "nameAfter": "New name",
        },
    }

    result = process(service, payload, signing_key, "req-unsupported")

    assert result.outcome == ProcessOutcome.SKIPPED
    assert translator.calls == []
    assert ditto.updates == []
    assert "Skipping unsupported Ditto webhook event" in caplog.text


def test_non_base_locales_must_have_variant_ids(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Non-base locales must map to variant IDs"):
        Settings(
            ditto_locale_variant_ids={"ko": None, "en": None, "ja": "ja"},
            sqlite_path=tmp_path / "invalid.sqlite3",
        )


def test_variant_ids_must_be_unique(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Variant IDs must be unique"):
        Settings(
            ditto_locale_variant_ids={"ko": None, "en": "shared", "ja": "shared"},
            sqlite_path=tmp_path / "duplicate-variants.sqlite3",
        )


def test_ditto_api_client_includes_project_id_in_update_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = DittoApiClient(
        base_url="https://api.example.test/v2",
        api_token="Bearer test-token",
        force_variant_creation=True,
        transport=httpx.MockTransport(handler),
    )

    client.update_text_item(
        project_id="app",
        developer_id="welcome-title",
        locale="en",
        variant_id="en",
        text="Hello",
    )

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.example.test/v2/textItems"
    assert request.headers["authorization"] == "Bearer test-token"
    assert json.loads(request.content) == {
        "projectId": "app",
        "variantId": "en",
        "forceVariantCreation": True,
        "updates": [{"developerId": "welcome-title", "text": "Hello"}],
    }


def test_ditto_api_client_redacts_error_response_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"text":"translated secret"}')

    client = DittoApiClient(
        base_url="https://api.example.test/v2",
        api_token="Bearer test-token",
        force_variant_creation=False,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PermanentDittoApiError) as exc_info:
        client.update_text_item(
            project_id="app",
            developer_id="welcome-title",
            locale="en",
            variant_id="en",
            text="translated secret",
        )

    message = str(exc_info.value)
    assert "status_code=400" in message
    assert "translated secret" not in message
    assert '"text"' not in message


def test_ditto_api_client_treats_redirects_as_failures() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "https://api.example.test/elsewhere"})

    client = DittoApiClient(
        base_url="https://api.example.test/v2",
        api_token="Bearer test-token",
        force_variant_creation=False,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DittoApiError, match="status_code=307"):
        client.update_text_item(
            project_id="app",
            developer_id="welcome-title",
            locale="en",
            variant_id="en",
            text="Hello",
        )


def test_ditto_api_client_treats_rate_limits_as_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = DittoApiClient(
        base_url="https://api.example.test/v2",
        api_token="Bearer test-token",
        force_variant_creation=False,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DittoApiError, match="status_code=429") as exc_info:
        client.update_text_item(
            project_id="app",
            developer_id="welcome-title",
            locale="en",
            variant_id="en",
            text="Hello",
        )

    assert not isinstance(exc_info.value, PermanentDittoApiError)


def process(
    service: DittoTranslationService,
    payload: dict[str, object],
    signing_key: str,
    request_id: str,
) -> ProcessResult:
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = signed_headers(
        payload=payload,
        signing_key=signing_key,
        request_id=request_id,
        timestamp=str(int(time.time() * 1000)),
    )
    return service.process_webhook(raw_body, headers)


def base_payload(text_after: str) -> dict[str, object]:
    return {
        "event": "TextItem_Base_Text_Changed",
        "data": {
            "textItemId": "welcome-title",
            "projectId": "app",
            "integrated": True,
            "textBefore": "before",
            "textAfter": text_after,
        },
    }


def variant_payload(variant_id: str, text_after: str) -> dict[str, object]:
    return {
        "event": "TextItem_Variant_Text_Changed",
        "data": {
            "textItemId": "welcome-title",
            "projectId": "app",
            "integrated": True,
            "variantId": variant_id,
            "variantTextBefore": "before",
            "variantTextAfter": text_after,
        },
    }
