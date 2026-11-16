"""Try the converter from the terminal, without WhatsApp.

    uv run musiclink 'https://open.spotify.com/track/...'

For now this prints what we learned from Spotify and what Apple's search
returned. Once matching exists, it will print the one best Apple Music link.
"""

import asyncio
import os
import sys

from musiclink.core.http import make_client
from musiclink.core.itunes import ITunesError, search_songs
from musiclink.core.links import extract_spotify_link
from musiclink.core.models import Candidate, TrackInfo
from musiclink.core.spotify import SpotifyError, fetch_track_info


def format_length(seconds: int | None) -> str:
    """214 -> "3:34"."""
    if seconds is None:
        return "?:??"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}:{rest:02d}"


async def lookup(text: str, country: str) -> tuple[TrackInfo, list[Candidate]] | None:
    link = extract_spotify_link(text)
    if link is None:
        return None
    async with make_client() as client:
        info = await fetch_track_info(link, client)
        term = f"{info.title} {info.artist or ''}"
        candidates = await search_songs(term, client, country=country)
        return info, candidates


def main() -> int:
    """Run the command. The number returned is the exit code (0 means success)."""
    if len(sys.argv) < 2:
        print("Usage: uv run musiclink '<message containing a Spotify link>'")
        return 2

    # Everything typed after the command, joined back into one message.
    # Some terminals add backslashes before ? and = when you paste a link;
    # a real link never contains a backslash, so it is safe to drop them here.
    text = " ".join(sys.argv[1:]).replace("\\", "")

    # Your Apple Music country. Set it for one run like this:
    #   ITUNES_COUNTRY=sg uv run musiclink '<link>'
    country = os.environ.get("ITUNES_COUNTRY", "us")

    try:
        result = asyncio.run(lookup(text, country))
    except SpotifyError as error:
        print(f"Spotify problem: {error}")
        return 1
    except ITunesError as error:
        print(f"Apple problem: {error}")
        return 1

    if result is None:
        print("No Spotify track link found in that text.")
        return 1

    info, candidates = result
    print("From Spotify")
    print(f"  {info.title} - {info.artist or 'unknown artist'}")
    length = format_length(info.duration_seconds)
    print(f"  {info.album or 'unknown album'}, {info.year or '?'}, {length}")
    print()
    print(f"Apple Music search results ({country}), not yet ranked")
    if not candidates:
        print("  nothing found")
    for number, candidate in enumerate(candidates[:5], start=1):
        length = format_length(candidate.duration_seconds)
        print(f"  {number}. {candidate.title} - {candidate.artist} ({length})")
        print(f"     {candidate.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
