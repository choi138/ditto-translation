# Ditto Translation Webhook

Python FastAPI service for translating Ditto text changes through the Gemini API.

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
  Use `null` only for locales that should update base text instead of a variant.
- `GEMINI_API_KEY`: Gemini API key used by the translation provider.
- `TRANSLATION_MODEL`: default is `gemini-3.5-flash`.

For Docker or Compose deployments, pass `GEMINI_API_KEY` as a runtime
environment variable or deployment secret. Do not bake API keys into the image.

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
