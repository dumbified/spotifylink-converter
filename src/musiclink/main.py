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
from logging.handlers import RotatingFileHandler

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy() -> str:
        """A privacy policy page. Meta requires a link to one before an app can be published."""
        return PRIVACY_POLICY

    return app


PRIVACY_POLICY = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>musiclink privacy policy</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; }
</style>
</head>
<body>
<h1>musiclink privacy policy</h1>
<p>musiclink is a personal, non-commercial WhatsApp bot that converts Spotify
song links into Apple Music links. It only responds to phone numbers its
operator has explicitly allowed.</p>
<h2>What is processed</h2>
<ul>
<li>The text of a message sent to the bot, to find a Spotify link in it.</li>
<li>The sender's phone number, to check it is allowed and to send the reply.</li>
</ul>
<h2>What is stored</h2>
<p>Nothing is saved to a database or to disk. Message text is discarded as
soon as the reply is sent. Message IDs are kept in memory for a short time to
avoid answering the same message twice. Logs record that a message was handled
and only the last four digits of the phone number, never the message text.</p>
<h2>What is shared</h2>
<ul>
<li>Spotify receives a request for the public page of the linked song.</li>
<li>Apple receives a search for the song's title and artist.</li>
<li>Meta (WhatsApp) delivers the incoming message and the reply.</li>
</ul>
<p>No phone numbers or message text are sent to Spotify or Apple, and nothing
is sold or used for advertising.</p>
<h2>Contact</h2>
<p>Questions or removal requests can be sent to the bot's operator through the
WhatsApp number the bot uses.</p>
</body>
</html>
"""


def run() -> None:
    """Start the server. This is what `uv run musiclink-bot` calls."""
    # Check the settings up front, so a missing value gives a short, readable
    # message instead of a long technical error.
    try:
        settings = Settings()
    except ValidationError as error:
        print("The bot can't start because of these settings in your .env file:\n")
        for problem in error.errors():
            name = str(problem["loc"][0]).upper()
            reason = "is missing" if problem["type"] == "missing" else problem["msg"]
            print(f"  {name}: {reason}")
        print("\nIs there a .env file in this folder? Create it with:  cp .env.example .env")
        sys.exit(1)

    # Always log to the terminal. If a log file is configured, write there
    # too, so there is a record to look back at (capped at about 1 MB).
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        handlers.append(RotatingFileHandler(settings.log_file, maxBytes=500_000, backupCount=1))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    # httpx logs every URL it requests at INFO level. Quieten it.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # access_log=False: uvicorn's access log prints the full address of every
    # request, and Meta's verification request carries our verify token in its
    # address. Secrets must not end up in logs, so we log events ourselves.
    uvicorn.run(
        "musiclink.main:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.port,
        access_log=False,
    )


if __name__ == "__main__":
    run()
