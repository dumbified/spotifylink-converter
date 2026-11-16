"""The whole conversion in one place: message text in, ConversionResult out.

    message  ->  find Spotify link  ->  read song details  ->  search Apple
             ->  pick the best match  ->  ConversionResult

This is the only function a front-end (the terminal command, the WhatsApp
bot, a future web page) needs to call. It never raises for the things we
expect to go wrong; it reports them in the result's `status` instead, so
each front-end can decide how to word the reply.
"""

import httpx

from musiclink.core.cleaning import split_artists, split_title
from musiclink.core.itunes import ITunesError, search_songs
from musiclink.core.links import extract_spotify_link
from musiclink.core.matching import pick_matches
from musiclink.core.models import Candidate, ConversionResult, TrackInfo
from musiclink.core.spotify import SpotifyError, fetch_track_info


async def convert(text: str, client: httpx.AsyncClient, country: str = "us") -> ConversionResult:
    """Convert the Spotify track link in `text` to Apple Music."""
    link = extract_spotify_link(text)
    if link is None:
        return ConversionResult(status="no_link")

    try:
        track = await fetch_track_info(link, client)
    except SpotifyError as error:
        return ConversionResult(status="spotify_error", detail=str(error))

    try:
        # First try: search with the title and artist exactly as Spotify has them.
        candidates = await search_songs(_full_search_term(track), client, country=country)
        confident, matches = pick_matches(track, candidates)

        # Second try, only if the first was not conclusive: a simpler search
        # (cleaned title + main artist) sometimes finds what the first missed.
        simple_term = _simple_search_term(track)
        if not confident and simple_term != _full_search_term(track):
            more = await search_songs(simple_term, client, country=country)
            candidates = _merge(candidates, more)
            confident, matches = pick_matches(track, candidates)
    except ITunesError as error:
        return ConversionResult(status="apple_error", track=track, detail=str(error))

    if confident:
        status = "match"
    elif matches:
        status = "options"
    else:
        status = "not_found"
    return ConversionResult(status=status, track=track, matches=tuple(matches))


def _full_search_term(track: TrackInfo) -> str:
    return f"{track.title} {track.artist or ''}".strip()


def _simple_search_term(track: TrackInfo) -> str:
    """The title without "(feat. X)" / "- Remastered", plus only the first artist."""
    base_title = split_title(track.title).base
    artists = split_artists(track.artist or "")
    return f"{base_title} {artists[0] if artists else ''}".strip()


def _merge(first: list[Candidate], second: list[Candidate]) -> list[Candidate]:
    """Join two result lists, dropping songs that appear in both."""
    seen = {candidate.url for candidate in first}
    return first + [candidate for candidate in second if candidate.url not in seen]
