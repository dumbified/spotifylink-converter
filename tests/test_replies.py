"""Tests for the wording of replies."""

from musiclink.core.models import Candidate, ConversionResult, ScoredCandidate, TrackInfo
from musiclink.whatsapp.replies import HELP, format_reply

TRACK = TrackInfo(title="Never Gonna Give You Up", artist="Rick Astley")


def scored(title: str, url: str, score: float = 1.0) -> ScoredCandidate:
    return ScoredCandidate(Candidate(title=title, artist="Rick Astley", url=url), score)


ORIGINAL = scored("Never Gonna Give You Up", "https://music.apple.com/us/album/a/1?i=2")
REMIX = scored("Never Gonna Give You Up (Cake Mix)", "https://music.apple.com/us/album/b/3?i=4")


def test_match():
    result = ConversionResult(status="match", track=TRACK, matches=(ORIGINAL,))
    assert format_reply(result) == (
        "Never Gonna Give You Up – Rick Astley\nhttps://music.apple.com/us/album/a/1?i=2"
    )


def test_options_are_numbered():
    result = ConversionResult(status="options", track=TRACK, matches=(ORIGINAL, REMIX))
    reply = format_reply(result)
    assert reply.startswith("I'm not sure which one it is.")
    assert "1. Never Gonna Give You Up – Rick Astley" in reply
    assert "2. Never Gonna Give You Up (Cake Mix) – Rick Astley" in reply
    assert reply.count("https://music.apple.com/") == 2


def test_not_found_names_the_song():
    reply = format_reply(ConversionResult(status="not_found", track=TRACK))
    assert reply == 'Couldn\'t find "Never Gonna Give You Up" by Rick Astley on Apple Music.'


def test_not_found_without_an_artist():
    reply = format_reply(ConversionResult(status="not_found", track=TrackInfo(title="X")))
    assert reply == 'Couldn\'t find "X" on Apple Music.'


def test_no_link_gives_help():
    assert format_reply(ConversionResult(status="no_link")) == HELP


def test_errors_never_leak_technical_details():
    secret_detail = "Spotify answered with status 503 at internal-host:8080"
    for status in ("spotify_error", "apple_error"):
        reply = format_reply(ConversionResult(status=status, track=TRACK, detail=secret_detail))
        assert "503" not in reply
        assert "internal-host" not in reply
        assert "try again" in reply.lower()
