from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

import pytest
from google.genai import types

from app.translator import SYSTEM_INSTRUCTION, GeminiClient, GeminiTranslator, TranslationError


@dataclass
class FakeGenerateContentResponse:
    text: object = "{}"


class FakeModels:
    def __init__(
        self,
        *,
        response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response if response is not None else FakeGenerateContentResponse()
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **body: object) -> object:
        self.calls.append(body)
        if self.error is not None:
            raise self.error
        return self.response


@dataclass
class FakeGeminiClient:
    models: FakeModels


def fake_client(models: FakeModels) -> GeminiClient:
    return cast(GeminiClient, FakeGeminiClient(models))


def test_gemini_translator_requests_structured_json_output() -> None:
    models = FakeModels(
        response=FakeGenerateContentResponse(
            text=json.dumps({"en": "Hello", "ja": "こんにちは"}, ensure_ascii=False)
        )
    )
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        timeout_seconds=2.5,
        client=fake_client(models),
    )

    result = translator.translate(
        source_locale="ko",
        target_locales=("en", "ja"),
        text="안녕하세요",
    )

    assert result == {"en": "Hello", "ja": "こんにちは"}
    assert len(models.calls) == 1

    body = models.calls[0]
    assert body["model"] == "gemini-test"

    request_input = body["contents"]
    assert isinstance(request_input, str)
    assert json.loads(request_input) == {
        "source_locale": "ko",
        "target_locales": ["en", "ja"],
        "text": "안녕하세요",
        "response_shape": {
            "en": "translation in en",
            "ja": "translation in ja",
        },
    }

    config = body["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.system_instruction == SYSTEM_INSTRUCTION
    assert config.response_mime_type == "application/json"

    schema = cast(dict[str, object], config.response_schema)
    assert schema["required"] == ["en", "ja"]
    assert "additionalProperties" not in schema
    assert schema["properties"] == {
        "en": {"type": "string"},
        "ja": {"type": "string"},
    }
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_budget == 0
    assert config.http_options is not None
    assert config.http_options.timeout == 2500


def test_gemini_translator_skips_provider_when_no_target_locales() -> None:
    models = FakeModels()
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(models),
    )

    assert translator.translate(source_locale="ko", target_locales=(), text="안녕하세요") == {}
    assert models.calls == []


def test_gemini_translator_returns_empty_strings_for_empty_text() -> None:
    models = FakeModels()
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(models),
    )

    assert translator.translate(source_locale="ko", target_locales=("en", "ja"), text="") == {
        "en": "",
        "ja": "",
    }
    assert models.calls == []


def test_gemini_translator_rejects_invalid_json_output() -> None:
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(FakeModels(response=FakeGenerateContentResponse("not json"))),
    )

    with pytest.raises(TranslationError, match="not valid JSON"):
        translator.translate(source_locale="ko", target_locales=("en",), text="안녕하세요")


def test_gemini_translator_rejects_missing_output_text() -> None:
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(FakeModels(response=object())),
    )

    with pytest.raises(TranslationError, match="did not contain text content"):
        translator.translate(source_locale="ko", target_locales=("en",), text="안녕하세요")


def test_gemini_translator_wraps_provider_exception() -> None:
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(FakeModels(error=RuntimeError("provider down"))),
    )

    with pytest.raises(TranslationError, match="provider request failed"):
        translator.translate(source_locale="ko", target_locales=("en",), text="안녕하세요")


def test_gemini_translator_enforces_required_locale_keys() -> None:
    translator = GeminiTranslator(
        api_key="",
        model="gemini-test",
        client=fake_client(
            FakeModels(response=FakeGenerateContentResponse(json.dumps({"en": "Hello"})))
        ),
    )

    with pytest.raises(TranslationError, match="missing string value for locale ja"):
        translator.translate(source_locale="ko", target_locales=("en", "ja"), text="안녕하세요")


def test_gemini_translator_requires_api_key_without_injected_client() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY must be configured"):
        GeminiTranslator(api_key="", model="gemini-test")


def test_gemini_translator_requires_model() -> None:
    with pytest.raises(ValueError, match="TRANSLATION_MODEL must be configured"):
        GeminiTranslator(
            api_key="",
            model=" ",
            client=fake_client(FakeModels()),
        )


def test_gemini_translator_requires_positive_timeout() -> None:
    with pytest.raises(ValueError, match="TRANSLATION_TIMEOUT_SECONDS must be greater than 0"):
        GeminiTranslator(
            api_key="",
            model="gemini-test",
            timeout_seconds=0,
            client=fake_client(FakeModels()),
        )
