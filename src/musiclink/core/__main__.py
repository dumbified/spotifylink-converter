"""Try the converter from the terminal, without WhatsApp.

    uv run musiclink 'https://open.spotify.com/track/...'

Add --debug before the link to also see every score.
"""

import asyncio
import os
import sys

from musiclink.core.convert import convert
from musiclink.core.http import make_client
from musiclink.core.models import ConversionResult, ScoredCandidate


def format_length(seconds: int | None) -> str:
    """214 -> "3:34"."""
    if seconds is None:
        return "?:??"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}:{rest:02d}"


def describe(match: ScoredCandidate, show_score: bool) -> str:
    song = match.candidate
    line = f"{song.title} - {song.artist} ({format_length(song.duration_seconds)})"
    if show_score:
        line += f"  [score {match.score:.2f}]"
    return f"{line}\n  {song.url}"


def print_result(result: ConversionResult, debug: bool) -> None:
    track = result.track
    if track is not None:
        length = format_length(track.duration_seconds)
        print(f"Spotify: {track.title} - {track.artist or 'unknown artist'} ({length})")
        print()

    if result.status == "match":
        print(describe(result.matches[0], debug))
    elif result.status == "options":
        print("Not sure which one. Closest matches:")
        for match in result.matches:
            print(describe(match, debug))
    elif result.status == "not_found":
        print("Couldn't find this song on Apple Music.")
    elif result.status == "no_link":
        print("No Spotify track link found in that text.")
    elif result.status == "spotify_error":
        print(f"Spotify problem: {result.detail}")
    elif result.status == "apple_error":
        print(f"Apple problem: {result.detail}")


async def run(text: str, country: str) -> ConversionResult:
    async with make_client() as client:
        return await convert(text, client, country=country)


def main() -> int:
    """Run the command. The number returned is the exit code (0 means success)."""
    arguments = sys.argv[1:]
    debug = "--debug" in arguments
    arguments = [argument for argument in arguments if argument != "--debug"]

    if not arguments:
        print("Usage: uv run musiclink [--debug] '<message containing a Spotify link>'")
        return 2

    # Everything typed after the command, joined back into one message.
    # Some terminals add backslashes before ? and = when you paste a link;
    # a real link never contains a backslash, so it is safe to drop them here.
    text = " ".join(arguments).replace("\\", "")

    # Your Apple Music country. Set it for one run like this:
    #   ITUNES_COUNTRY=sg uv run musiclink '<link>'
    country = os.environ.get("ITUNES_COUNTRY", "us")

    result = asyncio.run(run(text, country))
    print_result(result, debug)
    return 0 if result.status in ("match", "options") else 1


if __name__ == "__main__":
    sys.exit(main())
