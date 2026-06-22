# Ditto Translation Webhook

Python FastAPI service for translating Ditto text changes through a local codex-lb
OpenAI-compatible endpoint.

## Behavior

- `ko` changes update `en` and `ja`.
- `en` changes update `ko` and `ja`.
- `ja` changes update `ko` and `en`.
- The changed source locale is never overwritten.
- Webhook request IDs are stored in SQLite for idempotency.
- Failed events are marked retryable so Ditto delivery retries can run again.
- Self-generated Ditto updates are remembered briefly and skipped when Ditto echoes
  them back as webhook events.

## Configuration

Copy `.env.example` to `.env` and set:

- `DITTO_API_TOKEN`: value sent as the Ditto `Authorization` header.
- `DITTO_WEBHOOK_SIGNING_KEY`: webhook signing key from Ditto.
- `ALLOW_UNSIGNED_WEBHOOKS`: keep `false` in production; set `true` only for local unsigned tests.
- `DITTO_LOCALE_VARIANT_IDS`: JSON mapping from locale code to Ditto variant developer ID.
  The base locale must map to `null`.
- `CODEX_LB_BASE_URL`: default is `http://127.0.0.1:2455/v1`.
- `CODEX_LB_API_KEY`: API key generated from the `~/Desktop/codex-lb` dashboard.
- `TRANSLATION_MODEL`: default is `gpt-5.3-codex`.

## Run

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Ditto should call:

```text
POST /webhooks/ditto
```

Health check:

```text
GET /health
```

## Verify

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```
