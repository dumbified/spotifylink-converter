"""Find the Spotify link inside a WhatsApp message.

This is the security gate of the whole bot: later code will make web requests
to whatever URL this module returns. So it must only ever return URLs that are
really on Spotify, never something that just looks like Spotify.

Two rules keep it safe:

1. Allowlist, not blocklist. We describe exactly what a good link looks like
   and reject everything else, instead of trying to list every bad trick.
2. Rebuild, don't pass through. We never return the text the sender typed.
   We pull out the one piece we trust (the track ID) and build a fresh URL
   around it, so nothing unexpected can ride along.
"""

import re
from urllib.parse import urlsplit

from musiclink.core.models import SpotifyLink

TRACK_HOST = "open.spotify.com"
SHORT_HOST = "spotify.link"

# /track/<22 letters or digits>, optionally with a language prefix like /intl-de
# in front. The brackets around the ID "capture" it so we can read it back.
TRACK_PATH = re.compile(r"(?:/intl-[a-z]{2})?/track/([A-Za-z0-9]{22})")

# /<code>, where the code is letters and digits only.
SHORT_PATH = re.compile(r"/([A-Za-z0-9]+)")

# Punctuation that often ends up stuck to a link in a chat message.
LEADING_JUNK = "(<[\"'"
TRAILING_JUNK = ".,!?;:)>]\"'"


def extract_spotify_link(text: str) -> SpotifyLink | None:
    """Return the first valid Spotify track link (or short link) in `text`.

    Returns None if there isn't one.
    """
    # A link never contains spaces, so checking word by word is enough.
    for word in text.split():
        link = _check_word(word)
        if link is not None:
            return link
    return None


def _check_word(word: str) -> SpotifyLink | None:
    """Return a SpotifyLink if this one word is a valid Spotify link."""
    word = word.lstrip(LEADING_JUNK).rstrip(TRAILING_JUNK)

    try:
        parts = urlsplit(word)
    except ValueError:
        # urlsplit refuses some malformed input, e.g. "https://[oops".
        return None

    if parts.scheme != "https":
        return None

    # netloc is everything between "//" and the next "/". Comparing all of it
    # with == means a username ("user@host") or a port ("host:8443") makes the
    # check fail, as does any look-alike such as "open.spotify.com.evil.io".
    host = parts.netloc.lower()

    if host == TRACK_HOST:
        # fullmatch: the WHOLE path must fit the pattern, with nothing extra.
        match = TRACK_PATH.fullmatch(parts.path)
        if match:
            track_id = match.group(1)
            return SpotifyLink(kind="track", url=f"https://{TRACK_HOST}/track/{track_id}")

    if host == SHORT_HOST:
        match = SHORT_PATH.fullmatch(parts.path)
        if match:
            code = match.group(1)
            return SpotifyLink(kind="short", url=f"https://{SHORT_HOST}/{code}")

    return None
