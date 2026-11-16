"""Get a song's title and artist from Spotify without the Spotify Web API.

Spotify's official API needs a Premium account, so instead we read the same
"preview tags" that WhatsApp reads to draw a link preview. Every track page
has them near the top of its HTML, for example:

    <meta property="og:title" content="Never Gonna Give You Up"/>
    <meta name="music:musician_description" content="Rick Astley"/>

This is NOT an official API. Spotify can change its pages whenever it likes,
so everything here fails with a clear SpotifyError rather than guessing.
"""

from html.parser import HTMLParser

import httpx

from musiclink.core.links import TRACK_HOST, extract_spotify_link
from musiclink.core.models import SpotifyLink, TrackInfo

# A track page is about 300 KB and the tags we want are in the first 20 KB.
# Stop reading here so a huge response can't fill up our memory.
MAX_PAGE_BYTES = 512 * 1024

# A short link should reach the track in one hop. Allow a little slack.
MAX_REDIRECT_HOPS = 3

REDIRECT_STATUSES = {301, 302, 303, 307, 308}

OEMBED_URL = f"https://{TRACK_HOST}/oembed"


class SpotifyError(Exception):
    """We could not get the song details from Spotify."""


class TrackNotFoundError(SpotifyError):
    """Spotify says this track does not exist (or was removed)."""


async def fetch_track_info(link: SpotifyLink, client: httpx.AsyncClient) -> TrackInfo:
    """Return the title, artist and so on for a validated Spotify link.

    Raises SpotifyError (or its subclass TrackNotFoundError) if it can't.
    """
    try:
        if link.kind == "short":
            link = await _expand_short_link(link, client)

        try:
            html = await _get_page(link.url, client)
            return parse_track_page(html)
        except TrackNotFoundError:
            raise
        except SpotifyError:
            # The page was unreadable. oEmbed is an official, simpler endpoint
            # that at least gives us the title.
            return await _fetch_title_from_oembed(link.url, client)
    except httpx.HTTPError as error:
        # Timeouts, connection failures and so on.
        raise SpotifyError(f"Could not reach Spotify: {type(error).__name__}") from error


# --- Reading the preview tags ------------------------------------------------


class _MetaTagCollector(HTMLParser):
    """Walks through HTML and remembers every <meta> tag it sees.

    <meta property="og:title" content="X"/>  ->  self.tags["og:title"] = "X"
    """

    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name")
        content = attributes.get("content")
        # setdefault keeps the FIRST value if a tag appears more than once.
        if key and content:
            self.tags.setdefault(key, content.strip())


def parse_track_page(html: str) -> TrackInfo:
    """Pull the song details out of a Spotify track page's HTML.

    Raises SpotifyError if the page doesn't look like a song page.
    """
    collector = _MetaTagCollector()
    collector.feed(html)
    tags = collector.tags

    title = tags.get("og:title")
    if not title or tags.get("og:type") != "music.song":
        raise SpotifyError("The Spotify page has no song details")

    # og:description looks like "Artist · Album · Song · 1987".
    description = [part.strip() for part in tags.get("og:description", "").split(" · ")]
    has_expected_shape = len(description) == 4

    artist = tags.get("music:musician_description")
    if not artist and has_expected_shape:
        artist = description[0]

    return TrackInfo(
        title=title,
        artist=artist or None,
        album=description[1] if has_expected_shape else None,
        year=_to_int(tags.get("music:release_date", "")[:4]),
        duration_seconds=_to_int(tags.get("music:duration", "")),
    )


def _to_int(text: str) -> int | None:
    """Turn "1987" into 1987, and anything that isn't a plain number into None."""
    return int(text) if text.isascii() and text.isdigit() else None


# --- Talking to Spotify ------------------------------------------------------


async def _get_page(url: str, client: httpx.AsyncClient) -> str:
    """Download a track page, reading at most MAX_PAGE_BYTES of it."""
    # "stream" lets us read the answer piece by piece instead of all at once.
    async with client.stream("GET", url) as response:
        if response.status_code == 404:
            raise TrackNotFoundError("Spotify has no track at this link")
        if response.status_code != 200:
            raise SpotifyError(f"Spotify answered with status {response.status_code}")

        received = bytearray()
        async for chunk in response.aiter_bytes():
            received.extend(chunk)
            if len(received) >= MAX_PAGE_BYTES:
                break

    return bytes(received[:MAX_PAGE_BYTES]).decode("utf-8", errors="replace")


async def _expand_short_link(link: SpotifyLink, client: httpx.AsyncClient) -> SpotifyLink:
    """Follow a spotify.link short link to the full track link.

    We follow redirects by hand so that every address we are sent to goes back
    through extract_spotify_link, the same gate as the original message. If a
    redirect points anywhere else, we stop instead of fetching it.
    """
    for _ in range(MAX_REDIRECT_HOPS):
        response = await client.get(link.url)
        if response.status_code not in REDIRECT_STATUSES:
            raise SpotifyError("The short link did not redirect anywhere")

        next_link = extract_spotify_link(response.headers.get("location", ""))
        if next_link is None:
            raise SpotifyError("The short link does not lead to a Spotify track")
        if next_link.kind == "track":
            return next_link
        link = next_link

    raise SpotifyError("The short link redirected too many times")


async def _fetch_title_from_oembed(track_url: str, client: httpx.AsyncClient) -> TrackInfo:
    """Fallback: ask Spotify's oEmbed endpoint, which only knows the title."""
    # Passing `params` lets httpx encode the URL safely for us.
    response = await client.get(OEMBED_URL, params={"url": track_url})
    if response.status_code == 404:
        raise TrackNotFoundError("Spotify has no track at this link")
    if response.status_code != 200:
        raise SpotifyError(f"Spotify oEmbed answered with status {response.status_code}")

    try:
        title = response.json().get("title")
    except ValueError as error:  # the body was not valid JSON
        raise SpotifyError("Spotify oEmbed sent an unreadable answer") from error

    if not isinstance(title, str) or not title.strip():
        raise SpotifyError("Spotify oEmbed did not include a title")
    return TrackInfo(title=title.strip())
