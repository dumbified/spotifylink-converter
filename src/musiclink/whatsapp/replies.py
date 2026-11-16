"""Turn a ConversionResult into the text the bot sends back.

Kept separate from the conversion itself so the wording can change without
touching any logic, and so another front-end can word things its own way.

Note that `result.detail` (the technical reason for an error) is never put
in a reply. It is for our logs; the person chatting gets a plain sentence.
"""

from musiclink.core.models import ConversionResult, ScoredCandidate

HELP = (
    "Send me a Spotify song link and I'll find it on Apple Music.\n"
    "(Only single songs for now, not albums or playlists.)"
)


def format_reply(result: ConversionResult) -> str:
    if result.status == "match":
        return _describe(result.matches[0])

    if result.status == "options":
        lines = ["I'm not sure which one it is. Closest matches:"]
        for number, match in enumerate(result.matches, start=1):
            lines.append("")
            lines.append(f"{number}. {_describe(match)}")
        return "\n".join(lines)

    if result.status == "not_found":
        return f"Couldn't find {_song_name(result)} on Apple Music."

    if result.status == "spotify_error":
        return "I couldn't read that song from Spotify. Please try again in a minute."

    if result.status == "apple_error":
        return "I couldn't search Apple Music just now. Please try again in a minute."

    return HELP  # "no_link"


def _describe(match: ScoredCandidate) -> str:
    song = match.candidate
    return f"{song.title} – {song.artist}\n{song.url}"


def _song_name(result: ConversionResult) -> str:
    track = result.track
    if track is None:
        return "that song"
    if track.artist:
        return f'"{track.title}" by {track.artist}'
    return f'"{track.title}"'
