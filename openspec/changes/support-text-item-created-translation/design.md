## Context

The webhook service currently normalizes Ditto base and variant text change events into `SourceChange` and then reuses one processing pipeline for translation, Ditto updates, retry, idempotency, and loop prevention. Ditto text-item creation events are currently unsupported, so newly created base strings are skipped before translation starts.

## Goals / Non-Goals

**Goals:**

- Accept Ditto `TextItem_Created` webhook payloads.
- Normalize created text items into the existing base-locale `SourceChange` shape.
- Preserve all existing duplicate detection, retry, target update, source-variant sync, and self-generated webhook loop prevention behavior.

**Non-Goals:**

- Do not add a separate creation-specific translation pipeline.
- Do not support legacy Ditto webhook event names unless they are added to the spec later.
- Do not change locale mapping, translation provider, or Ditto update API behavior.

## Decisions

- Treat `TextItem_Created` as a base-locale source event. The payload's `data.text` field becomes `SourceChange.source_text`, `data.textItemId` remains the developer ID, and `data.projectId` remains the project context.
- Reuse the existing `source_variant_id=None` behavior. If the base locale has a configured variant ID, the current source synchronization logic writes the unchanged source text to that variant before updating translated target locales.
- Keep malformed creation payload handling aligned with supported change events. Missing or non-string `projectId`, `textItemId`, or `text` fields are skipped as malformed and do not call translation or Ditto update APIs.

## Risks / Trade-offs

- Ditto webhook contracts may differ between modern and legacy webhook versions. This change targets the modern `TextItem_Created` event only; legacy support should be specified separately if needed.
- Creation events may be delivered alongside later base text change events for the same text item. Existing request-ID idempotency handles duplicate deliveries of the same event, while repeated distinct events remain processed as source edits.
