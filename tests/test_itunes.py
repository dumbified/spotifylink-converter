"""Tests for the Apple search. The fixtures are saved copies of real answers."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from musiclink.core.itunes import ITunesError, parse_search_results, search_songs
from musiclink.core.models import Candidate

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def search(handler, term="Never Gonna Give You Up Rick Astley", **kwargs) -> list[Candidate]:
    """Run search_songs against a fake Apple."""

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await search_songs(term, client, **kwargs)

    return asyncio.run(run())


# --- parse_search_results -------------------------------------------------------


def test_parse_real_english_answer():
    candidates = parse_search_results(json.loads(fixture("itunes_search_english.json")))
    assert len(candidates) == 8
    assert candidates[0] == Candidate(
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        url="https://music.apple.com/us/album/never-gonna-give-you-up/1773292758?i=1773293184",
        album="The Best Of Me: Never Edition",
        duration_seconds=214,
    )
    # Remixes come back too. Choosing between them is matching.py's job.
    assert candidates[1].title == "Never Gonna Give You Up (Cake Mix)"


def test_parse_real_chinese_answer():
    candidates = parse_search_results(json.loads(fixture("itunes_search_chinese.json")))
    assert candidates[0].title == "星辰大海"
    assert candidates[0].artist == "黃霄雲"
    assert candidates[0].url.startswith("https://music.apple.com/us/album/")
    assert candidates[0].url.endswith("?i=1725936614")


def test_parse_empty_answer():
    assert parse_search_results(json.loads(fixture("itunes_search_empty.json"))) == []


def song(**changes) -> dict:
    """A minimal valid search result, with optional changes for a test."""
    item = {
        "kind": "song",
        "trackName": "Song",
        "artistName": "Artist",
        "trackViewUrl": "https://music.apple.com/us/album/song/111?i=222&uo=4",
    }
    item.update(changes)
    return item


def test_parse_copes_with_missing_optional_fields():
    assert parse_search_results({"results": [song()]}) == [
        Candidate(
            title="Song", artist="Artist", url="https://music.apple.com/us/album/song/111?i=222"
        )
    ]


@pytest.mark.parametrize(
    "bad_item",
    [
        "not a dictionary",
        song(kind="music-video"),
        song(trackName=None),
        song(artistName=42),
        song(trackViewUrl=None),
        # Links that are not really Apple Music must never reach the user
        song(trackViewUrl="http://music.apple.com/us/album/song/111?i=222"),
        song(trackViewUrl="https://music.apple.com.evil.io/us/album/song/111?i=222"),
        song(trackViewUrl="https://music.apple.com@evil.io/us/album/song/111?i=222"),
        song(trackViewUrl="https://evil.io/?next=https://music.apple.com/us/album/song/111"),
        song(trackViewUrl="javascript:alert(1)"),
    ],
)
def test_parse_skips_unusable_results(bad_item):
    # The bad result is dropped; the good one next to it survives.
    candidates = parse_search_results({"results": [bad_item, song()]})
    assert len(candidates) == 1


def test_parse_drops_extra_query_parameters():
    item = song(trackViewUrl="https://music.apple.com/us/album/song/111?i=222&uo=4&x=<script>")
    assert parse_search_results({"results": [item]})[0].url == (
        "https://music.apple.com/us/album/song/111?i=222"
    )


@pytest.mark.parametrize("data", [None, [], "text", {}, {"results": "nope"}])
def test_parse_rejects_answers_with_the_wrong_shape(data):
    with pytest.raises(ITunesError):
        parse_search_results(data)


# --- search_songs ---------------------------------------------------------------


def test_search_sends_the_right_request():
    seen = {}

    def apple(request):
        seen["url"] = request.url
        return httpx.Response(200, text=fixture("itunes_search_english.json"))

    candidates = search(apple, term="  Señorita & more  ", country="SG", limit=5)

    assert len(candidates) == 8
    assert seen["url"].host == "itunes.apple.com"
    assert seen["url"].path == "/search"
    assert dict(seen["url"].params) == {
        "term": "Señorita & more",  # trimmed, and safely encoded by httpx
        "media": "music",
        "entity": "song",
        "country": "sg",
        "limit": "5",
    }


def test_search_with_no_results():
    def apple(request):
        return httpx.Response(200, text=fixture("itunes_search_empty.json"))

    assert search(apple) == []


def test_search_with_blank_term_does_not_call_apple():
    def apple(request):
        raise AssertionError("Apple should not be contacted")

    assert search(apple, term="   ") == []


@pytest.mark.parametrize("country", ["", "usa", "u", "u$", "../", "us&limit=200"])
def test_search_rejects_bad_country_codes(country):
    def apple(request):
        raise AssertionError("Apple should not be contacted")

    with pytest.raises(ITunesError):
        search(apple, country=country)


@pytest.mark.parametrize("status", [400, 403, 429, 500, 503])
def test_search_fails_cleanly_on_error_statuses(status):
    def apple(request):
        return httpx.Response(status, text="nope")

    with pytest.raises(ITunesError):
        search(apple)


def test_search_fails_cleanly_on_garbage():
    def apple(request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(ITunesError):
        search(apple)


def test_search_turns_network_errors_into_itunes_errors():
    def apple(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(ITunesError):
        search(apple)
