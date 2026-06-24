## 1. Project Setup

- [x] 1.1 Add Python project metadata, dependencies, lint/type/test configuration, and runtime ignore rules
- [x] 1.2 Add environment example and README instructions for Ditto, locale mapping, and codex-lb configuration

## 2. Webhook Intake And Security

- [x] 2.1 Implement FastAPI health and Ditto webhook endpoints
- [x] 2.2 Implement Ditto signature verification, timestamp tolerance handling, and duplicate event key derivation
- [x] 2.3 Implement base and variant webhook payload parsing with source locale detection

## 3. Translation And Ditto Updates

- [x] 3.1 Implement codex-lb OpenAI-compatible translator with structured target-locale JSON validation
- [x] 3.2 Implement Ditto Text Items API update client with base/variant locale mapping behavior
- [x] 3.3 Ensure source locale is excluded from all target locale updates

## 4. Reliability And Loop Prevention

- [x] 4.1 Implement SQLite event status storage that allows retries for failed or stale events
- [x] 4.2 Implement outbound update memory to skip self-generated Ditto webhook echoes
- [x] 4.3 Implement retry behavior for translation and Ditto update failures
- [x] 4.4 Add outcome logging without API keys or full translated text payloads

## 5. Tests And Review

- [x] 5.1 Add tests for locale routing, source preservation, and Ditto payload target mapping
- [x] 5.2 Add tests for duplicate handling, failed-event retry, self-generated echo skipping, retry behavior, and signature rejection
- [x] 5.3 Run formatting, linting, type checking, and pytest
- [ ] 5.4 Run codex-review-loop and fix findings until the review is clean
