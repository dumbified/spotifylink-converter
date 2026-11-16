"""What extract_spotify_link must do. Read these as the specification."""

import pytest

from musiclink.core.links import extract_spotify_link
from musiclink.core.models import SpotifyLink

TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"  # 22 characters
CLEAN = f"https://open.spotify.com/track/{TRACK_ID}"
TRACK = SpotifyLink(kind="track", url=CLEAN)


# --- Links we should accept -------------------------------------------------


def test_plain_track_link():
    assert extract_spotify_link(CLEAN) == TRACK


def test_tracking_parameters_are_removed():
    assert extract_spotify_link(f"{CLEAN}?si=abc123def456&utm_source=copy") == TRACK


def test_link_inside_other_text():
    text = f"omg listen to this\n{CLEAN}?si=xyz it's so good"
    assert extract_spotify_link(text) == TRACK


def test_punctuation_after_the_link_is_ignored():
    assert extract_spotify_link(f"Have you heard {CLEAN}?") == TRACK
    assert extract_spotify_link(f"(this one: {CLEAN}).") == TRACK


def test_language_prefix_is_removed():
    # Spotify sometimes adds /intl-xx/ before /track/
    assert extract_spotify_link(f"https://open.spotify.com/intl-de/track/{TRACK_ID}") == TRACK


def test_host_is_not_case_sensitive():
    assert extract_spotify_link(f"https://Open.Spotify.com/track/{TRACK_ID}") == TRACK


def test_short_link():
    result = extract_spotify_link("check this https://spotify.link/AbCd1234Ef")
    assert result == SpotifyLink(kind="short", url="https://spotify.link/AbCd1234Ef")


def test_first_valid_link_wins():
    other = "https://open.spotify.com/track/0000000000000000000000"
    assert extract_spotify_link(f"{CLEAN} and {other}") == TRACK


def test_other_links_are_skipped_over():
    assert extract_spotify_link(f"https://youtu.be/dQw4w9WgXcQ or {CLEAN}") == TRACK


# --- Things we should reject (return None) ----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no link here, just words",
        "https://example.com/track/4cOdK2wGLETKBW3PvgPWqT",
        # Not a track (albums and playlists are out of scope for now)
        "https://open.spotify.com/album/4cOdK2wGLETKBW3PvgPWqT",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        # Track ID too short / too long / has odd characters
        "https://open.spotify.com/track/abc",
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqTXX",
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPW-T",
        # Extra path after the ID
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT/../../admin",
        # Short link with nothing after the slash
        "https://spotify.link/",
    ],
)
def test_not_a_spotify_track_link(text):
    assert extract_spotify_link(text) is None


@pytest.mark.parametrize(
    "text",
    [
        # Plain http is not allowed, only https
        "http://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        # Look-alike hosts
        "https://open.spotify.com.evil.io/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://evil-open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://openspotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://spotify.link.evil.io/AbCd1234Ef",
        # The real host is evil.io; "open.spotify.com" is only a username here
        "https://open.spotify.com@evil.io/track/4cOdK2wGLETKBW3PvgPWqT",
        # A username or a port has no business being in a Spotify link
        "https://user@open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://open.spotify.com:8443/track/4cOdK2wGLETKBW3PvgPWqT",
        # Spotify mentioned only in the path or query of another site
        "https://evil.io/open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://evil.io/?u=https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
    ],
)
def test_tricky_links_are_rejected(text):
    assert extract_spotify_link(text) is None
