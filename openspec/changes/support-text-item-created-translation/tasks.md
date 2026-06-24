## 1. Webhook Intake

- [x] 1.1 Add a `TextItem_Created` webhook event constant.
- [x] 1.2 Parse `TextItem_Created` payloads into base-locale `SourceChange` values using `data.text`.

## 2. Tests

- [x] 2.1 Add a successful text-item creation webhook test that verifies base-locale source sync and translated target updates.
- [x] 2.2 Add malformed creation payload coverage to verify translation and Ditto updates are skipped.

## 3. Validation

- [x] 3.1 Run format, lint, type, unit test, and strict OpenSpec validation checks.

## 4. Ditto API Authorization

- [x] 4.1 Send configured Ditto API tokens verbatim as the `Authorization` header.
- [x] 4.2 Preserve explicitly configured authorization schemes such as `token`.
- [x] 4.3 Add regression coverage for Ditto update authorization headers.
