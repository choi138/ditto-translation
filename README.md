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

- `DITTO_API_TOKEN`: Ditto API token. The value is sent verbatim as the
  `Authorization` header, so configure it exactly as Ditto requires.
- `DITTO_WEBHOOK_SIGNING_KEY`: webhook signing key from Ditto.
- `ALLOW_UNSIGNED_WEBHOOKS`: keep `false` in production; set `true` only for local unsigned tests.
- `DITTO_LOCALE_VARIANT_IDS`: JSON mapping from locale code to Ditto variant developer ID.
  Use `null` only for locales that should update base text instead of a variant.
- `GEMINI_API_KEY`: Gemini API key used by the translation provider.
- `TRANSLATION_MODEL`: default is `gemini-3.1-flash-lite`.
- `TRANSLATION_TIMEOUT_SECONDS`: Gemini request timeout in seconds; default is `10.0`.

For Docker or Compose deployments, pass `GEMINI_API_KEY` as a runtime
environment variable or deployment secret. Do not bake API keys into the image.
Environment variables take precedence over `.env`, so unset stale local secrets
before relying on updated `.env` values.

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

## Docker

Build the production image locally:

```bash
docker build -t ditto-translation:local .
```

Run with Docker Compose:

```bash
cp .env.example .env
DITTO_TRANSLATION_IMAGE=ditto-translation:local docker compose up -d --build
```

Compose reads runtime configuration from `.env`, maps host port `8080` to the
container, and stores SQLite state in the `ditto-translation-data` volume. Keep
real API keys and webhook signing keys in local or deployment secrets only. For
Docker env files, keep `DITTO_LOCALE_VARIANT_IDS` as raw JSON without surrounding
quotes.

Run the image directly when Compose is not needed:

```bash
docker run -d \
  --name ditto-translation \
  --env-file .env \
  -p 8080:8080 \
  -v ditto-translation-data:/app/var \
  ditto-translation:local
```

Check and stop the container:

```bash
curl http://localhost:8080/health
docker stop ditto-translation
```

Release images are published to GitHub Container Registry as:

```text
ghcr.io/choi138/ditto-translation:<version>
ghcr.io/choi138/ditto-translation:<major>.<minor>
ghcr.io/choi138/ditto-translation:latest
ghcr.io/choi138/ditto-translation:sha-<short-sha>
```

For a server deployment, pin the image tag before pulling and starting:

```bash
DITTO_TRANSLATION_IMAGE=ghcr.io/choi138/ditto-translation:0.1.0 docker compose pull
DITTO_TRANSLATION_IMAGE=ghcr.io/choi138/ditto-translation:0.1.0 docker compose up -d --no-build
```

## Vercel

Production deploys can be run manually with:

```bash
vercel deploy --prod
```

The `Vercel Release` GitHub Actions workflow deploys production only when a
non-prerelease GitHub release is published with a production SemVer tag such as
`v1.2.3`. Prereleases and RC tags such as `v1.2.3-rc.1` are skipped. Configure
these repository secrets before cutting a release:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Application runtime secrets such as `DITTO_API_TOKEN`,
`DITTO_WEBHOOK_SIGNING_KEY`, and `GEMINI_API_KEY` should stay in the Vercel
project's Production environment variables. Vercel applies environment variable
changes to the next production deployment.

## Verify

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```
