"""Tests for reading song details from Spotify.

None of these touch the internet. Page parsing uses saved copies of real pages
(tests/fixtures), and the network code talks to a fake Spotify built with
httpx.MockTransport: a function that receives each request and decides the reply.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from musiclink.core.models import SpotifyLink, TrackInfo
from musiclink.core.spotify import (
    MAX_PAGE_BYTES,
    SpotifyError,
    TrackNotFoundError,
    fetch_track_info,
    parse_track_page,
)

FIXTURES = Path(__file__).parent / "fixtures"
TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"
TRACK_URL = f"https://open.spotify.com/track/{TRACK_ID}"
TRACK = SpotifyLink(kind="track", url=TRACK_URL)
SHORT = SpotifyLink(kind="short", url="https://spotify.link/AbCd1234Ef")

RICK = TrackInfo(
    title="Never Gonna Give You Up",
    artist="Rick Astley",
    album="Whenever You Need Somebody",
    year=1987,
    duration_seconds=214,
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fetch(link: SpotifyLink, handler) -> tuple[TrackInfo, list[str]]:
    """Run fetch_track_info against a fake Spotify.

    Returns the result plus the list of URLs the code asked for, so tests can
    check it never contacted anything it shouldn't.
    """
    requested: list[str] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    async def run() -> TrackInfo:
        transport = httpx.MockTransport(recording_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_track_info(link, client)

    return asyncio.run(run()), requested


# --- parse_track_page ---------------------------------------------------------


def test_parse_single_artist():
    assert parse_track_page(fixture("spotify_track_single_artist.html")) == RICK


def test_parse_two_artists_and_accents():
    info = parse_track_page(fixture("spotify_track_two_artists.html"))
    assert info.title == "Señorita"
    assert info.artist == "Shawn Mendes, Camila Cabello"
    assert info.year == 2019
    assert info.duration_seconds == 191


def test_parse_decodes_html_entities():
    html = """
        <meta property="og:type" content="music.song"/>
        <meta property="og:title" content="Rock &amp; Roll &#39;n&#39; Soul"/>
        <meta name="music:musician_description" content="Simon &amp; Garfunkel"/>
    """
    info = parse_track_page(html)
    assert info.title == "Rock & Roll 'n' Soul"
    assert info.artist == "Simon & Garfunkel"


def test_parse_falls_back_to_description_for_artist():
    html = """
        <meta property="og:type" content="music.song"/>
        <meta property="og:title" content="Song"/>
        <meta property="og:description" content="Some Artist · Some Album · Song · 2020"/>
    """
    info = parse_track_page(html)
    assert info.artist == "Some Artist"
    assert info.album == "Some Album"


def test_parse_copes_with_missing_extras():
    html = '<meta property="og:type" content="music.song"/><meta property="og:title" content="X"/>'
    assert parse_track_page(html) == TrackInfo(title="X")


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html><body>hello</body></html>",
        fixture("spotify_track_not_found.html"),
        # A title but not a song page (e.g. an album or the home page)
        '<meta property="og:type" content="music.album"/><meta property="og:title" content="X"/>',
    ],
)
def test_parse_rejects_pages_that_are_not_songs(html):
    with pytest.raises(SpotifyError):
        parse_track_page(html)


# --- fetch_track_info ---------------------------------------------------------


def test_fetch_track():
    def spotify(request):
        return httpx.Response(200, text=fixture("spotify_track_single_artist.html"))

    info, requested = fetch(TRACK, spotify)
    assert info == RICK
    assert requested == [TRACK_URL]


def test_fetch_unknown_track():
    def spotify(request):
        return httpx.Response(404, text=fixture("spotify_track_not_found.html"))

    with pytest.raises(TrackNotFoundError):
        fetch(TRACK, spotify)


def test_fetch_falls_back_to_oembed_when_page_is_unreadable():
    def spotify(request):
        if request.url.path == "/oembed":
            assert request.url.params["url"] == TRACK_URL
            return httpx.Response(200, text=fixture("spotify_oembed.json"))
        return httpx.Response(200, text="<html>Spotify changed its page layout</html>")

    info, _ = fetch(TRACK, spotify)
    assert info == TrackInfo(title="Never Gonna Give You Up")


def test_fetch_fails_cleanly_when_both_sources_fail():
    def spotify(request):
        return httpx.Response(503)

    with pytest.raises(SpotifyError):
        fetch(TRACK, spotify)


def test_fetch_turns_network_errors_into_spotify_errors():
    def spotify(request):
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(SpotifyError):
        fetch(TRACK, spotify)


def test_fetch_stops_reading_huge_pages():
    # The song tags are at the very end, far past the limit, so they must not be seen.
    padding = "<!-- padding -->" * (MAX_PAGE_BYTES // 16 + 1)
    huge_page = padding + fixture("spotify_track_single_artist.html")

    def spotify(request):
        if request.url.path == "/oembed":
            return httpx.Response(200, text=fixture("spotify_oembed.json"))
        return httpx.Response(200, text=huge_page)

    info, _ = fetch(TRACK, spotify)
    assert info == TrackInfo(title="Never Gonna Give You Up")  # came from oEmbed


# --- short links ----------------------------------------------------------------


def test_short_link_is_expanded():
    def spotify(request):
        if request.url.host == "spotify.link":
            return httpx.Response(307, headers={"location": f"{TRACK_URL}?si=abc123"})
        return httpx.Response(200, text=fixture("spotify_track_single_artist.html"))

    info, requested = fetch(SHORT, spotify)
    assert info == RICK
    # The tracking parameter was dropped before the second request.
    assert requested == [SHORT.url, TRACK_URL]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/steal",
        "http://169.254.169.254/latest/meta-data/",  # a classic SSRF target
        "http://localhost:8000/admin",
        "https://open.spotify.com/",  # what Spotify sends for an unknown short code
        "https://open.spotify.com/album/5Z9iiGl2FcIfa3BMiv6OIw",
        "",
    ],
)
def test_short_link_redirect_to_anything_else_is_not_followed(location):
    def spotify(request):
        return httpx.Response(307, headers={"location": location})

    requested: list[str] = []

    def recording(request):
        requested.append(str(request.url))
        return spotify(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recording)) as client:
            await fetch_track_info(SHORT, client)

    with pytest.raises(SpotifyError):
        asyncio.run(run())
    # Only the short link itself was ever contacted.
    assert requested == [SHORT.url]


def test_short_link_redirect_loop_gives_up():
    def spotify(request):
        return httpx.Response(307, headers={"location": "https://spotify.link/AbCd1234Ef"})

    with pytest.raises(SpotifyError, match="too many"):
        fetch(SHORT, spotify)


def test_short_link_without_redirect_fails():
    def spotify(request):
        return httpx.Response(200, text="<html>some landing page</html>")

    with pytest.raises(SpotifyError):
        fetch(SHORT, spotify)
