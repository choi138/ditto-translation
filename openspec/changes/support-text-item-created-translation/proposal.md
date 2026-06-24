## Why

Ditto text items created from scratch are not currently translated because the webhook service only accepts base and variant text change events. Supporting Ditto's text-item creation webhook closes that gap so newly created source strings follow the same automatic translation flow as later edits.

## What Changes

- Accept Ditto `TextItem_Created` webhook events.
- Treat `data.text` from a created text item as source text for the configured base locale.
- Reuse the existing translation, target-locale update, idempotency, retry, and self-generated webhook loop prevention behavior.
- Keep unsupported or malformed creation payloads skipped without translating or updating Ditto.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `ditto-webhook-auto-translation`: Extend Ditto webhook intake to support text-item creation events in addition to text change events.

## Impact

- Updates OpenSpec requirements for Ditto webhook intake.
- Updates webhook event parsing in `app.models` and `app.service`.
- Adds service tests for successful and malformed text-item creation payloads.
