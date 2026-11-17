"""Tests for the webhook, end to end inside the test process.

TestClient sends requests straight into the FastAPI app without a real
server. The "internet" the app sees is fake: one function plays Spotify,
Apple and Meta, and records what the bot tried to send.
"""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from musiclink.config import Settings
from musiclink.main import create_app
from musiclink.whatsapp.replies import HELP
from musiclink.whatsapp.signature import compute_signature

FIXTURES = Path(__file__).parent / "fixtures"

APP_SECRET = "test-app-secret-0123456789"
VERIFY_TOKEN = "test-verify-token-0123456789"
ACCESS_TOKEN = "test-access-token-0123456789"
ME = "6591234567"
STRANGER = "15550001111"
SPOTIFY_MESSAGE = "listen! https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc"

SETTINGS = Settings(
    _env_file=None,
    whatsapp_verify_token=VERIFY_TOKEN,
    whatsapp_app_secret=APP_SECRET,
    whatsapp_access_token=ACCESS_TOKEN,
    whatsapp_phone_number_id="123456789012345",
    allowed_senders=ME,
    itunes_country="sg",
)


class FakeInternet:
    """Plays every outside service, and remembers what the bot did."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.sent: list[dict] = []  # WhatsApp messages the bot sent
        self.meta_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "open.spotify.com":
            html = (FIXTURES / "spotify_track_single_artist.html").read_text(encoding="utf-8")
            return httpx.Response(200, text=html)
        if host == "itunes.apple.com":
            data = (FIXTURES / "itunes_search_english.json").read_text(encoding="utf-8")
            return httpx.Response(200, text=data)
        if host == "graph.facebook.com":
            self.sent.append(json.loads(request.content))
            return httpx.Response(self.meta_status, json={"messages": [{"id": "wamid.reply"}]})
        raise AssertionError(f"The bot contacted an unexpected host: {host}")

    def hosts(self) -> list[str]:
        return [request.url.host for request in self.requests]


@pytest.fixture
def internet() -> FakeInternet:
    return FakeInternet()


@pytest.fixture
def client(internet):
    app = create_app(SETTINGS, transport=httpx.MockTransport(internet))
    # "with" runs the app's startup and shutdown code around the test.
    with TestClient(app) as test_client:
        yield test_client


def text_message(text: str, sender: str = ME, message_id: str = "wamid.TEST1") -> dict:
    return {
        "from": sender,
        "id": message_id,
        "timestamp": "1",
        "type": "text",
        "text": {"body": text},
    }


def payload(*messages: dict) -> dict:
    """Wrap messages the way Meta does."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "123456789012345"},
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


def post(client: TestClient, data: dict, secret: str = APP_SECRET) -> httpx.Response:
    """POST to the webhook, signed the way Meta signs."""
    body = json.dumps(data).encode()
    headers = {
        "content-type": "application/json",
        "x-hub-signature-256": compute_signature(secret, body),
    }
    return client.post("/webhook", content=body, headers=headers)


# --- GET /webhook: Meta's one-off check ---------------------------------------------


def verify(client, **changes):
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "1158201444",
    }
    params.update(changes)
    return client.get("/webhook", params=params)


def test_verification_echoes_the_challenge(client):
    response = verify(client)
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "changes",
    [
        {"hub.verify_token": "wrong-token"},
        {"hub.verify_token": ""},
        {"hub.mode": "unsubscribe"},
    ],
)
def test_verification_with_wrong_details_is_refused(client, changes):
    response = verify(client, **changes)
    assert response.status_code == 403
    assert "1158201444" not in response.text


def test_verification_does_not_echo_arbitrary_text(client):
    response = verify(client, **{"hub.challenge": "<script>alert(1)</script>"})
    assert response.status_code == 400
    assert "<script>" not in response.text


# --- POST /webhook: signature ---------------------------------------------------------


def test_unsigned_request_is_rejected(client, internet):
    response = client.post("/webhook", json=payload(text_message(SPOTIFY_MESSAGE)))
    assert response.status_code == 401
    assert internet.requests == []


def test_wrongly_signed_request_is_rejected(client, internet):
    response = post(
        client, payload(text_message(SPOTIFY_MESSAGE)), secret="attackers-guess-at-secret"
    )
    assert response.status_code == 401
    assert internet.requests == []


def test_body_changed_after_signing_is_rejected(client, internet):
    body = json.dumps(payload(text_message(SPOTIFY_MESSAGE))).encode()
    signature = compute_signature(APP_SECRET, body)
    tampered = body.replace(ME.encode(), STRANGER.encode())
    response = client.post("/webhook", content=tampered, headers={"x-hub-signature-256": signature})
    assert response.status_code == 401
    assert internet.requests == []


