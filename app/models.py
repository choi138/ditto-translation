from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WebhookEvent(StrEnum):
    BASE_TEXT_CHANGED = "TextItem_Base_Text_Changed"
    VARIANT_TEXT_CHANGED = "TextItem_Variant_Text_Changed"


class ProcessOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class EventStart(StrEnum):
    STARTED = "started"
    RETRY_STARTED = "retry_started"
    IN_PROGRESS = "in_progress"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class SourceChange:
    project_id: str
    developer_id: str
    source_locale: str
    source_text: str
    source_variant_id: str | None


@dataclass(frozen=True)
class ProcessResult:
    outcome: ProcessOutcome
    reason: str
    event_key: str
    source_locale: str | None = None
    updated_locales: tuple[str, ...] = ()


class WebhookPayloadError(ValueError):
    """Raised when a supported Ditto event is missing required fields."""


class EventInProgressError(RuntimeError):
    """Raised when the same webhook delivery is still being processed."""
