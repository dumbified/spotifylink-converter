"""Small data classes shared across the core."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SpotifyLink:
    """A Spotify link we found in a message and have checked is safe to fetch.

    kind:
        "track" - a full link. `url` is always the clean form
                  https://open.spotify.com/track/<id> (no ?si=..., no /intl-xx/).
        "short" - a spotify.link short link. `url` is https://spotify.link/<code>.
                  It still needs expanding before we know which track it is.
    """

    kind: Literal["track", "short"]
    url: str


@dataclass(frozen=True)
class TrackInfo:
    """What we know about a song after reading its Spotify page.

    Only `title` is guaranteed. The rest is None when Spotify didn't tell us
    (for example when we had to fall back to the oEmbed endpoint).
    """

    title: str
    artist: str | None = None  # several artists come as one string: "A, B"
    album: str | None = None
    year: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class Candidate:
    """One song from an Apple Music search: a possible match for a TrackInfo."""

    title: str
    artist: str
    url: str  # clean https://music.apple.com/... link, safe to send to the user
    album: str | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    """A Candidate plus how sure we are that it is the right song (0.0 to 1.0)."""

    candidate: Candidate
    score: float


# What can come out of a conversion:
#   "match"          one confident answer, in `matches`
#   "options"        not sure; the best few guesses are in `matches`
#   "not_found"      Apple Music has nothing close enough
#   "no_link"        the message had no Spotify track link in it
#   "spotify_error"  could not read the song from Spotify
#   "apple_error"    could not search Apple Music
ConversionStatus = Literal[
    "match", "options", "not_found", "no_link", "spotify_error", "apple_error"
]


@dataclass(frozen=True)
class ConversionResult:
    """The full answer to "convert this message". Front-ends turn this into a reply."""

    status: ConversionStatus
    track: TrackInfo | None = None  # what we read from Spotify, if we got that far
    matches: tuple[ScoredCandidate, ...] = ()  # best first
    detail: str = ""  # a short technical reason for errors, for logs