def test_signed_garbage_is_a_bad_request(client):
    body = b"this is not json"
    headers = {"x-hub-signature-256": compute_signature(APP_SECRET, body)}
    assert client.post("/webhook", content=body, headers=headers).status_code == 400


def test_oversized_body_is_rejected(client):
    body = b"x" * (256 * 1024 + 1)
    headers = {"x-hub-signature-256": compute_signature(APP_SECRET, body)}
    assert client.post("/webhook", content=body, headers=headers).status_code == 413


# --- POST /webhook: the happy path ------------------------------------------------------


def test_spotify_link_gets_an_apple_music_reply(client, internet):
    response = post(client, payload(text_message(SPOTIFY_MESSAGE)))

    assert response.status_code == 200
    assert internet.hosts() == ["open.spotify.com", "itunes.apple.com", "graph.facebook.com"]

    # The search used the configured country.
    assert internet.requests[1].url.params["country"] == "sg"

    # The reply went to the sender, through the right address, with the token in a header.
    meta_request = internet.requests[2]
    assert meta_request.url.path == "/v24.0/123456789012345/messages"
    assert meta_request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert ACCESS_TOKEN not in str(meta_request.url)

    [sent] = internet.sent
    assert sent["messaging_product"] == "whatsapp"
    assert sent["to"] == ME
    assert sent["type"] == "text"
    assert sent["text"]["body"] == (
        "Never Gonna Give You Up – Rick Astley\n"
        "https://music.apple.com/us/album/never-gonna-give-you-up/1559885420?i=1559885421"
    )


def test_message_without_a_link_gets_help(client, internet):
    post(client, payload(text_message("hello there")))
    assert internet.hosts() == ["graph.facebook.com"]
    assert internet.sent[0]["text"]["body"] == HELP


def test_non_text_message_gets_help(client, internet):
    photo = {
        "from": ME,
        "id": "wamid.PHOTO",
        "timestamp": "1",
        "type": "image",
        "image": {"id": "9"},
    }
    post(client, payload(photo))
    assert internet.sent[0]["text"]["body"] == HELP


# --- POST /webhook: the guards ----------------------------------------------------------


def test_stranger_is_ignored_completely(client, internet):
    response = post(client, payload(text_message(SPOTIFY_MESSAGE, sender=STRANGER)))
    assert response.status_code == 200  # Meta still gets its "got it"
    assert internet.requests == []  # but the bot does nothing and replies to nobody


def test_repeated_delivery_is_answered_once(client, internet):
    data = payload(text_message(SPOTIFY_MESSAGE, message_id="wamid.SAME"))
    assert post(client, data).status_code == 200
    assert post(client, data).status_code == 200
    assert len(internet.sent) == 1


def test_rate_limit_stops_a_flood(client, internet):
    for number in range(15):
        post(client, payload(text_message("hi", message_id=f"wamid.FLOOD{number}")))
    assert len(internet.sent) == 10  # the limiter's default: 10 per minute


def test_delivery_receipts_are_ignored(client, internet):
    receipt = payload()
    value = receipt["entry"][0]["changes"][0]["value"]
    del value["messages"]
    value["statuses"] = [{"id": "wamid.reply", "status": "delivered", "recipient_id": ME}]
    assert post(client, receipt).status_code == 200
    assert internet.requests == []


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        "just a string",
        {"entry": "not a list"},
        {"entry": [{"changes": [{"value": {"messages": ["not a dictionary"]}}]}]},
        {"entry": [{"changes": [{"value": {"messages": [{"from": ME}]}}]}]},  # no id
        {"entry": [{"changes": [{"value": {"messages": [{"id": "x", "from": "abc"}]}}]}]},
        {
            "entry": [
                {"changes": [{"value": {"messages": [{"id": 5, "from": ME, "type": "text"}]}}]}
            ]
        },
    ],
)
def test_strangely_shaped_payloads_do_not_crash(client, internet, data):
    assert post(client, data).status_code == 200
    assert internet.requests == []


def test_meta_refusing_the_reply_does_not_crash(client, internet):
    internet.meta_status = 401  # e.g. the access token has expired
    assert post(client, payload(text_message(SPOTIFY_MESSAGE))).status_code == 200
    # And the server is still healthy afterwards.
    assert client.get("/health").json() == {"status": "ok"}


# --- everything else ----------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_answers_head_for_uptime_monitors(client):
    assert client.head("/health").status_code == 200


def test_privacy_policy_page(client):
    response = client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "privacy policy" in response.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentation_pages_are_switched_off(client, path):
    assert client.get(path).status_code == 404
