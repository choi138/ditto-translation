from __future__ import annotations

import logging
from functools import lru_cache

from anyio.to_thread import run_sync
from fastapi import FastAPI, HTTPException, Request, status

from app.config import Settings, get_settings
from app.ditto import DittoApiClient
from app.models import EventInProgressError
from app.security import SignatureError
from app.service import DittoTranslationService
from app.store import TranslationStore
from app.translator import GeminiTranslator


def create_app() -> FastAPI:
    configure_logging(get_settings())
    app = FastAPI(title="Ditto Translation Webhook")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/ditto")
    async def ditto_webhook(request: Request) -> dict[str, object]:
        raw_body = await request.body()
        headers = dict(request.headers)
        try:
            result = await run_sync(
                get_service().process_webhook,
                raw_body,
                headers,
            )
        except SignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        except EventInProgressError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ditto webhook event is already in progress",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ditto webhook processing failed",
            ) from exc

        return {
            "outcome": result.outcome,
            "reason": result.reason,
            "eventKey": result.event_key,
            "sourceLocale": result.source_locale,
            "updatedLocales": list(result.updated_locales),
        }

    return app


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@lru_cache
def get_service() -> DittoTranslationService:
    settings = get_settings()
    store = TranslationStore(settings.sqlite_path)
    translator = GeminiTranslator(
        api_key=settings.gemini_api_key,
        model=settings.translation_model,
    )
    ditto_client = DittoApiClient(
        base_url=settings.ditto_api_base_url,
        api_token=settings.ditto_api_token,
        force_variant_creation=settings.ditto_force_variant_creation,
    )
    return DittoTranslationService(
        settings=settings,
        store=store,
        translator=translator,
        ditto_client=ditto_client,
    )


app = create_app()
