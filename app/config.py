from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_locale_variant_ids() -> dict[str, str | None]:
    return {"ko": "ko", "en": "en", "ja": "ja"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ditto_api_token: str = ""
    ditto_webhook_signing_key: str | None = None
    allow_unsigned_webhooks: bool = False
    ditto_api_base_url: str = "https://api.dittowords.com/v2"
    ditto_locale_variant_ids: dict[str, str | None] = Field(
        default_factory=_default_locale_variant_ids
    )
    ditto_force_variant_creation: bool = False

    base_locale: str = "ko"

    gemini_api_key: str = ""
    translation_model: str = "gemini-3.5-flash"

    sqlite_path: Path = Path("var/app.sqlite3")
    webhook_timestamp_tolerance_seconds: int = 360
    in_progress_event_timeout_seconds: int = 600
    outbound_update_ttl_seconds: int = 1800

    translation_retry_attempts: int = 3
    translation_retry_initial_delay_seconds: float = 1.0
    ditto_retry_attempts: int = 3
    ditto_retry_initial_delay_seconds: float = 1.0
    retry_backoff_multiplier: float = 2.0
    retry_max_delay_seconds: float = 10.0

    log_level: str = "INFO"

    @field_validator("ditto_locale_variant_ids")
    @classmethod
    def normalize_locale_mapping(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        return {locale.strip(): variant_id for locale, variant_id in value.items()}

    @model_validator(mode="after")
    def validate_locale_mapping(self) -> Settings:
        if self.base_locale not in self.ditto_locale_variant_ids:
            raise ValueError("BASE_LOCALE must exist in DITTO_LOCALE_VARIANT_IDS")
        blank_variant_locales = [
            locale
            for locale, variant_id in self.ditto_locale_variant_ids.items()
            if variant_id is not None and variant_id.strip() == ""
        ]
        if blank_variant_locales:
            locales = ", ".join(sorted(blank_variant_locales))
            raise ValueError(f"Variant IDs must not be blank: {locales}")

        invalid_variant_locales = [
            locale
            for locale, variant_id in self.ditto_locale_variant_ids.items()
            if locale != self.base_locale and variant_id is None
        ]
        if invalid_variant_locales:
            locales = ", ".join(sorted(invalid_variant_locales))
            raise ValueError(f"Non-base locales must map to variant IDs: {locales}")
        variant_ids = [
            variant_id
            for variant_id in self.ditto_locale_variant_ids.values()
            if variant_id is not None
        ]
        duplicate_variant_ids = {
            variant_id for variant_id in variant_ids if variant_ids.count(variant_id) > 1
        }
        if duplicate_variant_ids:
            variants = ", ".join(sorted(duplicate_variant_ids))
            raise ValueError(f"Variant IDs must be unique across locales: {variants}")
        if len(self.ditto_locale_variant_ids) < 2:
            raise ValueError("At least two locales are required")
        return self

    @property
    def supported_locales(self) -> tuple[str, ...]:
        return tuple(self.ditto_locale_variant_ids.keys())

    @property
    def variant_id_to_locale(self) -> dict[str, str]:
        return {
            variant_id: locale
            for locale, variant_id in self.ditto_locale_variant_ids.items()
            if variant_id is not None
        }

    def variant_id_for_locale(self, locale: str) -> str | None:
        return self.ditto_locale_variant_ids[locale]


@lru_cache
def get_settings() -> Settings:
    return Settings()
