"""One place that decides how the bot talks to other websites."""

import httpx

# Be honest about who we are instead of pretending to be a browser.
USER_AGENT = "musiclink/0.1 (personal Spotify-to-Apple-Music link converter)"

# Give up if a site takes longer than this many seconds to answer.
TIMEOUT_SECONDS = 10.0


def make_client() -> httpx.AsyncClient:
    """Create the HTTP client the core uses for every outgoing request.

    follow_redirects=False is deliberate: a redirect is the server telling us
    "go fetch this other address instead". We never follow that blindly; the
    code that needs redirects checks each address first (see spotify.py).
    """
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
    )
