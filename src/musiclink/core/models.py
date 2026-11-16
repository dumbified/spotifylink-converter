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
