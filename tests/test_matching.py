"""Tests for scoring and picking. Search results are saved real answers from Apple."""

import json
from pathlib import Path

import pytest

from musiclink.core.itunes import parse_search_results
from musiclink.core.matching import (
    CONFIDENT_SCORE,
    POSSIBLE_SCORE,
    artist_similarity,
    duration_similarity,
    pick_matches,
    rank_candidates,
    score_candidate,
    title_similarity,
)
from musiclink.core.models import Candidate, TrackInfo

FIXTURES = Path(__file__).parent / "fixtures"


def results(name: str) -> list[Candidate]:
    return parse_search_results(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


ENGLISH = results("itunes_search_english.json")
CHINESE = results("itunes_search_chinese.json")

RICK = TrackInfo(
    title="Never Gonna Give You Up",
    artist="Rick Astley",
    album="Whenever You Need Somebody",
    year=1987,
    duration_seconds=214,
)


def candidate(title="Song", artist="Artist", seconds=200, album=None) -> Candidate:
    return Candidate(
        title=title,
        artist=artist,
        url="https://music.apple.com/us/album/x/1?i=2",
        album=album,
        duration_seconds=seconds,
    )


# --- the three building blocks ---------------------------------------------------


def test_title_similarity_ignores_harmless_differences():
    assert title_similarity("Hey Jude - Remastered 2015", "Hey Jude") == 1.0
    assert title_similarity("Stay (with Justin Bieber)", "STAY") == 1.0
    assert title_similarity("Señorita", "Senorita") == 1.0
    assert title_similarity("Hello", "Goodbye") < 0.5


@pytest.mark.parametrize(
    ("spotify", "apple"),
    [
        ("Rick Astley", "Rick Astley"),
        ("Shawn Mendes, Camila Cabello", "Shawn Mendes & Camila Cabello"),
        ("Calvin Harris, Rihanna", "Calvin Harris"),  # Apple lists only the main artist
        ("Calvin Harris", "Calvin Harris feat. Rihanna"),
        ("Beyoncé", "Beyonce"),
    ],
)
def test_artist_similarity_same_artist(spotify, apple):
    assert artist_similarity(spotify, apple) == 1.0


def test_artist_similarity_different_artist():
    assert artist_similarity("Rick Astley", "Karaoke All Stars") < 0.5
    assert artist_similarity("黃霄雲", "余空") < 0.5


def test_duration_similarity():
    assert duration_similarity(214, 214) == 1.0
    assert duration_similarity(214, 216) == 1.0  # within 2 seconds
    assert 0.0 < duration_similarity(214, 222) < 1.0
    assert duration_similarity(214, 229) == 0.0
    assert duration_similarity(214, 347) == 0.0


# --- score_candidate -------------------------------------------------------------


def test_identical_song_scores_one():
    track = TrackInfo(title="Song", artist="Artist", duration_seconds=200)
    assert score_candidate(track, candidate()) == pytest.approx(1.0)


def test_different_version_is_marked_down():
    track = TrackInfo(title="Song", artist="Artist", duration_seconds=200)
    assert score_candidate(track, candidate(title="Song (Live)")) < POSSIBLE_SCORE + 0.1
    assert score_candidate(track, candidate(title="Song (Live)")) < CONFIDENT_SCORE


def test_matching_versions_are_not_marked_down():
    track = TrackInfo(title="Song - Live", artist="Artist", duration_seconds=200)
    assert score_candidate(track, candidate(title="Song (Live)")) == pytest.approx(1.0)


def test_cover_by_someone_else_is_not_confident():
    track = TrackInfo(title="Song", artist="Artist", duration_seconds=200)
    score = score_candidate(track, candidate(artist="Tribute Band"))
    assert score < CONFIDENT_SCORE


def test_different_song_by_same_artist_scores_low():
    track = TrackInfo(title="Together Forever", artist="Rick Astley", duration_seconds=214)
    score = score_candidate(track, candidate("Never Gonna Give You Up", "Rick Astley", 214))
    assert score < POSSIBLE_SCORE


def test_missing_lengths_are_left_out_not_punished():
    track = TrackInfo(title="Song", artist="Artist")
    assert score_candidate(track, candidate(seconds=None)) == pytest.approx(1.0)


# --- ranking and picking, on real search results ------------------------------------


def test_original_is_picked_over_remixes_and_same_album_wins_ties():
    confident, matches = pick_matches(RICK, ENGLISH)
    assert confident
    assert len(matches) == 1
    best = matches[0].candidate
    assert best.title == "Never Gonna Give You Up"
    # Four results tie on score; the one from the same album as on Spotify wins.
    assert best.album == "Whenever You Need Somebody"


def test_remix_is_picked_when_the_spotify_track_is_that_remix():
    track = TrackInfo(
        title="Never Gonna Give You Up - Cake Mix", artist="Rick Astley", duration_seconds=347
    )
    confident, matches = pick_matches(track, ENGLISH)
    assert confident
    assert matches[0].candidate.title == "Never Gonna Give You Up (Cake Mix)"


def test_chinese_song_skips_instrumental_and_covers():
    track = TrackInfo(title="星辰大海", artist="黃霄雲", album="星辰大海", duration_seconds=208)
    ranked = rank_candidates(track, CHINESE)
    assert ranked[0].candidate.title == "星辰大海"
    assert ranked[0].candidate.artist == "黃霄雲"
    assert ranked[0].score >= CONFIDENT_SCORE
    assert ranked[1].score < CONFIDENT_SCORE  # the instrumental (伴奏)


def test_artist_name_in_another_script_gives_options_not_a_confident_match():
    # Spotify sometimes shows a romanized name where Apple shows the original.
    track = TrackInfo(title="星辰大海", artist="Huang Xiaoyun", duration_seconds=208)
    confident, matches = pick_matches(track, CHINESE)
    assert not confident
    assert matches[0].candidate.artist == "黃霄雲"


def test_live_track_with_no_live_version_on_apple_gives_options():
    track = TrackInfo(
        title="Never Gonna Give You Up - Live", artist="Rick Astley", duration_seconds=220
    )
    confident, matches = pick_matches(track, ENGLISH)
    assert not confident
    assert 1 <= len(matches) <= 3


def test_title_only_is_never_confident():
    # This is what we have when Spotify's page was unreadable (oEmbed fallback).
    confident, matches = pick_matches(TrackInfo(title="星辰大海"), CHINESE)
    assert not confident
    assert matches


def test_unrelated_results_give_nothing():
    track = TrackInfo(title="Bohemian Rhapsody", artist="Queen", duration_seconds=354)
    assert pick_matches(track, ENGLISH) == (False, [])


def test_no_results_give_nothing():
    assert pick_matches(RICK, []) == (False, [])
