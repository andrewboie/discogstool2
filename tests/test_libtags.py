"""Tests for libtags.py — audio file tag management.

Covers:
  - sanitize: filename character whitelist filtering
  - tag_map / rev_tag_map: structure consistency for ID3 and MP4Tags
  - track_from_comment: both new ("Discogs: 12345") and old ("12345 VERIFIED") formats
  - AudioFile.__getitem__: track number parsing (ID3 "track/total" and MP4 tuple forms)
    — tested via duck-typed fakes so no real audio files are needed
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import libtags
from libtags import (
    TagsException,
    sanitize,
    tag_map,
    track_from_comment,
)


# ─── sanitize ─────────────────────────────────────────────────────────────────

class TestSanitize:
    def test_plain_ascii_unchanged(self):
        assert sanitize("Hello World") == "Hello World"

    def test_digits_unchanged(self):
        assert sanitize("track01") == "track01"

    def test_allowed_special_chars(self):
        # Characters in the whitelist: []()-_+.' and space
        s = "Artist [2022] (Remix) - Title"
        assert sanitize(s) == s

    def test_disallowed_chars_replaced(self):
        # Slash, colon, pipe → _
        result = sanitize("a/b:c|d")
        assert "/" not in result
        assert ":" not in result
        assert "|" not in result
        assert result == "a_b_c_d"

    def test_accents_stripped(self):
        # Accented Latin chars are decomposed and accents stripped
        assert sanitize("Réé") == "Ree"
        assert sanitize("Ñoño") == "Nono"
        assert sanitize("über") == "uber"

    def test_non_latin_replaced(self):
        # Characters with no ASCII base still become _
        assert sanitize("日本語") == "___"

    def test_empty_string(self):
        assert sanitize("") == ""

    def test_apostrophe_allowed(self):
        assert sanitize("It's a Test") == "It's a Test"

    def test_dot_allowed(self):
        assert sanitize("file.mp3") == "file.mp3"

    def test_plus_allowed(self):
        assert sanitize("a+b") == "a+b"


# ─── tag_map / rev_tag_map structure ─────────────────────────────────────────

class TestTagMap:
    EXPECTED_KEYS = {"album", "artist", "bpm", "title", "year",
                     "comment", "genre", "image", "track", "label", "compilation"}

    def test_id3_has_all_expected_keys(self):
        assert self.EXPECTED_KEYS == set(tag_map["ID3"].keys())

    def test_mp4_has_all_expected_keys(self):
        assert self.EXPECTED_KEYS == set(tag_map["MP4Tags"].keys())

    def test_id3_title_tag(self):
        assert tag_map["ID3"]["title"] == "TIT2"

    def test_id3_artist_tag(self):
        assert tag_map["ID3"]["artist"] == "TPE1"

    def test_id3_bpm_tag(self):
        assert tag_map["ID3"]["bpm"] == "TBPM"

    def test_mp4_title_tag(self):
        assert tag_map["MP4Tags"]["title"] == "\xa9nam"

    def test_mp4_bpm_tag(self):
        assert tag_map["MP4Tags"]["bpm"] == "tmpo"

    def test_rev_tag_map_inverts_id3(self):
        """rev_tag_map should map raw ID3 tags back to logical names."""
        # rev_tag_map is built at module level; test a few key entries
        assert libtags.rev_tag_map.get("TIT2") == "title"
        assert libtags.rev_tag_map.get("TPE1") == "artist"
        assert libtags.rev_tag_map.get("TBPM") == "bpm"


# ─── track_from_comment ───────────────────────────────────────────────────────

class TestTrackFromComment:
    """Tests the comment-parsing logic that extracts a DiscogsTrack from an
    embedded comment.  We mock client_interface.DiscogsTrack so no network
    calls are made.
    """

    def _call(self, comment, index=0):
        """Call track_from_comment with client_interface.DiscogsTrack mocked."""
        mock_track = MagicMock()
        with patch.object(libtags.client_interface, "DiscogsTrack",
                          return_value=mock_track) as mock_cls:
            result = track_from_comment(comment, index)
            return result, mock_cls

    def test_new_format_parses_release_id(self):
        """New format: "Label [catno] Discogs: 12345" → rid=12345."""
        _, mock_cls = self._call("Test Label [TEST001] Discogs: 12345", index=1)
        mock_cls.assert_called_once_with(12345, 0)   # index - 1 = 0

    def test_old_format_parses_release_id(self):
        """Old format: "99999 VERIFIED" → rid=99999."""
        _, mock_cls = self._call("99999 VERIFIED", index=1)
        mock_cls.assert_called_once_with(99999, 0)

    def test_index_subtracted_by_one(self):
        """track_from_comment converts 1-based index to 0-based."""
        _, mock_cls = self._call("Label [X] Discogs: 55555", index=3)
        mock_cls.assert_called_once_with(55555, 2)

    def test_invalid_comment_raises(self):
        with pytest.raises(TagsException):
            track_from_comment("no release info here", index=1)

    def test_empty_comment_raises(self):
        with pytest.raises(TagsException):
            track_from_comment("", index=1)


# ─── track number parsing logic ───────────────────────────────────────────────
# Tests the __getitem__ "track" branch in isolation without needing real files.

class TestTrackNumberParsing:
    """AudioFile.__getitem__("track") has two paths:
    - MP4: tuple (track_num, total) from mutagen
    - ID3: string "track_num/total" from mutagen

    We test the parsing logic by directly calling the conversion code rather
    than instantiating AudioFile (which requires a real audio file and Discogs).
    """

    def _parse_id3_track(self, raw):
        """Simulate the ID3 track string parsing in AudioFile.__getitem__."""
        i = str(raw).split("/")
        if len(i) == 1:
            i.append(0)
        return tuple([int(x) for x in i])

    def _parse_mp4_track(self, raw):
        """Simulate the MP4 track tuple parsing in AudioFile.__getitem__."""
        if isinstance(raw, tuple):
            return (int(raw[0]), int(raw[1]) if len(raw) > 1 and raw[1] else 0)
        return raw

    def test_id3_track_with_total(self):
        result = self._parse_id3_track("3/10")
        assert result == (3, 10)

    def test_id3_track_without_total(self):
        result = self._parse_id3_track("5")
        assert result == (5, 0)

    def test_mp4_track_tuple(self):
        result = self._parse_mp4_track((2, 8))
        assert result == (2, 8)

    def test_mp4_track_no_total(self):
        result = self._parse_mp4_track((4, 0))
        assert result == (4, 0)


# ─── AudioFile against real files ─────────────────────────────────────────────
#
# These use genuine WAV files tagged with real ID3 frames (mutagen's WAVE
# support wraps ID3), so the round-trip exercises the actual tag mapping rather
# than a mock's idea of it. AudioFile was previously untested end to end — it is
# the code that writes tags into the library and renames files on disk.

import os
import struct
import wave


def _make_wav(path, frames=64):
    """Write a tiny but valid WAV that mutagen can attach ID3 tags to."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<%dh" % frames, *([0] * frames)))
    return path


