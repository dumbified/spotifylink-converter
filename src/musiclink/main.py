"""Builds the web app and starts the server.

    uv run musiclink-bot

`create_app` is a "factory": a function that builds a fresh app. That lets
the tests build one with fake settings and a fake internet, instead of there
being a single global app wired to the real thing.
"""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

from musiclink.config import Settings
from musiclink.core.http import TIMEOUT_SECONDS, USER_AGENT
from musiclink.whatsapp.client import WhatsAppClient
from musiclink.whatsapp.limits import RateLimiter, RecentIds
from musiclink.whatsapp.webhook import BotState, router


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the app.

    settings:  defaults to reading the environment / .env file.
    transport: only for tests, to replace the real internet with a fake one.
    """
    if settings is None:
        settings = Settings()  # raises a clear error if something is missing

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Code before `yield` runs once at startup, code after it at shutdown.
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        ) as http:
            app.state.bot = BotState(
                settings=settings,
                http=http,
                whatsapp=WhatsAppClient(
                    http,
                    access_token=settings.whatsapp_access_token.get_secret_value(),
                    phone_number_id=settings.whatsapp_phone_number_id,
                    api_version=settings.graph_api_version,
                ),
                recent_ids=RecentIds(),
                rate_limiter=RateLimiter(),
            )
            yield

    # FastAPI normally publishes interactive documentation at /docs. Nobody
    # needs that on a webhook server, so it is switched off: less to attack.
    app = FastAPI(
        title="musiclink", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """A harmless address for checking the server (and the tunnel) is up."""
        return {"status": "ok"}

    return app


def run() -> None:
    """Start the server. This is what `uv run musiclink-bot` calls."""
    # Check the settings up front, so a missing value gives a short, readable
    # message instead of a long technical error.
    try:
        Settings()
    except ValidationError as error:
        print("The bot can't start because of these settings in your .env file:\n")
        for problem in error.errors():
            name = str(problem["loc"][0]).upper()
            reason = "is missing" if problem["type"] == "missing" else problem["msg"]
            print(f"  {name}: {reason}")
        print("\nIs there a .env file in this folder? Create it with:  cp .env.example .env")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # httpx logs every URL it requests at INFO level. Quieten it.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # 127.0.0.1 means "this computer only". The tunnel connects from this
    # machine, so nothing else on your Wi-Fi can reach the server directly.
    #
    # access_log=False: uvicorn's access log prints the full address of every
    # request, and Meta's verification request carries our verify token in its
    # address. Secrets must not end up in logs, so we log events ourselves.
    uvicorn.run(
        "musiclink.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        access_log=False,
    )


if __name__ == "__main__":
    run()
