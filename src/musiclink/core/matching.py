"""Decide which Apple Music search result is the same song as the Spotify track.

Apple's search returns its best guesses, but the top result is not always the
right one: it may be a remix, a live recording, an instrumental, or a cover by
someone else. So every result gets a score from 0.0 (nothing alike) to 1.0
(certainly the same recording), built from three questions:

    1. Is the title the same?          (worth 45%)
    2. Is the artist the same?         (worth 35%)
    3. Is it the same length?          (worth 20%)

Then the score is cut down if it is a different VERSION of the song (live
vs studio, a named remix, and so on).

The numbers below are judgement calls, tuned on real songs. They are named
constants so they are easy to find and adjust.
"""

from difflib import SequenceMatcher

from musiclink.core.cleaning import normalize, split_artists, split_title
from musiclink.core.models import Candidate, ScoredCandidate, TrackInfo

TITLE_WEIGHT = 0.45
ARTIST_WEIGHT = 0.35
DURATION_WEIGHT = 0.20

# Lengths within this many seconds count as identical...
DURATION_EXACT_SECONDS = 2
# ...and beyond this many seconds as completely different.
DURATION_TOO_FAR_SECONDS = 15

# If the titles are less alike than this, it is a different song, however
# well the artist matches. The score is halved.
MIN_TITLE_SIMILARITY = 0.6
WRONG_TITLE_FACTOR = 0.5

# Same song, different version (e.g. we want the studio track, this is live).
DIFFERENT_VERSION_FACTOR = 0.6

# At or above this score we reply with a single link.
CONFIDENT_SCORE = 0.85
# At or above this score a result is worth offering as an option.
POSSIBLE_SCORE = 0.55
MAX_OPTIONS = 3


def similarity(a: str, b: str) -> float:
    """How alike two strings are: 1.0 identical, 0.0 nothing in common.

    SequenceMatcher finds the longest runs of characters the two share.
    "senorita" vs "senorita" -> 1.0,  "hello" vs "help" -> about 0.67
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def title_similarity(track_title: str, candidate_title: str) -> float:
    return similarity(split_title(track_title).base, split_title(candidate_title).base)


def artist_similarity(track_artist: str, candidate_artist: str) -> float:
    """Compare artists, coping with "A, B" on one side and "A & B" on the other."""
    # First try the whole strings: "shawn mendes camila cabello" on both sides.
    whole = similarity(normalize(track_artist), normalize(candidate_artist))

    track_names = split_artists(track_artist)
    candidate_names = split_artists(candidate_artist)
    if not track_names or not candidate_names:
        return whole

    # Then the main (first-listed) artist against each name on the other side.
    # This handles one side listing featured artists and the other not.
    main = max(similarity(track_names[0], name) for name in candidate_names)
    return max(whole, main)


def duration_similarity(track_seconds: int, candidate_seconds: int) -> float:
    """1.0 if the lengths agree, sliding down to 0.0 as they drift apart."""
    difference = abs(track_seconds - candidate_seconds)
    if difference <= DURATION_EXACT_SECONDS:
        return 1.0
    if difference >= DURATION_TOO_FAR_SECONDS:
        return 0.0
    span = DURATION_TOO_FAR_SECONDS - DURATION_EXACT_SECONDS
    return 1.0 - (difference - DURATION_EXACT_SECONDS) / span


def score_candidate(track: TrackInfo, candidate: Candidate) -> float:
    """Score one Apple Music result against the Spotify track, from 0.0 to 1.0."""
    title_score = title_similarity(track.title, candidate.title)

    # Collect (score, weight) for each question we are able to ask. If Spotify
    # did not give us an artist or a length, that question is simply left out
    # and the remaining weights are scaled up to fill the gap.
    parts = [(title_score, TITLE_WEIGHT)]
    if track.artist:
        parts.append((artist_similarity(track.artist, candidate.artist), ARTIST_WEIGHT))
    if track.duration_seconds is not None and candidate.duration_seconds is not None:
        length_score = duration_similarity(track.duration_seconds, candidate.duration_seconds)
        parts.append((length_score, DURATION_WEIGHT))

    total_weight = sum(weight for _, weight in parts)
    score = sum(value * weight for value, weight in parts) / total_weight

    if title_score < MIN_TITLE_SIMILARITY:
        score *= WRONG_TITLE_FACTOR

    if split_title(track.title).tags != split_title(candidate.title).tags:
        score *= DIFFERENT_VERSION_FACTOR

    return score


def same_album(track: TrackInfo, candidate: Candidate) -> bool:
    if not track.album or not candidate.album:
        return False
    return normalize(track.album) == normalize(candidate.album)


def rank_candidates(track: TrackInfo, candidates: list[Candidate]) -> list[ScoredCandidate]:
    """Score every candidate and return them best first.

    Ties are common: the same recording is often on several albums. They are
    broken first by "is it from the same album as on Spotify?", and then by
    Apple's own order. (Python's sort is "stable": items that compare equal
    stay in the order they were given.)
    """
    scored = [
        ScoredCandidate(candidate, score_candidate(track, candidate)) for candidate in candidates
    ]
    # Sorting by a pair compares the score first, then True/False for the album.
    return sorted(
        scored,
        key=lambda item: (item.score, same_album(track, item.candidate)),
        reverse=True,
    )


def pick_matches(
    track: TrackInfo, candidates: list[Candidate]
) -> tuple[bool, list[ScoredCandidate]]:
    """Choose what to show the user.

    Returns (confident, matches):
      (True,  [best])         one clear answer
      (False, [a, b, c])      unsure; up to MAX_OPTIONS plausible guesses
      (False, [])             nothing close enough
    """
    ranked = rank_candidates(track, candidates)
    if not ranked:
        return False, []

    best = ranked[0]
    # Without an artist we only matched on a title, which is never enough to be sure.
    if best.score >= CONFIDENT_SCORE and track.artist:
        return True, [best]

    possible = [item for item in ranked if item.score >= POSSIBLE_SCORE]
    return False, possible[:MAX_OPTIONS]