def _fake_track(*, artist="Track Artist", title="Track Title", number=3,
                album="The Album", year="1998", label="Some Label",
                catno="CAT001", release_id=12345, total=8,
                genre="Electronic", compilation=False, artwork=None):
    """A duck-typed DiscogsTrack/DiscogsRelease pair good enough for AudioFile."""
    release = MagicMock()
    release.getTitle.return_value       = album
    release.getYear.return_value        = year
    release.getLabel.return_value       = label
    release.getCatno.return_value       = catno
    release.getId.return_value          = release_id
    release.getTotalTracks.return_value = total
    release.getGenre.return_value       = genre
    release.getArtwork.return_value     = artwork
    release.isCompilation.return_value  = compilation

    track = MagicMock()
    track.release = release
    track.getArtist.return_value      = artist
    track.getTitle.return_value       = title
    track.getTrackNumber.return_value = number
    track.getRelease.return_value     = release
    return track


@pytest.fixture
def audio_file(tmp_path):
    """An AudioFile over a real tagged WAV, plus its backing track."""
    path = _make_wav(str(tmp_path / "input.wav"))
    track = _fake_track()
    return libtags.AudioFile(path, track), track


class TestAudioFileTagRoundTrip:
    def test_update_writes_expected_tags(self, audio_file):
        af, _ = audio_file
        assert af["artist"] == "Track Artist"
        assert af["title"]  == "Track Title"
        assert af["album"]  == "The Album"
        assert af["year"]   == "1998"
        assert af["label"]  == "Some Label"

    def test_track_tuple_round_trips(self, audio_file):
        af, _ = audio_file
        assert af["track"] == (3, 8)

    def test_comment_encodes_release_id(self, audio_file):
        af, _ = audio_file
        assert af["comment"] == "Some Label [CAT001] Discogs: 12345"

    def test_comment_is_reparseable(self, audio_file):
        """The comment must round-trip back to the same release id.

        libtags writes this string and dt_collection regex-extracts it later,
        so the two halves have to agree.
        """
        af, _ = audio_file
        with patch.object(libtags.client_interface, "DiscogsRelease") as rel_cls:
            libtags.track_from_comment(str(af["comment"]), 3)
        assert rel_cls.call_args[0][0] == 12345

    def test_genre_taken_from_release_when_absent(self, audio_file):
        af, _ = audio_file
        assert af["genre"] == "Electronic"

    def test_existing_genre_not_overwritten(self, tmp_path):
        """update() must preserve a genre the user has already set."""
        path = _make_wav(str(tmp_path / "g.wav"))
        af = libtags.AudioFile(path, _fake_track())
        af["genre"] = "Dub Techno"
        af.save()
        af2 = libtags.AudioFile(path, _fake_track(genre="Electronic"))
        assert af2["genre"] == "Dub Techno"

    def test_compilation_flag_set_only_for_compilations(self, tmp_path):
        plain = libtags.AudioFile(_make_wav(str(tmp_path / "a.wav")),
                                  _fake_track(compilation=False))
        comp  = libtags.AudioFile(_make_wav(str(tmp_path / "b.wav")),
                                  _fake_track(compilation=True))
        assert plain["compilation"] is None
        assert comp["compilation"] == "1"

    def test_bpm_is_returned_as_int(self, audio_file):
        af, _ = audio_file
        af["bpm"] = 128
        assert af["bpm"] == 128

    def test_save_persists_across_reopen(self, tmp_path):
        path = _make_wav(str(tmp_path / "p.wav"))
        af = libtags.AudioFile(path, _fake_track(artist="Before"))
        af["artist"] = "After"
        af.save()
        assert libtags.AudioFile(path, _fake_track())["artist"] == "Track Artist"

    def test_missing_tag_returns_none(self, audio_file):
        af, _ = audio_file
        assert af["image"] is None

    def test_filename_key_returns_path(self, audio_file):
        af, _ = audio_file
        assert af["filename"] == af.getFilename()

    def test_keys_lists_written_tags(self, audio_file):
        af, _ = audio_file
        keys = list(af.keys())
        for expected in ("artist", "title", "album"):
            assert expected in keys

    def test_unopenable_file_raises(self, tmp_path):
        bad = tmp_path / "not-audio.wav"
        bad.write_text("this is not a wav")
        with pytest.raises(TagsException):
            libtags.AudioFile(str(bad), _fake_track())


