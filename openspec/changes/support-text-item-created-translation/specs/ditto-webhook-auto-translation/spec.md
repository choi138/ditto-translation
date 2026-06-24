## MODIFIED Requirements

### Requirement: Ditto webhook event intake
The system SHALL expose an HTTP endpoint for Ditto text item webhook events and SHALL support text item creation, base text change, and variant text change payloads.

#### Scenario: Text item creation payload is accepted
- **WHEN** Ditto sends a `TextItem_Created` event with `projectId`, `textItemId`, and `text`
- **THEN** the system treats `text` as the source text for the configured base locale

#### Scenario: Base text change payload is accepted
- **WHEN** Ditto sends a `TextItem_Base_Text_Changed` event with `projectId`, `textItemId`, and `textAfter`
- **THEN** the system treats `textAfter` as the changed source text for the configured base locale

#### Scenario: Variant text change payload is accepted
- **WHEN** Ditto sends a `TextItem_Variant_Text_Changed` event with `projectId`, `textItemId`, `variantId`, and `variantTextAfter`
- **THEN** the system maps `variantId` to the changed source locale and treats `variantTextAfter` as the changed source text

#### Scenario: Unsupported webhook event is skipped
- **WHEN** Ditto sends a webhook event type outside the supported text item events
- **THEN** the system marks the event as skipped without requiring text item payload fields

#### Scenario: Malformed supported webhook event is skipped
- **WHEN** Ditto sends a supported text item event with malformed JSON or missing required text item fields
- **THEN** the system marks the event as skipped without translating or updating Ditto

### Requirement: Ditto target locale updates
The system SHALL update target locales through the Ditto Text Items API using configured locale-to-variant mappings.

#### Scenario: Ditto API token authorizes update requests
- **WHEN** a target locale update is sent to Ditto with a configured Ditto API token
- **THEN** the system sends the configured value verbatim as the `Authorization` header
