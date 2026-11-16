"""Tests for the whole pipeline, with fake Spotify and Apple servers."""

import asyncio
from pathlib import Path

import httpx

from musiclink.core.convert import convert
from musiclink.core.models import ConversionResult

FIXTURES = Path(__file__).parent / "fixtures"
MESSAGE = "listen to this https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def run(text: str, spotify, apple, country: str = "us") -> tuple[ConversionResult, list[httpx.URL]]:
    """Run convert() with fake servers. Also returns every URL that was requested."""
    requested: list[httpx.URL] = []

    def internet(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        if request.url.host == "itunes.apple.com":
            return apple(request)
        return spotify(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(internet)) as client:
            return await convert(text, client, country=country)

    return asyncio.run(go()), requested


def spotify_ok(request):
    return httpx.Response(200, text=fixture("spotify_track_single_artist.html"))


def apple_ok(request):
    return httpx.Response(200, text=fixture("itunes_search_english.json"))


def apple_empty(request):
    return httpx.Response(200, text=fixture("itunes_search_empty.json"))


def test_confident_match():
    result, requested = run(MESSAGE, spotify_ok, apple_ok, country="sg")

    assert result.status == "match"
    assert result.track.title == "Never Gonna Give You Up"
    assert len(result.matches) == 1
    assert result.matches[0].candidate.url == (
        "https://music.apple.com/us/album/never-gonna-give-you-up/1559885420?i=1559885421"
    )
    # One page from Spotify, one search on Apple, nothing else.
    assert [url.host for url in requested] == ["open.spotify.com", "itunes.apple.com"]
    assert requested[1].params["term"] == "Never Gonna Give You Up Rick Astley"
    assert requested[1].params["country"] == "sg"


def test_no_link_contacts_nobody():
    result, requested = run("hello, how are you?", spotify_ok, apple_ok)
    assert result == ConversionResult(status="no_link")
    assert requested == []


def test_lookalike_link_contacts_nobody():
    text = "https://open.spotify.com.evil.io/track/4cOdK2wGLETKBW3PvgPWqT"
    result, requested = run(text, spotify_ok, apple_ok)
    assert result.status == "no_link"
    assert requested == []


def test_spotify_failure():
    def spotify_down(request):
        return httpx.Response(503)

    result, requested = run(MESSAGE, spotify_down, apple_ok)
    assert result.status == "spotify_error"
    assert result.detail
    assert all(url.host != "itunes.apple.com" for url in requested)


def test_apple_failure_still_reports_the_track():
    def apple_down(request):
        return httpx.Response(503)

    result, _ = run(MESSAGE, spotify_ok, apple_down)
    assert result.status == "apple_error"
    assert result.track.title == "Never Gonna Give You Up"


def test_not_found():
    result, _ = run(MESSAGE, spotify_ok, apple_empty)
    assert result.status == "not_found"
    assert result.matches == ()


def test_second_simpler_search_is_tried_when_the_first_finds_nothing():
    # A Spotify page for a track with a featured artist in the title.
    page = """
        <meta property="og:type" content="music.song"/>
        <meta property="og:title" content="Never Gonna Give You Up (feat. Somebody Else)"/>
        <meta name="music:musician_description" content="Rick Astley, Somebody Else"/>
        <meta name="music:duration" content="214"/>
    """
    terms = []

    def spotify(request):
        return httpx.Response(200, text=page)

    def apple(request):
        terms.append(request.url.params["term"])
        # Nothing for the long search, real results for the simple one.
        if len(terms) == 1:
            return httpx.Response(200, text=fixture("itunes_search_empty.json"))
        return httpx.Response(200, text=fixture("itunes_search_english.json"))

    result, _ = run(MESSAGE, spotify, apple)

    assert terms == [
        "Never Gonna Give You Up (feat. Somebody Else) Rick Astley, Somebody Else",
        "never gonna give you up rick astley",
    ]
    assert result.status == "match"


def test_options_when_only_other_versions_exist():
    page = """
        <meta property="og:type" content="music.song"/>
        <meta property="og:title" content="Never Gonna Give You Up - Live"/>
        <meta name="music:musician_description" content="Rick Astley"/>
        <meta name="music:duration" content="220"/>
    """

    def spotify(request):
        return httpx.Response(200, text=page)

    result, _ = run(MESSAGE, spotify, apple_ok)
    assert result.status == "options"
    assert 1 <= len(result.matches) <= 3
