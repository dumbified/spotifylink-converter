"""Tidy song titles and artist names so they can be compared fairly.

The same song is written differently on Spotify and Apple Music:

    Spotify:  "Never Gonna Give You Up - 2022 Remaster"
    Apple:    "Never Gonna Give You Up (2022 Remaster)"

    Spotify:  "Shawn Mendes, Camila Cabello"
    Apple:    "Shawn Mendes & Camila Cabello"

So before comparing we split a title into two things:

* the BASE: the actual name of the song, in a plain form
* the TAGS: what kind of recording it is ("live", "instrumental", "cake mix")

Two recordings are the same song when their bases match, and the same VERSION
of that song when their tags match too.
"""

import re
import unicodedata
from dataclasses import dataclass

# --- Words that tell us what a bracket like "(Live at Wembley)" means --------

# Extra people on the track. Not part of the title, and not a different version.
FEATURING_WORDS = {"feat", "ft", "featuring", "with"}

# Notes that don't change which recording it is. Safe to ignore.
HARMLESS_WORDS = {
    "remaster", "remastered", "mono", "stereo", "deluxe", "bonus", "explicit",
    "clean", "anniversary", "edition", "soundtrack", "ost", "from",
}  # fmt: skip
HARMLESS_PHRASES = ("single version", "album version", "original version", "original mix")

# A genuinely different recording. Each word maps to the tag we give it.
VERSION_WORDS = {
    "live": "live", "concert": "live", "unplugged": "acoustic",
    "acoustic": "acoustic", "stripped": "acoustic", "piano": "acoustic",
    "pianoforte": "acoustic",
    "instrumental": "instrumental", "karaoke": "instrumental", "inst": "instrumental",
    "cover": "cover", "tribute": "cover",
    "demo": "demo",
    "sped": "altered", "slowed": "altered", "reverb": "altered", "nightcore": "altered",
}  # fmt: skip
VERSION_PHRASES = {
    "backing track": "instrumental",
    "made famous by": "cover",
    "originally performed": "cover",
    "in the style of": "cover",
    # Chinese
    "伴奏": "instrumental", "纯音乐": "instrumental", "純音樂": "instrumental",
    "现场": "live", "現場": "live",
    "翻唱": "cover",
}  # fmt: skip

# "Cake Mix", "Radio Edit", "Taylor's Version": a named variant. The whole
# phrase becomes the tag, so "cake mix" and "club mix" count as different.
NAMED_VARIANT_WORDS = {"remix", "mix", "edit", "version", "ver", "rework", "dub", "flip", "bootleg"}

# Text inside (), [], and the full-width brackets used in Chinese and Japanese.
BRACKETED = re.compile(r"[(\[（【]([^()\[\]（）【】]*)[)\]）】]")

# " - " in the middle of a title, as in "Song - Live". Also matches long dashes.
DASH = re.compile(r"\s[-–—]\s")

# "Song feat. Someone" with no brackets around it.
TRAILING_FEATURING = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)

# The different ways several artists get joined into one string.
ARTIST_SEPARATORS = re.compile(
    r"\s*(?:,|&|;|/|、|\+|\band\b|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b)\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TitleParts:
    """A title split into the song's name and the kind of recording."""

    base: str  # normalized, e.g. "never gonna give you up"
    tags: frozenset[str]  # e.g. {"live"} or {"cake mix"}; empty for the original


def normalize(text: str) -> str:
    """Reduce text to a plain form for comparing: lower case, no accents or punctuation.

    "Señorita!"  ->  "senorita"
    "Don't Stop"  ->  "dont stop"
    "Simon & Garfunkel"  ->  "simon and garfunkel"
    """
    # NFKC folds look-alike characters together (e.g. full-width "Ａ" -> "A").
    text = unicodedata.normalize("NFKC", text).casefold()

    # NFD splits "ñ" into "n" plus a separate accent mark, which we then drop.
    decomposed = unicodedata.normalize("NFD", text)
    text = "".join(char for char in decomposed if not unicodedata.combining(char))

    text = text.replace("&", " and ")
    for apostrophe in ("'", "’", "`"):
        text = text.replace(apostrophe, "")

    # Every remaining symbol becomes a space. isalnum() is true for letters and
    # digits in any language, so Chinese, Korean and so on are kept.
    text = "".join(char if char.isalnum() else " " for char in text)

    # split() + join() squeezes runs of spaces down to single ones.
    return " ".join(text.split())


def split_title(title: str) -> TitleParts:
    """Split a title into its base name and its version tags.

    "Never Gonna Give You Up (2022 Remaster)" -> base "never gonna give you up", no tags
    "Hello - Live at the O2"                  -> base "hello", tags {"live"}
    "Stay (feat. Justin Bieber)"              -> base "stay", no tags
    "Levitating (The Blessed Madonna Remix)"  -> base "levitating",
                                                 tags {"the blessed madonna remix"}
    """
    tags: set[str] = set()

    def handle_bracket(match: re.Match[str]) -> str:
        """Decide what to do with one bracketed piece of the title."""
        kind, tag = _classify(match.group(1))
        if kind == "keep":
            return match.group(0)  # part of the real title, e.g. "(Don't Fear) The Reaper"
        if tag:
            tags.add(tag)
        return " "  # remove it from the title

    # re.sub calls handle_bracket once for every bracketed piece it finds.
    remaining = BRACKETED.sub(handle_bracket, title)

    # "Song - Live": look at what comes after the first dash the same way.
    pieces = DASH.split(remaining, maxsplit=1)
    if len(pieces) == 2:
        kind, tag = _classify(pieces[1])
        if kind != "keep":
            remaining = pieces[0]
            if tag:
                tags.add(tag)

    remaining = TRAILING_FEATURING.sub("", remaining)

    base = normalize(remaining)
    if not base:
        # The whole title was in brackets or similar. Better to compare the
        # full thing than to compare nothing.
        return TitleParts(base=normalize(title), tags=frozenset())
    return TitleParts(base=base, tags=frozenset(tags))


def _classify(text: str) -> tuple[str, str | None]:
    """Work out what a bracket or dash-suffix means.

    Returns one of:
      ("keep", None)   it is part of the song's real title
      ("drop", None)   it is noise, e.g. "feat. X" or "2011 Remaster"
      ("tag", "live")  it marks a different version of the song
    """
    plain = normalize(text)
    words = plain.split()
    if not words:
        return "drop", None

    if words[0] in FEATURING_WORDS:
        return "drop", None

    # Different-recording markers are checked before the harmless ones, so
    # that "Live - Remastered" still counts as live.
    for phrase, tag in VERSION_PHRASES.items():
        if phrase in plain:
            return "tag", tag
    for word in words:
        if word in VERSION_WORDS:
            return "tag", VERSION_WORDS[word]

    if any(phrase in plain for phrase in HARMLESS_PHRASES):
        return "drop", None
    if any(word in NAMED_VARIANT_WORDS for word in words):
        return "tag", plain
    if any(word in HARMLESS_WORDS for word in words):
        return "drop", None

    return "keep", None


def split_artists(artists: str) -> list[str]:
    """Split a combined artist string into normalized names, first artist first.

    "Shawn Mendes, Camila Cabello"   -> ["shawn mendes", "camila cabello"]
    "Shawn Mendes & Camila Cabello"  -> ["shawn mendes", "camila cabello"]
    """
    names = [normalize(name) for name in ARTIST_SEPARATORS.split(artists)]
    return [name for name in names if name]
