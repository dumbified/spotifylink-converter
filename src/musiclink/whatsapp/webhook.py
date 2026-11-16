"""The two web addresses Meta talks to.

GET  /webhook   Called once, when you register the webhook in the Meta
                dashboard, to check the server is really yours.
POST /webhook   Called every time someone messages the bot.

Meta expects an answer to the POST within a few seconds, or it sends the
message again. Converting a song takes a second or two (it calls Spotify and
Apple), so we answer "got it" immediately and do the work afterwards as a
background task.
"""

import hmac
import json
import logging
import re
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from musiclink.config import Settings
from musiclink.core.convert import convert
from musiclink.whatsapp.client import WhatsAppClient, WhatsAppError
from musiclink.whatsapp.limits import RateLimiter, RecentIds
from musiclink.whatsapp.replies import HELP, format_reply
from musiclink.whatsapp.signature import is_valid_signature

logger = logging.getLogger("musiclink.whatsapp")

# A real webhook from Meta is a few kilobytes. Refuse anything far bigger.
MAX_BODY_BYTES = 256 * 1024

# WhatsApp's own limit for a text message.
MAX_TEXT_LENGTH = 4096

PHONE_NUMBER = re.compile(r"\d{6,20}")
MESSAGE_ID = re.compile(r"[\x21-\x7e]{1,200}")  # printable characters, no spaces

router = APIRouter()


@dataclass
class BotState:
    """Everything the webhook needs, created once when the app starts."""

    settings: Settings
    http: httpx.AsyncClient  # for Spotify and Apple
    whatsapp: WhatsAppClient
    recent_ids: RecentIds
    rate_limiter: RateLimiter


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    sender: str  # phone number, digits only
    text: str | None  # None for photos, voice notes, stickers...


def mask(phone_number: str) -> str:
    """Hide most of a phone number for logs: "6591234567" -> "******4567"."""
    return "*" * max(len(phone_number) - 4, 0) + phone_number[-4:]


# --- GET: Meta checking the webhook is ours ----------------------------------


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    request: Request,
    # Meta's parameter names contain dots, which Python names cannot, so each
    # one is given an alias.
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    state: BotState = request.app.state.bot
    expected = state.settings.whatsapp_verify_token.get_secret_value()

    token_matches = hmac.compare_digest(token.encode(), expected.encode())
    if mode != "subscribe" or not token_matches:
        logger.warning("Webhook verification failed (wrong verify token?)")
        raise HTTPException(status_code=403, detail="Verification failed")

    # Meta sends a number and expects exactly that number back. Refusing
    # anything else means this address can't be used to echo arbitrary text.
    if not challenge.isascii() or not challenge.isdigit():
        raise HTTPException(status_code=400, detail="Bad challenge")
    logger.info("Webhook verified by Meta")
    return challenge


# --- POST: a message arrived ---------------------------------------------------


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks) -> dict[str, str]:
    state: BotState = request.app.state.bot

    # The raw bytes, exactly as sent. The signature was made from these.
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Body too large")

    # 1. Is it really from Meta? Check BEFORE reading anything inside.
    secret = state.settings.whatsapp_app_secret.get_secret_value()
    if not is_valid_signature(secret, body, request.headers.get("x-hub-signature-256")):
        logger.warning("Rejected a webhook with a missing or wrong signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. Only now do we trust it enough to parse.
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Body is not JSON") from error

    # 3. Queue the work and answer straight away.
    for message in extract_messages(payload):
        if should_handle(message, state):
            background.add_task(handle_message, message, state)

    return {"status": "ok"}


def extract_messages(payload: object) -> list[IncomingMessage]:
    """Pick the messages out of Meta's deeply nested webhook JSON.

    The shape is: payload -> entry[] -> changes[] -> value -> messages[].
    Meta also uses this webhook for delivery receipts ("statuses"), which
    have no "messages" list and so produce nothing here.

    Even though the signature proved this came from Meta, nothing about the
    shape is assumed: anything unexpected is skipped rather than crashing.
    """
    messages = []
    for entry in _list(_get(payload, "entry")):
        for change in _list(_get(entry, "changes")):
            value = _get(change, "value")
            for raw in _list(_get(value, "messages")):
                message = _to_message(raw)
                if message is not None:
                    messages.append(message)
    return messages


def _get(thing: object, key: str) -> object:
    """thing[key] if thing is a dictionary, otherwise None."""
    return thing.get(key) if isinstance(thing, dict) else None


def _list(thing: object) -> list:
    """thing if it is a list, otherwise an empty list."""
    return thing if isinstance(thing, list) else []


def _to_message(raw: object) -> IncomingMessage | None:
    message_id = _get(raw, "id")
    sender = _get(raw, "from")
    if not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id):
        return None
    if not isinstance(sender, str) or not PHONE_NUMBER.fullmatch(sender):
        return None

    text = None
    if _get(raw, "type") == "text":
        body = _get(_get(raw, "text"), "body")
        if isinstance(body, str):
            text = body[:MAX_TEXT_LENGTH]

    return IncomingMessage(message_id=message_id, sender=sender, text=text)


def should_handle(message: IncomingMessage, state: BotState) -> bool:
    """The gatekeeping rules, in order. The cheapest checks come first."""
    if message.sender not in state.settings.allowed_sender_set:
        logger.info("Ignored a message from a sender not on the list: %s", mask(message.sender))
        return False
    if state.recent_ids.seen_before(message.message_id):
        logger.info("Ignored a repeated message")
        return False
    if not state.rate_limiter.allow(message.sender):
        logger.warning("Rate limit reached for %s", mask(message.sender))
        return False
    return True


async def handle_message(message: IncomingMessage, state: BotState) -> None:
    """Convert the link and reply. Runs after the webhook has already answered."""
    try:
        if message.text is None:
            reply = HELP
        else:
            result = await convert(
                message.text, state.http, country=state.settings.itunes_country.lower()
            )
            reply = format_reply(result)
            # Log what happened, but never the message text itself.
            logger.info("Handled a message: %s %s", result.status, result.detail)

        await state.whatsapp.send_text(message.sender, reply)
    except WhatsAppError as error:
        logger.error("Could not send the reply: %s", error)
    except Exception:
        # A background task has nobody to report to. Log it so the bug can
        # be found, and keep the server running.
        logger.exception("Unexpected error while handling a message")
