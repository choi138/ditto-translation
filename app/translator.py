from __future__ import annotations

import json
import logging
import time
from typing import Protocol, cast

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class Translator(Protocol):
    def translate(
        self,
        *,
        source_locale: str,
        target_locales: tuple[str, ...],
        text: str,
    ) -> dict[str, str]: ...


class TranslationError(RuntimeError):
    """Raised when translation output cannot be used safely."""


class GeminiModels(Protocol):
    def generate_content(self, **body: object) -> object: ...


class GeminiClient(Protocol):
    models: GeminiModels


SYSTEM_INSTRUCTION = (
    "You are a professional product localization engine. "
    "Translate UI/product copy faithfully. Preserve placeholders, "
    "variables, ICU tokens, printf tokens, HTML tags, markdown links, "
    "line breaks, and leading/trailing whitespace. Return only JSON."
)


class GeminiTranslator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 10.0,
        client: GeminiClient | None = None,
    ) -> None:
        if client is None and api_key.strip() == "":
            raise ValueError("GEMINI_API_KEY must be configured")
        if model.strip() == "":
            raise ValueError("TRANSLATION_MODEL must be configured")
        if timeout_seconds <= 0:
            raise ValueError("TRANSLATION_TIMEOUT_SECONDS must be greater than 0")

        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._client = client or cast(GeminiClient, genai.Client(api_key=api_key))

    def translate(
        self,
        *,
        source_locale: str,
        target_locales: tuple[str, ...],
        text: str,
    ) -> dict[str, str]:
        if not target_locales:
            return {}
        if text == "":
            return {locale: "" for locale in target_locales}

        request_body = json.dumps(
            {
                "source_locale": source_locale,
                "target_locales": list(target_locales),
                "text": text,
                "response_shape": {locale: f"translation in {locale}" for locale in target_locales},
            },
            ensure_ascii=False,
        )
        response_schema: dict[str, object] = {
            "type": "object",
            "properties": {locale: {"type": "string"} for locale in target_locales},
            "required": list(target_locales),
        }

        started_at = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=request_body,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    http_options=types.HttpOptions(
                        timeout=max(1, int(self._timeout_seconds * 1000)),
                    ),
                ),
            )
        except Exception as exc:
            logger.warning(
                "Gemini translation request failed",
                extra={
                    "model": self._model,
                    "source_locale": source_locale,
                    "target_locale_count": len(target_locales),
                    "source_text_length": len(text),
                    "duration_ms": _duration_ms(started_at),
                    "error_type": exc.__class__.__name__,
                },
            )
            raise TranslationError("Translation provider request failed") from exc

        logger.info(
            "Gemini translation request completed",
            extra={
                "model": self._model,
                "source_locale": source_locale,
                "target_locale_count": len(target_locales),
                "source_text_length": len(text),
                "duration_ms": _duration_ms(started_at),
            },
        )

        content = getattr(response, "text", None)
        if not isinstance(content, str):
            raise TranslationError("Translation response did not contain text content")
        return parse_translation_json(content, target_locales)


def parse_translation_json(content: str, target_locales: tuple[str, ...]) -> dict[str, str]:
    parsed = _load_json_object(content)
    translations: dict[str, str] = {}
    for locale in target_locales:
        value = parsed.get(locale)
        if not isinstance(value, str):
            raise TranslationError(f"Translation response missing string value for locale {locale}")
        translations[locale] = value
    return translations


def _load_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise TranslationError("Translation response was not valid JSON") from None
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError as exc:
            raise TranslationError("Translation response was not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise TranslationError("Translation response JSON must be an object")
    return parsed


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)
