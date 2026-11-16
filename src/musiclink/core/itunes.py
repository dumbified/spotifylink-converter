"""Search Apple's catalogue with the free iTunes Search API.

Docs: https://performance-partners.apple.com/search-api

No key or account is needed. Apple asks for roughly 20 calls a minute at most,
which is far more than one person forwarding songs will ever use.

The search just returns Apple's best guesses for some words. Deciding which
result (if any) is really the same song is a separate job: see matching.py.
"""

import re
from urllib.parse import parse_qs, urlsplit

import httpx

from musiclink.core.models import Candidate

SEARCH_URL = "https://itunes.apple.com/search"
APPLE_MUSIC_HOST = "music.apple.com"

# How many results to ask for. More gives the matcher more to choose from.
DEFAULT_LIMIT = 15

# Search terms longer than this are almost certainly not a song name.
MAX_TERM_LENGTH = 200

COUNTRY_CODE = re.compile(r"[a-z]{2}")


class ITunesError(Exception):
    """The Apple search did not work (as opposed to working and finding nothing)."""


async def search_songs(
    term: str,
    client: httpx.AsyncClient,
    country: str = "us",
    limit: int = DEFAULT_LIMIT,
) -> list[Candidate]:
    """Search Apple Music for songs matching `term`, best guess first.

    `country` is the two-letter code of an Apple Music storefront ("us", "sg").
    It matters: catalogues differ by country, and so do the links.

    Returns an empty list when nothing matches. Raises ITunesError when the
    search itself fails.
    """
    term = term.strip()[:MAX_TERM_LENGTH]
    country = country.strip().lower()
    if not term:
        return []
    if not COUNTRY_CODE.fullmatch(country):
        raise ITunesError(f"Not a two-letter country code: {country!r}")

    # httpx turns this dictionary into ?term=...&media=music&... and takes
    # care of encoding spaces, accents and other special characters.
    params = {
        "term": term,
        "media": "music",
        "entity": "song",
        "country": country,
        "limit": str(limit),
    }

    try:
        response = await client.get(SEARCH_URL, params=params)
    except httpx.HTTPError as error:
        raise ITunesError(f"Could not reach Apple: {type(error).__name__}") from error

    if response.status_code in (403, 429):
        raise ITunesError("Apple is rate-limiting us, try again in a minute")
    if response.status_code != 200:
        raise ITunesError(f"Apple answered with status {response.status_code}")

    try:
        data = response.json()
    except ValueError as error:  # the body was not valid JSON
        raise ITunesError("Apple sent an unreadable answer") from error

    return parse_search_results(data)


def parse_search_results(data: object) -> list[Candidate]:
    """Turn Apple's JSON answer into Candidates, skipping anything malformed.

    This data comes from outside our program, so we don't assume its shape:
    every field is checked before it is used.
    """
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ITunesError("Apple's answer was not in the expected format")

    candidates = []
    for item in data["results"]:
        candidate = _to_candidate(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _to_candidate(item: object) -> Candidate | None:
    """Build one Candidate, or return None if this result is unusable."""
    if not isinstance(item, dict) or item.get("kind") != "song":
        return None

    title = item.get("trackName")
    artist = item.get("artistName")
    url = _clean_apple_music_url(item.get("trackViewUrl"))
    if not isinstance(title, str) or not isinstance(artist, str) or url is None:
        return None

    album = item.get("collectionName")
    milliseconds = item.get("trackTimeMillis")

    return Candidate(
        title=title,
        artist=artist,
        url=url,
        album=album if isinstance(album, str) else None,
        duration_seconds=round(milliseconds / 1000) if isinstance(milliseconds, int) else None,
    )


def _clean_apple_music_url(url: object) -> str | None:
    """Check a link really is an Apple Music link, and tidy it.

    This link is what the bot sends back to a person, so it gets the same
    treatment as the Spotify link on the way in: exact host, https only, and
    rebuilt from the parts we trust.

      in:  https://music.apple.com/us/album/song-name/1559885420?i=1559885421&uo=4
      out: https://music.apple.com/us/album/song-name/1559885420?i=1559885421
    """
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.lower() != APPLE_MUSIC_HOST:
        return None

    clean = f"https://{APPLE_MUSIC_HOST}{parts.path}"

    # ?i=<number> is what points at the song within its album. Keep only that.
    song_ids = parse_qs(parts.query).get("i", [])
    if song_ids and song_ids[0].isascii() and song_ids[0].isdigit():
        clean += f"?i={song_ids[0]}"
    return clean
