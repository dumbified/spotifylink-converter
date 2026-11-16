"""Tests for title and artist cleaning."""

import pytest

from musiclink.core.cleaning import normalize, split_artists, split_title


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Never Gonna Give You Up", "never gonna give you up"),
        ("  Extra   Spaces  ", "extra spaces"),
        ("Señorita!", "senorita"),
        ("Beyoncé", "beyonce"),
        ("Don't Stop Believin’", "dont stop believin"),
        ("Simon & Garfunkel", "simon and garfunkel"),
        ("AC/DC", "ac dc"),
        ("P!nk", "p nk"),
        ("ＡＢＣ　１２３", "abc 123"),  # full-width characters
        ("星辰大海", "星辰大海"),  # Chinese is kept as it is
        ("", ""),
        ("!!!", ""),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize(
    ("title", "base", "tags"),
    [
        # Nothing to remove
        ("Never Gonna Give You Up", "never gonna give you up", set()),
        # Harmless notes are dropped without a tag
        ("Never Gonna Give You Up (2022 Remaster)", "never gonna give you up", set()),
        ("Never Gonna Give You Up - 2022 Remaster", "never gonna give you up", set()),
        ("Hey Jude - Remastered 2015", "hey jude", set()),
        ("Yesterday (Mono)", "yesterday", set()),
        ('Let It Go (From "Frozen")', "let it go", set()),
        ("Song (Album Version)", "song", set()),
        ("Song [Explicit]", "song", set()),
        # Featured artists are dropped without a tag
        ("Stay (feat. Justin Bieber)", "stay", set()),
        ("Stay (with Justin Bieber)", "stay", set()),
        ("Stay [ft. Justin Bieber]", "stay", set()),
        ("Stay feat. Justin Bieber", "stay", set()),
        # Different recordings get a tag
        ("Hello (Live)", "hello", {"live"}),
        ("Hello - Live at the O2", "hello", {"live"}),
        ("Hello (Live) [Remastered]", "hello", {"live"}),
        ("Hello - Live / Remastered", "hello", {"live"}),
        ("Hello (Acoustic)", "hello", {"acoustic"}),
        ("Never Gonna Give You Up (Pianoforte)", "never gonna give you up", {"acoustic"}),
        ("Hello (Instrumental)", "hello", {"instrumental"}),
        ("Hello (Karaoke Version)", "hello", {"instrumental"}),
        ("Hello (Demo)", "hello", {"demo"}),
        ("Hello (Sped Up)", "hello", {"altered"}),
        ("Hello (Made Famous by Adele)", "hello", {"cover"}),
        # Named variants keep their whole name as the tag
        ("Never Gonna Give You Up (Cake Mix)", "never gonna give you up", {"cake mix"}),
        ("Levitating (The Blessed Madonna Remix)", "levitating", {"the blessed madonna remix"}),
        ("Blinding Lights - Radio Edit", "blinding lights", {"radio edit"}),
        ("Love Story (Taylor's Version)", "love story", {"taylors version"}),
        ("Song (feat. Someone) [Club Mix]", "song", {"club mix"}),
        # Chinese, including full-width brackets
        ("星辰大海 (伴奏)", "星辰大海", {"instrumental"}),
        ("星辰大海（Live）", "星辰大海", {"live"}),
        ("星辰大海 (現場版)", "星辰大海", {"live"}),
        # Brackets and dashes that are part of the real title are kept
        ("(Don't Fear) The Reaper", "dont fear the reaper", set()),
        ("Hello (Goodbye)", "hello goodbye", set()),
        ("Anti-Hero", "anti hero", set()),
        ("Jay-Z - The Story", "jay z the story", set()),
        # Words like "live" inside a normal title are not tags
        ("Live and Let Die", "live and let die", set()),
        ("Mix It Up", "mix it up", set()),
        # If stripping would leave nothing, the whole title is used
        ("(Remix)", "remix", set()),
    ],
)
def test_split_title(title, base, tags):
    parts = split_title(title)
    assert parts.base == base
    assert parts.tags == tags


@pytest.mark.parametrize(
    ("artists", "expected"),
    [
        ("Rick Astley", ["rick astley"]),
        ("Shawn Mendes, Camila Cabello", ["shawn mendes", "camila cabello"]),
        ("Shawn Mendes & Camila Cabello", ["shawn mendes", "camila cabello"]),
        ("Calvin Harris feat. Rihanna", ["calvin harris", "rihanna"]),
        ("A x B", ["a", "b"]),
        ("黃霄雲", ["黃霄雲"]),
        ("周杰倫、費玉清", ["周杰倫", "費玉清"]),
        ("", []),
    ],
)
def test_split_artists(artists, expected):
    assert split_artists(artists) == expected
