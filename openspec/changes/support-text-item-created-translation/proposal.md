## Why

Ditto text items created from scratch need to follow the same automatic
translation flow as later edits. Figma-created text items also receive a
source-derived Developer ID from Ditto, and that Developer ID becomes the key
used by downstream pull/export consumers. Newly created text items should
instead receive an opaque UUID Developer ID automatically so application keys
do not depend on mutable product copy.

## What Changes

- Accept Ditto `TextItem_Created` webhook events.
- Treat `data.text` from a created text item as source text for the configured base locale.
- Generate a canonical UUID Developer ID for each valid creation event and
  persist the assignment before mutating Ditto.
- Rename the newly created text item through `PATCH /v2/textItems`, using the
  webhook `textItemId` as the current `developerId` and the persisted UUID as
  `newDeveloperId`.
- Reuse the persisted UUID across duplicate deliveries and retry attempts,
  including when a previous attempt renamed the item but failed before
  translation processing completed.
- Use the UUID Developer ID for source-variant synchronization, translated
  target updates, outbound-update loop prevention, and subsequent logging.
- Reuse the existing translation, target-locale update, idempotency, retry, and self-generated webhook loop prevention behavior.
- Keep `TextItem_Developer_ID_Changed` unsupported as a translation source;
  the event emitted by this service's own rename is acknowledged and skipped.
- Keep unsupported or malformed creation payloads skipped without translating or updating Ditto.
- Apply UUID reassignment only to newly received creation events. Existing text
  items are not backfilled or migrated by this change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `ditto-webhook-auto-translation`: Extend Ditto webhook intake to support
  text-item creation events, assign UUID Developer IDs idempotently, and
  translate the created text using the reassigned ID.

## Impact

- Updates OpenSpec requirements for Ditto webhook intake.
- Updates webhook event parsing and creation processing in `app.models` and
  `app.service`.
- Extends the Ditto API client with Developer ID rename support via
  `newDeveloperId`.
- Extends the SQLite store with a durable mapping from a creation event and its
  original Developer ID to the assigned UUID and rename state.
- Adds coverage for successful UUID assignment, duplicate delivery, retries
  after partial rename success, rename failures, and translated updates using
  the UUID.
- Requires the Ditto workspace Developer ID configuration to accept the chosen
  UUID representation, including its characters and maximum length.
- Introduces a brief interval after Figma creation in which Ditto still exposes
  its automatically generated Developer ID before the webhook-driven rename
  completes.