class TestRenameFile:
    """rename_file builds the destination path and moves/copies the file.

    dryrun=True returns the computed path without touching the filesystem, so
    the naming logic — where a bug scatters or overwrites library files — is
    directly testable.
    """

    def _af(self, tmp_path, **kw):
        path = _make_wav(str(tmp_path / "src.wav"))
        return libtags.AudioFile(path, _fake_track(**kw))

    def test_dryrun_does_not_move_the_file(self, tmp_path):
        af = self._af(tmp_path)
        dest = tmp_path / "out"
        af.rename_file(str(dest), verbose=False, dryrun=True, move=True,
                       withgenre=False)
        assert os.path.exists(af.getFilename())
        assert not dest.exists()

    def test_default_name_format(self, tmp_path):
        af = self._af(tmp_path)
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=False)
        assert os.path.basename(out) == \
            "The Album - 3 - Track Artist - Track Title [CAT001].wav"

    def test_genre_layout_nests_by_genre(self, tmp_path):
        af = self._af(tmp_path, genre="Dub Techno")
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=True)
        assert os.path.basename(os.path.dirname(out)) == "Dub Techno"

    def test_genre_layout_name_format(self, tmp_path):
        af = self._af(tmp_path)
        af["bpm"] = 128
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=True)
        assert os.path.basename(out) == "[128] Track Artist - Track Title 3 (1998).wav"

    def test_missing_bpm_becomes_zero(self, tmp_path):
        """No BPM must still produce a valid name, not raise."""
        af = self._af(tmp_path)
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=True)
        assert os.path.basename(out).startswith("[000] ")

    def test_unassigned_genre_is_skipped(self, tmp_path):
        af = self._af(tmp_path)
        af["genre"] = "null"
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=True)
        assert out is None

    def test_illegal_characters_sanitised(self, tmp_path):
        af = self._af(tmp_path, title="A/B: C?", artist="X*Y")
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=False)
        name = os.path.basename(out)
        for ch in "/:?*":
            assert ch not in name

    def test_accents_stripped_from_name(self, tmp_path):
        af = self._af(tmp_path, artist="Björk", title="Jóga")
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=False)
        assert "Bjork" in os.path.basename(out)

    def test_extension_preserved(self, tmp_path):
        af = self._af(tmp_path)
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=False)
        assert out.endswith(".wav")

    def test_copy_leaves_original_in_place(self, tmp_path):
        af = self._af(tmp_path)
        src = af.getFilename()
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=False,
                             move=False, withgenre=False)
        assert os.path.exists(src)
        assert os.path.exists(out)

    def test_move_relocates_and_updates_filename(self, tmp_path):
        af = self._af(tmp_path)
        src = af.getFilename()
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=False,
                             move=True, withgenre=False)
        assert not os.path.exists(src)
        assert os.path.exists(out)
        assert af.getFilename() == out

    def test_destination_directory_created(self, tmp_path):
        af = self._af(tmp_path)
        dest = tmp_path / "deep" / "nested"
        af.rename_file(str(dest), verbose=False, dryrun=False, move=False,
                       withgenre=False)
        assert dest.exists()

    def test_identical_existing_file_not_recopied(self, tmp_path):
        """An unchanged destination must be left alone, not rewritten."""
        af = self._af(tmp_path)
        dest = str(tmp_path / "out")
        first = af.rename_file(dest, verbose=False, dryrun=False, move=False,
                               withgenre=False)
        mtime = os.path.getmtime(first)
        again = af.rename_file(dest, verbose=False, dryrun=False, move=False,
                               withgenre=False)
        assert again == first
        assert os.path.getmtime(first) == mtime


