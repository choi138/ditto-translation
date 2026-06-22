from __future__ import annotations

import json
from typing import Protocol

from openai import OpenAI


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


class CodexLbTranslator:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key)

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

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional product localization engine. "
                        "Translate UI/product copy faithfully. Preserve placeholders, "
                        "variables, ICU tokens, printf tokens, HTML tags, markdown links, "
                        "line breaks, and leading/trailing whitespace. Return only JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_locale": source_locale,
                            "target_locales": list(target_locales),
                            "text": text,
                            "response_shape": {
                                locale: f"translation in {locale}" for locale in target_locales
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
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
