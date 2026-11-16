"""Try the converter from the terminal, without WhatsApp.

    uv run musiclink 'https://open.spotify.com/track/...'

For now this prints what we learned from Spotify. Once the Apple Music search
and matching exist, it will print the Apple Music link instead.
"""

import asyncio
import sys

from musiclink.core.http import make_client
from musiclink.core.links import extract_spotify_link
from musiclink.core.models import TrackInfo
from musiclink.core.spotify import SpotifyError, fetch_track_info


async def lookup(text: str) -> TrackInfo | None:
    link = extract_spotify_link(text)
    if link is None:
        return None
    async with make_client() as client:
        return await fetch_track_info(link, client)


def main() -> int:
    """Run the command. The number returned is the exit code (0 means success)."""
    if len(sys.argv) < 2:
        print("Usage: uv run musiclink '<message containing a Spotify link>'")
        return 2

    # Everything typed after the command, joined back into one message.
    # Some terminals add backslashes before ? and = when you paste a link;
    # a real link never contains a backslash, so it is safe to drop them here.
    text = " ".join(sys.argv[1:]).replace("\\", "")

    try:
        info = asyncio.run(lookup(text))
    except SpotifyError as error:
        print(f"Spotify problem: {error}")
        return 1

    if info is None:
        print("No Spotify track link found in that text.")
        return 1

    print(f"Title:  {info.title}")
    print(f"Artist: {info.artist or 'unknown'}")
    print(f"Album:  {info.album or 'unknown'}")
    print(f"Year:   {info.year or 'unknown'}")
    if info.duration_seconds is not None:
        minutes, seconds = divmod(info.duration_seconds, 60)
        print(f"Length: {minutes}:{seconds:02d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