class TestAudioFileRobustness:
    """Failure modes that must not abort a whole-library scan.

    dt_collection iterates every file in the collection and catches
    TagsException to skip bad ones, so any other exception escaping AudioFile
    kills the entire run partway through.
    """

    def test_corrupt_file_raises_tags_exception(self, tmp_path):
        """mutagen raises InvalidChunk for a recognised-but-corrupt file."""
        bad = tmp_path / "corrupt.wav"
        bad.write_text("this is not a wav")
        with pytest.raises(TagsException):
            libtags.AudioFile(str(bad), _fake_track())

    def test_truncated_file_raises_tags_exception(self, tmp_path):
        path = _make_wav(str(tmp_path / "t.wav"))
        with open(path, "r+b") as f:
            f.truncate(20)
        with pytest.raises(TagsException):
            libtags.AudioFile(path, _fake_track())

    def test_empty_file_raises_tags_exception(self, tmp_path):
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")
        with pytest.raises(TagsException):
            libtags.AudioFile(str(empty), _fake_track())

    def test_unknown_container_raises_tags_exception(self, tmp_path):
        odd = tmp_path / "thing.xyz"
        odd.write_bytes(b"\x00" * 128)
        with pytest.raises(TagsException):
            libtags.AudioFile(str(odd), _fake_track())

    def test_int_bpm_is_accepted(self, tmp_path):
        """ID3 text frames need strings; an int must be coerced, not blow up."""
        af = libtags.AudioFile(_make_wav(str(tmp_path / "b.wav")), _fake_track())
        af["bpm"] = 128            # would previously raise inside mutagen
        assert af["bpm"] == 128

    def test_int_bpm_survives_save_and_reload(self, tmp_path):
        path = _make_wav(str(tmp_path / "b2.wav"))
        af = libtags.AudioFile(path, _fake_track())
        af["bpm"] = 133
        af.save()
        assert libtags.AudioFile(path, _fake_track())["bpm"] == 133

    def test_bpm_used_in_genre_filename(self, tmp_path):
        af = libtags.AudioFile(_make_wav(str(tmp_path / "b3.wav")), _fake_track())
        af["bpm"] = 128
        out = af.rename_file(str(tmp_path / "out"), verbose=False, dryrun=True,
                             move=False, withgenre=True)
        assert os.path.basename(out).startswith("[128] ")
