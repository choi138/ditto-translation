## Why

Ditto에서 디자이너가 특정 locale의 텍스트를 수정할 때, 나머지 locale 번역을 사람이 수동으로 맞추면 누락과 역방향 덮어쓰기 위험이 생긴다. Ditto Webhook과 codex-lb의 OpenAI-compatible endpoint를 연결해 변경된 언어를 source locale로 삼는 자동 번역 흐름을 만들 필요가 있다.

## What Changes

- Add a Python FastAPI webhook service for Ditto text change events.
- Detect the changed source locale from base text and variant text webhook payloads.
- Translate only non-source locales according to the configured Ditto locale mapping.
- Update Ditto target locales through the Ditto Text Items API without overwriting the source locale.
- Add persistent idempotency, self-generated webhook loop prevention, retry behavior, and structured logs.
- Configure translation through the local codex-lb server and API key generated from `~/Desktop/codex-lb`.

## Capabilities

### New Capabilities

- `ditto-webhook-auto-translation`: Receive Ditto text change webhooks and automatically translate/update the remaining locales while preserving the changed source locale.

### Modified Capabilities

None.

## Impact

- Adds a Python application package under `app/`.
- Adds FastAPI runtime dependencies, OpenAI-compatible client usage, Ditto API client usage, and SQLite state storage.
- Adds configuration for Ditto credentials, webhook signing, locale-to-variant mapping, codex-lb base URL/API key/model, retry settings, and runtime database path.
- Adds tests for locale routing, source-locale protection, deduplication, retry, signature verification, and loop prevention.
