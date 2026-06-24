## Purpose

Provide a Ditto webhook service that translates changed text through the configured codex-lb OpenAI-compatible provider and updates the remaining configured Ditto locales without overwriting the source locale.

## Requirements

### Requirement: Ditto webhook event intake
The system SHALL expose an HTTP endpoint for Ditto text change webhook events and SHALL support both base text and variant text change payloads.

#### Scenario: Base text change payload is accepted
- **WHEN** Ditto sends a `TextItem_Base_Text_Changed` event with `projectId`, `textItemId`, and `textAfter`
- **THEN** the system treats `textAfter` as the changed source text for the configured base locale

#### Scenario: Variant text change payload is accepted
- **WHEN** Ditto sends a `TextItem_Variant_Text_Changed` event with `projectId`, `textItemId`, `variantId`, and `variantTextAfter`
- **THEN** the system maps `variantId` to the changed source locale and treats `variantTextAfter` as the changed source text

#### Scenario: Unsupported webhook event is skipped
- **WHEN** Ditto sends a webhook event type outside the supported text change events
- **THEN** the system marks the event as skipped without requiring text-change payload fields

#### Scenario: Malformed supported webhook event is skipped
- **WHEN** Ditto sends a supported text change event with malformed JSON or missing required text-change fields
- **THEN** the system marks the event as skipped without translating or updating Ditto

### Requirement: Source locale preservation
The system SHALL use the changed locale as the source locale and MUST NOT translate that same locale as a target locale while processing the webhook event. When a base text change has a configured variant ID for the source locale, the system SHALL write the unchanged source text to that source-locale variant as source synchronization.

#### Scenario: Korean base source syncs Korean variant and updates English and Japanese
- **WHEN** the configured base locale is `ko`, `ko` maps to a variant ID, and a Korean base text change is processed
- **THEN** the system writes the unchanged Korean source text to the configured `ko` variant
- **AND** the system updates translated target locales `en` and `ja`

#### Scenario: English source updates only Korean and Japanese
- **WHEN** an English variant text change is processed
- **THEN** the system updates only `ko` and `ja`

#### Scenario: Japanese source updates only Korean and English
- **WHEN** a Japanese variant text change is processed
- **THEN** the system updates only `ko` and `en`

### Requirement: Ditto target locale updates
The system SHALL update target locales through the Ditto Text Items API using configured locale-to-variant mappings.

#### Scenario: Webhook project context is preserved
- **WHEN** a target locale update is sent to Ditto
- **THEN** the system includes the webhook `projectId` in the Ditto update payload

#### Scenario: Non-base locale requires variant ID
- **WHEN** locale mapping configuration assigns no variant developer ID to a non-base locale
- **THEN** the system rejects the configuration before processing webhooks

#### Scenario: Variant IDs must be unique
- **WHEN** locale mapping configuration assigns the same variant developer ID to multiple locales
- **THEN** the system rejects the configuration before processing webhooks

#### Scenario: Locale without variant ID updates base text
- **WHEN** the target locale maps to `null`
- **THEN** the system sends a Ditto text item update without `variantId`

#### Scenario: Variant locale target includes variant ID
- **WHEN** the target locale is a configured variant locale
- **THEN** the system sends a Ditto text item update with that locale's configured variant developer ID

### Requirement: codex-lb translation provider
The system SHALL translate text by calling the codex-lb OpenAI-compatible endpoint configured by environment variables.

#### Scenario: codex-lb API key is configured
- **WHEN** translation is requested
- **THEN** the system uses `CODEX_LB_BASE_URL`, `CODEX_LB_API_KEY`, and `TRANSLATION_MODEL` for the OpenAI-compatible chat completion call

#### Scenario: Target locales are requested as structured output
- **WHEN** translation is requested for multiple target locales
- **THEN** the system requests and validates a JSON object containing one string translation for each target locale

### Requirement: Ditto webhook authenticity
The system SHALL verify Ditto webhook signatures before processing production webhook events.

#### Scenario: Valid signature is accepted
- **WHEN** Ditto signature headers match the configured signing key and timestamp tolerance
- **THEN** the system processes the webhook event

#### Scenario: Invalid signature is rejected
- **WHEN** Ditto signature headers are missing, expired, or invalid
- **THEN** the system rejects the webhook event without translating or updating Ditto

### Requirement: Duplicate webhook handling
The system SHALL prevent duplicate processing of the same Ditto webhook delivery.

#### Scenario: Previously completed event is redelivered
- **WHEN** a webhook event with the same Ditto request ID has already succeeded or been skipped
- **THEN** the system returns a duplicate outcome and performs no translation or Ditto update

#### Scenario: Active event is redelivered
- **WHEN** a webhook event with the same Ditto request ID is already being processed and is not stale
- **THEN** the system returns a retryable response instead of acknowledging the redelivery as completed

#### Scenario: Previously failed event is redelivered
- **WHEN** a webhook event with the same Ditto request ID previously failed
- **THEN** the system retries processing instead of permanently skipping the event

### Requirement: Self-generated webhook loop prevention
The system SHALL prevent webhook cascades caused by its own Ditto target-locale updates.

#### Scenario: Echoed service update is received
- **WHEN** Ditto sends a webhook for the same project, text item, locale, and text that the system recently wrote
- **THEN** the system marks the event as skipped and performs no translation or Ditto update

#### Scenario: Repeated echoed service update is received
- **WHEN** Ditto sends multiple webhooks for the same project, text item, locale, and text that the system recently wrote
- **THEN** the system skips each matching webhook until the outbound update marker expires

#### Scenario: Failed service update is not marked as self-generated
- **WHEN** the system fails to write a target locale after exhausting Ditto update retries
- **THEN** the system does not create a self-generated update marker for that failed write

#### Scenario: Source-variant echo remains skipped after later target failure
- **WHEN** the system successfully writes a configured source-locale variant and a later target-locale update fails
- **THEN** an echoed webhook for the successful source-locale variant is skipped as self-generated while the original base webhook remains retryable

#### Scenario: Real source edit is received
- **WHEN** Ditto sends a webhook whose locale or text does not match a recent service-generated update
- **THEN** the system processes the webhook as a normal source edit

### Requirement: Retry and logging
The system SHALL retry transient translation and Ditto update failures and SHALL log processing outcomes.

#### Scenario: Translation fails transiently
- **WHEN** the translation provider fails before the configured retry limit is exhausted
- **THEN** the system retries translation before marking the event failed

#### Scenario: Ditto update fails transiently
- **WHEN** Ditto update fails before the configured retry limit is exhausted
- **THEN** the system retries the update before marking the event failed

#### Scenario: Ditto update fails permanently
- **WHEN** Ditto returns a non-retryable 4xx response other than rate limiting
- **THEN** the system does not retry the same Ditto update request and marks the webhook event as skipped

#### Scenario: Event processing completes
- **WHEN** a webhook event is processed, skipped, duplicated, or failed
- **THEN** the system logs the outcome without logging API keys or full translated text payloads
