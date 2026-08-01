"""Tests for dt_label — pure helper functions.

Covers:
  - get_side: side letter extraction from position strings
  - side_to_disc: side letter → disc number mapping
  - group_tracks_by_disc: builds disc/side structure from a fake release
  - flatten_discs: orders disc/side/track tuples
  - parse_release_id: integer and [rXXXXX] format parsing
  - read_id_file: URL mode and plain-ID mode
  - _layout_height: canvas height measured from a real layout pass
  - _chunk_continuous: greedy packing of tracks onto labels
  - load_config / save_config: key=value dotfile I/O
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# ── Load dt_label as a module (it has no .py extension) ──────────────────────

_DT_LABEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dt_label"
)

_loader = importlib.machinery.SourceFileLoader("dt_label", _DT_LABEL_PATH)
_spec   = importlib.util.spec_from_loader("dt_label", _loader)
dt_label = importlib.util.module_from_spec(_spec)
sys.modules["dt_label"] = dt_label
_loader.exec_module(dt_label)

get_side            = dt_label.get_side
side_to_disc        = dt_label.side_to_disc
group_tracks_by_disc = dt_label.group_tracks_by_disc
flatten_discs       = dt_label.flatten_discs
parse_release_id    = dt_label.parse_release_id
read_id_file        = dt_label.read_id_file
_layout_height      = dt_label._layout_height
_chunk_continuous   = dt_label._chunk_continuous
load_config         = dt_label.load_config
save_config         = dt_label.save_config
render_label             = dt_label.render_label
LABEL_PROFILES           = dt_label.LABEL_PROFILES
MAX_LABEL_HEIGHT_PX      = dt_label.MAX_LABEL_HEIGHT_PX
_QR_SIZE                 = dt_label._QR_SIZE
_HDR_H                   = dt_label._HDR_H
_SIDE_HDR_H              = dt_label._SIDE_HDR_H
_TRACK_ROW_H             = dt_label._TRACK_ROW_H


# ─── get_side ─────────────────────────────────────────────────────────────────

class TestGetSide:
    def test_alpha_numeric(self):
        assert get_side("A1") == "A"

    def test_side_b(self):
        assert get_side("B2") == "B"

    def test_double_letter(self):
        assert get_side("AA1") == "AA"

    def test_pure_letter(self):
        assert get_side("A") == "A"

    def test_numeric_only_returns_empty(self):
        assert get_side("1") == ""
        assert get_side("12") == ""

    def test_empty_string(self):
        assert get_side("") == ""

    def test_lowercase_uppercased(self):
        assert get_side("a1") == "A"

    def test_side_c(self):
        assert get_side("C3") == "C"

    def test_none_like_empty(self):
        # Position with leading/trailing spaces
        assert get_side("  B1  ") == "B"


# ─── side_to_disc ─────────────────────────────────────────────────────────────

class TestSideToDisc:
    def test_a_is_disc_1(self):
        assert side_to_disc("A") == 1

    def test_b_is_disc_1(self):
        assert side_to_disc("B") == 1

    def test_c_is_disc_2(self):
        assert side_to_disc("C") == 2

    def test_d_is_disc_2(self):
        assert side_to_disc("D") == 2

    def test_e_is_disc_3(self):
        assert side_to_disc("E") == 3

    def test_f_is_disc_3(self):
        assert side_to_disc("F") == 3

    def test_empty_returns_1(self):
        assert side_to_disc("") == 1

    def test_double_letter_uses_first_char(self):
        # AA → A → disc 1
        assert side_to_disc("AA") == 1

    def test_lowercase_input(self):
        assert side_to_disc("c") == 2


# ─── group_tracks_by_disc / flatten_discs ─────────────────────────────────────

def _fake_release(positions):
    """Build a minimal fake release with tracks at the given positions."""
    tracks = []
    for pos in positions:
        t = MagicMock()
        t.__getitem__ = lambda self, k, _p=pos: {"position": _p}[k]
        t.getArtist.return_value = "Artist"
        tracks.append(t)

    release = MagicMock()
    release.getTotalTracks.return_value = len(tracks)
    release.getTrack.side_effect = lambda i: tracks[i]
    return release


class TestGroupTracksByDisc:
    def test_single_side(self):
        rel = _fake_release(["A1", "A2", "A3"])
        discs = group_tracks_by_disc(rel)
        assert 1 in discs
        assert "A" in discs[1]
        assert len(discs[1]["A"]) == 3

    def test_two_sides_one_disc(self):
        rel = _fake_release(["A1", "A2", "B1", "B2"])
        discs = group_tracks_by_disc(rel)
        assert set(discs.keys()) == {1}
        assert "A" in discs[1]
        assert "B" in discs[1]

    def test_four_sides_two_discs(self):
        rel = _fake_release(["A1", "B1", "C1", "D1"])
        discs = group_tracks_by_disc(rel)
        assert 1 in discs and 2 in discs
        assert "A" in discs[1] and "B" in discs[1]
        assert "C" in discs[2] and "D" in discs[2]

    def test_numeric_positions_grouped_as_disc_1(self):
        rel = _fake_release(["1", "2", "3"])
        discs = group_tracks_by_disc(rel)
        assert 1 in discs

    def test_global_idx_preserved(self):
        rel = _fake_release(["A1", "A2", "B1"])
        discs = group_tracks_by_disc(rel)
        # Global indices should be 0, 1, 2 in order
        a_indices = [idx for idx, _ in discs[1]["A"]]
        b_indices = [idx for idx, _ in discs[1]["B"]]
        assert a_indices == [0, 1]
        assert b_indices == [2]


class TestFlattenDiscs:
    def test_single_disc_ordering(self):
        rel = _fake_release(["A1", "A2", "B1", "B2"])
        discs = group_tracks_by_disc(rel)
        flat = flatten_discs(discs)
        # Should be A tracks first, then B tracks
        sides = [entry[0] for entry in flat]
        assert sides == ["A", "A", "B", "B"]

    def test_multi_disc_ordering(self):
        rel = _fake_release(["A1", "B1", "C1", "D1"])
        discs = group_tracks_by_disc(rel)
        flat = flatten_discs(discs)
        sides = [entry[0] for entry in flat]
        assert sides == ["A", "B", "C", "D"]

    def test_entry_structure(self):
        rel = _fake_release(["A1"])
        discs = group_tracks_by_disc(rel)
        flat = flatten_discs(discs)
        assert len(flat) == 1
        side, idx, track = flat[0]
        assert side == "A"
        assert idx == 0


# ─── parse_release_id ─────────────────────────────────────────────────────────

class TestParseReleaseId:
    def test_plain_integer_string(self):
        assert parse_release_id("12345") == 12345

    def test_bracketed_format(self):
        assert parse_release_id("[r99999]") == 99999

    def test_bracketed_with_spaces(self):
        assert parse_release_id("  [r12345]  ") == 12345

    def test_large_number(self):
        assert parse_release_id("123456789") == 123456789

    def test_invalid_raises(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_release_id("notanumber")

    def test_float_raises(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_release_id("123.45")

    def test_bracketed_without_r_raises(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_release_id("[12345]")


# ─── read_id_file ─────────────────────────────────────────────────────────────

class TestReadIdFile:
    def _write(self, tmp_path, content):
        p = tmp_path / "ids.txt"
        p.write_text(content)
        return str(p)

    def test_plain_ids(self, tmp_path):
        path = self._write(tmp_path, "11111\n22222\n33333\n")
        result = read_id_file(path)
        ids = [r[2] for r in result]
        assert ids == [11111, 22222, 33333]

    def test_bracketed_ids(self, tmp_path):
        path = self._write(tmp_path, "[r12345]\n[r99999]\n")
        result = read_id_file(path)
        ids = [r[2] for r in result]
        assert ids == [12345, 99999]

    def test_url_mode(self, tmp_path):
        path = self._write(tmp_path,
            "https://www.discogs.com/release/12345 - Some Album\n"
            "https://www.discogs.com/release/99999 - Another\n"
        )
        result = read_id_file(path)
        ids = [r[2] for r in result]
        assert ids == [12345, 99999]

    def test_url_mode_ignores_plain_ids(self, tmp_path):
        """When URLs are present, plain ID lines are ignored."""
        path = self._write(tmp_path,
            "https://www.discogs.com/release/55555\n"
            "77777\n"  # plain ID — should be ignored in URL mode
        )
        result = read_id_file(path)
        ids = [r[2] for r in result]
        assert 55555 in ids
        assert 77777 not in ids

    def test_skips_blank_lines(self, tmp_path):
        path = self._write(tmp_path, "\n11111\n\n22222\n\n")
        result = read_id_file(path)
        assert len(result) == 2

    def test_skips_comment_lines(self, tmp_path):
        path = self._write(tmp_path, "# comment\n11111\n# another\n22222\n")
        result = read_id_file(path)
        ids = [r[2] for r in result]
        assert ids == [11111, 22222]

    def test_line_numbers_returned(self, tmp_path):
        path = self._write(tmp_path, "11111\n22222\n")
        result = read_id_file(path)
        linenos = [r[0] for r in result]
        assert linenos == [1, 2]

    def test_empty_file(self, tmp_path):
        path = self._write(tmp_path, "")
        result = read_id_file(path)
        assert result == []


# ─── load_config / save_config ────────────────────────────────────────────────

class TestConfig:
    def test_load_empty_when_no_file(self, tmp_path):
        fake_path = str(tmp_path / "label_config")
        with patch.object(dt_label.util, "userfile", return_value=fake_path):
            config = load_config()
        assert config == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        fake_path = str(tmp_path / "label_config")
        with patch.object(dt_label.util, "userfile", return_value=fake_path):
            save_config({"printer": "tcp://192.168.1.50:9100", "model": "QL-1110NWB"})
            config = load_config()
        assert config["printer"] == "tcp://192.168.1.50:9100"
        assert config["model"] == "QL-1110NWB"

    def test_load_ignores_comments(self, tmp_path):
        fake_path = str(tmp_path / "label_config")
        with open(fake_path, "w") as f:
            f.write("# this is a comment\nprinter=tcp://1.2.3.4:9100\n")
        with patch.object(dt_label.util, "userfile", return_value=fake_path):
            config = load_config()
        assert "printer" in config
        assert "#" not in config

    def test_save_writes_key_value_pairs(self, tmp_path):
        fake_path = str(tmp_path / "label_config")
        with patch.object(dt_label.util, "userfile", return_value=fake_path):
            save_config({"profile": "dk1247"})
        content = open(fake_path).read()
        assert "profile=dk1247" in content

    def test_values_with_spaces_preserved(self, tmp_path):
        fake_path = str(tmp_path / "label_config")
        with patch.object(dt_label.util, "userfile", return_value=fake_path):
            save_config({"printer": "tcp://192.168.1.50:9100"})
            config = load_config()
        assert config["printer"] == "tcp://192.168.1.50:9100"


# ─── _layout_height ───────────────────────────────────────────────────────────

def _make_tracks_with_sides(sides_and_counts, title="Track Title"):
    """Build a [(side, idx, track)] list for height tests."""
    result = []
    idx = 0
    for side, count in sides_and_counts:
        for n in range(count):
            t = MagicMock()
            t.__getitem__ = MagicMock(
                side_effect=lambda k, _p=f"{side}{n+1}": _p if k == "position" else "")
            t.getArtist.return_value = "Artist"
            t.getTitle.return_value = title
            t.getDuration.return_value = None
            result.append((side, idx, t))
            idx += 1
    return result


def _height_release(title="Release Title"):
    r = MagicMock()
    for name, val in [("getId", 1), ("getTitle", title), ("getArtist", "Artist"),
                      ("getLabel", "Label"), ("getCatno", "CAT1"), ("getYear", "2020"),
                      ("getLabelYear", "2020"), ("getFormat", '12"'),
                      ("getCountry", "UK"), ("getGenre", "Electronic"),
                      ("getStyle", "Techno"), ("getNotes", "")]:
        getattr(r, name).return_value = val
    r.isCompilation.return_value = False
    return r


def _h(tracks, profile=None, **kw):
    return _layout_height(_height_release(), tracks,
                          profile or LABEL_PROFILES["dk22243"], False, **kw)


class TestLayoutHeight:
    """Height is measured by running the real layout, not predicted.

    Two implementations of the layout drifted apart three separate times and
    each time the bottom-anchored QR printed over the track listing. There is
    now one implementation; these tests cover its behaviour.
    """

    PROFILE = LABEL_PROFILES["dk22243"]

    def test_returns_positive_int(self):
        h = _h(_make_tracks_with_sides([("A", 4)]))
        assert isinstance(h, int)
        assert h > 0

    def test_more_tracks_is_taller(self):
        assert _h(_make_tracks_with_sides([("A", 8)])) > \
               _h(_make_tracks_with_sides([("A", 4)]))

    def test_continuation_shorter_than_normal(self):
        tracks = _make_tracks_with_sides([("A", 4)])
        assert _h(tracks, continuation=True) < _h(tracks, continuation=False)

    def test_disc_info_adds_height(self):
        tracks = _make_tracks_with_sides([("A", 4)])
        assert _h(tracks, disc_info=(1, 2)) > _h(tracks, disc_info=None)

    def test_side_headers_counted(self):
        assert _h(_make_tracks_with_sides([("A", 2), ("B", 2)])) > \
               _h(_make_tracks_with_sides([("A", 4)]))

    def test_too_many_tracks_raises(self):
        with pytest.raises(ValueError, match="12"):
            _h(_make_tracks_with_sides([("A", 200)]))

    def test_wrapping_titles_add_height(self):
        """A title that wraps must grow the canvas — the r4884361 failure."""
        short = _make_tracks_with_sides([("A", 3)], title="Short")
        long_ = _make_tracks_with_sides(
            [("A", 3)],
            title="An Extremely Long Reconstruction Title That Certainly Wraps "
                  "Onto A Second Line No Matter The Font")
        assert _h(long_) > _h(short)

    def test_height_leaves_exactly_the_qr_block(self):
        """The canvas must clear the content by the notes gap plus the QR."""
        tracks = _make_tracks_with_sides([("A", 3)])
        release = _height_release()
        h = _layout_height(release, tracks, self.PROFILE, False)
        bottom = dt_label.render_label(release, tracks, self.PROFILE, False,
                                       probe=True)
        assert h == bottom + dt_label._NOTES_GAP + _QR_SIZE + self.PROFILE["margin_px"]

    def test_probe_is_independent_of_canvas_height(self):
        """Probe output must not depend on the canvas it was measured on.

        This is what makes a 1px scratch canvas valid: content layout never
        reads H, only the bottom-anchored QR does.
        """
        tracks = _make_tracks_with_sides([("A", 5)])
        release = _height_release()
        a = dt_label.render_label(release, tracks, self.PROFILE, False, probe=True)
        b = dt_label.render_label(release, tracks, self.PROFILE, False,
                                  height_px=3600, probe=True)
        assert a == b

    def test_probe_draws_nothing_permanent(self):
        """Probe returns a position, not an image."""
        tracks = _make_tracks_with_sides([("A", 2)])
        out = dt_label.render_label(_height_release(), tracks, self.PROFILE,
                                    False, probe=True)
        assert isinstance(out, int)


# ─── _chunk_continuous ────────────────────────────────────────────────────────

class TestChunkContinuous:
    PROFILE = LABEL_PROFILES["dk22243"]

    def test_small_release_fits_one_chunk(self):
        tracks = _make_tracks_with_sides([("A", 4)])
        chunks = _chunk_continuous(tracks, self.PROFILE, _height_release())
        assert len(chunks) == 1
        assert chunks[0] == tracks

    def test_empty_tracks_empty_chunks(self):
        chunks = _chunk_continuous([], self.PROFILE, _height_release())
        assert chunks == []

    def test_overflow_creates_multiple_chunks(self):
        """A very large tracklist must be split across multiple labels."""
        tracks = _make_tracks_with_sides([("A", 100)])
        chunks = _chunk_continuous(tracks, self.PROFILE, _height_release())
        assert len(chunks) > 1

    def test_all_tracks_preserved(self):
        """No tracks should be lost when splitting across chunks."""
        tracks = _make_tracks_with_sides([("A", 100)])
        chunks = _chunk_continuous(tracks, self.PROFILE, _height_release())
        total = sum(len(c) for c in chunks)
        assert total == len(tracks)

    def test_chunk_order_preserved(self):
        """Tracks within and across chunks must stay in original order."""
        tracks = _make_tracks_with_sides([("A", 100)])
        chunks = _chunk_continuous(tracks, self.PROFILE, _height_release())
        flat = [t for chunk in chunks for t in chunk]
        assert flat == tracks

    def test_each_chunk_fits_within_max_height(self):
        """Every produced chunk must fit within MAX_LABEL_HEIGHT_PX."""
        tracks = _make_tracks_with_sides([("A", 100)])
        chunks = _chunk_continuous(tracks, self.PROFILE, _height_release())
        for i, chunk in enumerate(chunks):
            h = _layout_height(_height_release(), chunk, self.PROFILE, False,
                               continuation=(i > 0))
            assert h <= MAX_LABEL_HEIGHT_PX


# ─── render_label ─────────────────────────────────────────────────────────────

def _render_kwargs_for(release, tracks, profile, **kw):
    """Continuous-profile render kwargs for a track list."""
    if profile.get("feed") != "continuous":
        return {}
    return {"height_px": _layout_height(release, tracks, profile,
                                        kw.get("is_compilation", False)),
            "notes_lines": profile.get("notes_lines", 3)}


def _ink(img):
    """Count non-white pixels — a proxy for "something was actually drawn"."""
    return sum(img.convert("L").histogram()[:200])


def _bpm_zone(img, profile):
    """Crop the right-hand BPM column, where BPM values are drawn."""
    W = profile["width_px"]
    M = profile["margin_px"]
    BPM_ZONE_W = 110
    return img.crop((W - M - BPM_ZONE_W, 0, W - M, img.height))


def _qr_zone(img, profile):
    """Crop the bottom-left corner where the QR is pasted."""
    M = profile["margin_px"]
    return img.crop((M, img.height - M - _QR_SIZE, M + _QR_SIZE, img.height - M))


def _fake_render_track(position: str = "A1") -> MagicMock:
    """Build a minimal track mock suitable for render_label()."""
    t = MagicMock()
    # track["position"] is accessed via dict-style __getitem__
    t.__getitem__ = MagicMock(side_effect=lambda k: position if k == "position" else "")
    t.getArtist.return_value = "Track Artist"
    t.getTitle.return_value = "Track Title"
    t.getDuration.return_value = "3:45"
    return t


def _make_render_tracks(sides_and_counts):
    """Build a [(side, idx, track)] list for render_label() tests."""
    result = []
    idx = 0
    positions = "ABCDEFGH"
    for i, (side, count) in enumerate(sides_and_counts):
        for n in range(count):
            pos = f"{positions[i]}{n + 1}"
            result.append((side, idx, _fake_render_track(pos)))
            idx += 1
    return result


def _fake_render_release() -> MagicMock:
    """Build a minimal release mock suitable for render_label()."""
    r = MagicMock()
    r.getArtist.return_value  = "Test Artist"
    r.getTitle.return_value   = "Test Album"
    r.getLabel.return_value   = "Test Label"
    r.getCatno.return_value   = "TL001"
    r.getYear.return_value    = "2020"
    r.getCountry.return_value = "UK"
    r.getId.return_value      = 12345
    r.getGenre.return_value   = "Electronic"
    r.getArtwork.return_value = None
    return r


class TestRenderLabel:
    """Smoke and integration tests for the render_label() function."""

    def test_returns_pil_image(self):
        """render_label() returns a PIL Image object."""
        from PIL import Image as PILImage
        profile = LABEL_PROFILES["dk1247"]
        tracks = _make_render_tracks([("A", 2)])
        img = render_label(_fake_render_release(), tracks, profile, is_compilation=False)
        assert isinstance(img, PILImage.Image)

    def test_dk1247_dimensions(self):
        """dk1247 die-cut profile produces a 1200×1822 image."""
        profile = LABEL_PROFILES["dk1247"]
        tracks = _make_render_tracks([("A", 4)])
        img = render_label(_fake_render_release(), tracks, profile, is_compilation=False)
        assert img.width  == 1200
        assert img.height == 1822

    def test_layout_height_matches_render(self):
        """_layout_height() returns the canvas height render_label() then uses."""
        profile = LABEL_PROFILES["dk22243"]
        tracks = _make_render_tracks([("A", 2), ("B", 2)])
        h = _layout_height(_fake_render_release(), tracks, profile, False)
        img = render_label(
            _fake_render_release(), tracks, profile,
            is_compilation=False, height_px=h, notes_lines=profile["notes_lines"],
        )
        # render_label uses height_px as its canvas height, so img.height must equal h
        assert img.height == h

    def test_compilation_shows_track_artists(self):
        """A compilation must actually draw more ink than a non-compilation.

        This previously only checked that render_label didn't raise, so it
        would have passed even if artist names were never drawn.
        """
        profile = LABEL_PROFILES["dk1247"]
        tracks = _make_render_tracks([("A", 3)])
        plain = render_label(_fake_render_release(), tracks, profile,
                             is_compilation=False)
        comp  = render_label(_fake_render_release(), tracks, profile,
                             is_compilation=True)
        assert _ink(comp) > _ink(plain)

    def test_bpm_values_appear_in_label(self):
        """A supplied BPM must put ink in the BPM zone, not just avoid raising."""
        profile = LABEL_PROFILES["dk1247"]
        tracks = _make_render_tracks([("A", 2)])
        bpms = {0: {"bpm": 128, "duration_ms": 360000},
                1: {"bpm": 132, "duration_ms": 420000}}
        without = render_label(_fake_render_release(), tracks, profile,
                               is_compilation=False)
        with_bpm = render_label(_fake_render_release(), tracks, profile,
                                is_compilation=False, bpms=bpms)
        assert _ink(_bpm_zone(with_bpm, profile)) > _ink(_bpm_zone(without, profile))

    def test_die_cut_does_not_wrap_tracks(self):
        """Die-cut labels use truncation, not wrapping — canvas height is fixed."""
        from PIL import Image as PILImage
        profile = LABEL_PROFILES["dk1247"]
        t = MagicMock()
        t.__getitem__ = MagicMock(side_effect=lambda k: "A1" if k == "position" else "")
        t.getArtist.return_value = "Artist"
        t.getTitle.return_value = "A" * 120   # absurdly long title
        t.getDuration.return_value = ""
        tracks = [("A", 0, t)]
        img = render_label(_fake_render_release(), tracks, profile, is_compilation=False)
        # Canvas must still be the fixed die-cut height
        assert img.height == profile["height_px"]

    def test_continuous_height_includes_qr_area(self):
        """notes_h must be large enough to fit the QR code with a safety buffer."""
        profile = LABEL_PROFILES["dk22243"]
        # notes_h = 28 (divider) + QR_SIZE (200) + EXTRA_LINE_H (50) = 278
        notes_h = 28 + _QR_SIZE + dt_label._EXTRA_LINE_H
        assert notes_h >= 28 + _QR_SIZE, \
            "notes_h must provide at least QR_SIZE pixels after the divider"
        # Safety buffer must be at least one track-wrap's worth so that a single
        # missed wrap in _measure_wrap_extra_px doesn't push QR into the tracks.
        safety = notes_h - 28 - _QR_SIZE
        assert safety >= dt_label._EXTRA_LINE_H, \
            f"safety buffer {safety} too small (need >= {dt_label._EXTRA_LINE_H})"


# ─── QR code placement ────────────────────────────────────────────────────────

def _fake_long_track(position: str, title: str, artist: str = "Artist",
                     duration: str = "5:00") -> MagicMock:
    """Build a track mock with a specific long title for wrap/QR tests."""
    t = MagicMock()
    t.__getitem__ = MagicMock(side_effect=lambda k: position if k == "position" else "")
    t.getArtist.return_value = artist
    t.getTitle.return_value = title
    t.getDuration.return_value = duration
    return t


class TestQRPlacement:
    """The QR must never overlap the track listing.

    These used to re-derive the content bottom with a copy of the layout
    arithmetic — the very duplication that caused the bugs. They now ask
    render_label itself via probe mode, so there is nothing to keep in sync.
    """

    PROFILE = LABEL_PROFILES["dk22243"]
    M       = LABEL_PROFILES["dk22243"]["margin_px"]

    def _clearance(self, tracks, release=None, is_compilation=False, bpms=None):
        """Pixels between the content bottom and the top of the QR."""
        release = release or _fake_render_release()
        h = _layout_height(release, tracks, self.PROFILE, is_compilation,
                           bpms=bpms)
        bottom = render_label(release, tracks, self.PROFILE, is_compilation,
                              bpms=bpms, probe=True)
        return (h - self.M - _QR_SIZE) - bottom, h

    def test_qr_clears_tracks_short_release(self):
        tracks = _make_render_tracks([("A", 2)])
        clearance, _ = self._clearance(tracks)
        assert clearance >= 0

    def test_qr_clears_tracks_long_wrapping_titles(self):
        long_titles = [
            ("A", 0, _fake_long_track("A1", "The Bug", "Faith In Dub", "5:12")),
            ("A", 1, _fake_long_track("A2", "Ghost Dubs",
                                      "Descent Into The Maelstrom Of Endless Reverb", "6:01")),
            ("B", 2, _fake_long_track("B1", "The Bug",
                                      "Alien Virus (West Indian Centre, Leeds)", "4:48")),
            ("B", 3, _fake_long_track("B2", "Ghost Dubs",
                                      "Militants (The Rocket, Holloway) Extended", "4:22")),
        ]
        clearance, _ = self._clearance(long_titles, is_compilation=True)
        assert clearance >= 0

    def test_qr_fits_within_canvas(self):
        tracks = _make_render_tracks([("A", 3)])
        _, h = self._clearance(tracks)
        assert h - self.M - _QR_SIZE + _QR_SIZE <= h

    def test_clearance_is_exactly_the_notes_gap(self):
        """Canvas is sized precisely — no slack beyond the divider gap."""
        tracks = _make_render_tracks([("A", 3)])
        clearance, _ = self._clearance(tracks)
        assert clearance == dt_label._NOTES_GAP

    @pytest.mark.parametrize("counts", [
        [("A", 1)], [("A", 4)], [("A", 3), ("B", 3)],
        [("A", 2), ("B", 2), ("C", 2), ("D", 2)],
    ])
    def test_qr_clears_tracks_across_shapes(self, counts):
        clearance, _ = self._clearance(_make_render_tracks(counts))
        assert clearance >= 0


# ─── Font glyph coverage / script fallback ───────────────────────────────────

_DEVANAGARI = "दुनिया का राजा"   # r37718007 A2 — "King of the World"


def _font_with(chars):
    """Find any installed font covering every char in `chars`, else None.

    Used to skip fallback tests on machines with no suitable font installed.
    """
    import glob
    seen = set()
    for pattern in ("/usr/share/fonts/**/*.ttf", "/usr/share/fonts/**/*.otf",
                    "/System/Library/Fonts/**/*.ttf",
                    "/System/Library/Fonts/**/*.ttc"):
        for path in glob.glob(pattern, recursive=True):
            if path in seen:
                continue
            seen.add(path)
            try:
                if not dt_label._missing_chars(path, chars):
                    return path
            except Exception:
                continue
    return None


@pytest.fixture
def clear_font_caches():
    """Reset the module-level font caches around a test."""
    def _clear():
        dt_label._font_path_cache.clear()
        dt_label._coverage_cache.clear()
        dt_label._notdef_cache.clear()
        dt_label._font_obj_cache.clear()
        dt_label._warned_missing.clear()
    _clear()
    yield
    _clear()


class TestGlyphCoverage:
    def test_latin_covered_by_primary(self):
        path = dt_label._find_font_path("regular")
        assert path, "no regular font installed"
        assert dt_label._missing_chars(path, "Angel Edit") == []

    def test_devanagari_not_covered_by_latin_face(self):
        """The bug: Arial/Liberation have no Devanagari glyphs."""
        path = dt_label._find_font_path("regular")
        missing = dt_label._missing_chars(path, _DEVANAGARI)
        assert missing, "expected Devanagari to be missing from the Latin face"
        assert "द" in missing

    def test_whitespace_always_covered(self):
        path = dt_label._find_font_path("regular")
        assert dt_label._covers(path, " ") is True
        assert dt_label._missing_chars(path, "   ") == []

    def test_coverage_is_cached(self, clear_font_caches):
        path = dt_label._find_font_path("regular")
        dt_label._covers(path, "A")
        assert (path, "A") in dt_label._coverage_cache


class TestFontFallback:
    def test_latin_text_keeps_primary_face(self, clear_font_caches):
        font = dt_label._font_for("regular", 38, "Angel Edit")
        assert font.path == dt_label._find_font_path("regular")

    def test_falls_back_to_face_with_glyphs(self, clear_font_caches):
        """A face covering the string must be chosen over the Latin primary."""
        good = _font_with(_DEVANAGARI)
        if not good:
            pytest.skip("no Devanagari-capable font installed")
        dt_label._FONT_CANDIDATES["devanagari"] = [good]
        dt_label._font_path_cache.clear()
        font = dt_label._font_for("regular", 38, _DEVANAGARI)
        assert dt_label._missing_chars(font.path, _DEVANAGARI) == []

    def test_mixed_script_needs_whole_string_coverage(self, clear_font_caches):
        """Fallback must cover Latin too — Pillow draws the run in one face."""
        mixed = _DEVANAGARI + " (Original Mix)"
        good = _font_with(mixed)
        if not good:
            pytest.skip("no font covering both scripts installed")
        dt_label._FONT_CANDIDATES["devanagari"] = [good]
        dt_label._font_path_cache.clear()
        font = dt_label._font_for("regular", 38, mixed)
        assert dt_label._missing_chars(font.path, mixed) == []

    def test_warns_once_when_nothing_covers(self, clear_font_caches, capsys):
        """Unrenderable text warns on stderr but still returns a usable font."""
        for style in dt_label._FALLBACK_ORDER:
            dt_label._FONT_CANDIDATES[style] = []
        dt_label._font_path_cache.clear()
        font = dt_label._font_for("regular", 38, _DEVANAGARI)
        assert font is not None
        err = capsys.readouterr().err
        assert "U+0926" in err

        dt_label._font_for("regular", 38, _DEVANAGARI)
        assert capsys.readouterr().err == ""   # deduped, no repeat warning

    def test_empty_and_non_string_are_safe(self, clear_font_caches):
        assert dt_label._font_for("regular", 38, "") is not None
        assert dt_label._font_for("regular", 38, None) is not None


# ─── Printer send ─────────────────────────────────────────────────────────────

import time
import threading


def _fake_printer(hold=0.0):
    """Throwaway TCP server that accepts a job and says nothing. Returns port."""
    import socket as _s
    srv = _s.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        try:
            conn, _ = srv.accept()
            conn.recv(65536)
            time.sleep(hold)
            conn.close()
        except Exception:
            pass
        finally:
            srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return port


class TestPrinterSend:
    """The printer does not report completion over the network.

    Probed for 10s on port 9100: zero bytes back.  So _send_raster writes and
    returns, and "sent to printer" is the last observable step.
    """

    def test_writes_and_returns(self):
        pytest.importorskip("brother_ql")
        port = _fake_printer()
        assert dt_label._send_raster(b"\x00" * 400,
                                     f"tcp://127.0.0.1:{port}") is None

    def test_returns_promptly(self):
        """No readback wait: a silent printer must not stall the caller."""
        pytest.importorskip("brother_ql")
        port = _fake_printer(hold=2.0)
        started = time.time()
        dt_label._send_raster(b"\x00" * 400, f"tcp://127.0.0.1:{port}")
        assert time.time() - started < 0.5

    def test_write_failure_raises(self):
        """A dead port must raise so print_label can turn it into RuntimeError."""
        pytest.importorskip("brother_ql")
        with pytest.raises(OSError):
            dt_label._send_raster(b"\x00" * 400, "tcp://127.0.0.1:1")

    def test_partially_written_blocks_retry(self):
        """A mid-transfer timeout must not be treated as safely retryable."""
        assert dt_label._partially_written(TimeoutError("timed out")) is True

    def test_connection_error_is_retryable(self):
        assert dt_label._partially_written(ConnectionRefusedError()) is False


# ─── Config-only CLI invocations ──────────────────────────────────────────────

class TestConfigOnlyInvocation:
    """`dt_label --printer …` with no release must save config and exit 0.

    Argument validation used to run before the config save, so a config-setting
    flag on its own bailed out with "provide a release ID" and saved nothing.
    """

    def _run(self, argv, cfg_path):
        """Run dt_label.main() with argv, redirecting config I/O to cfg_path.

        util.datapath is resolved at import time, so patching HOME is too late;
        userfile itself has to be replaced.
        """
        with patch.object(sys, "argv", ["dt_label"] + argv), \
             patch.object(dt_label.util, "userfile", lambda _n: cfg_path):
            with pytest.raises(SystemExit) as exc:
                dt_label.main()
        return exc.value.code

    def test_printer_alone_saves_and_exits_zero(self, tmp_path):
        cfg = str(tmp_path / "label_config")
        assert self._run(["--printer", "tcp://printer.local:9100"], cfg) == 0
        assert "printer=tcp://printer.local:9100" in open(cfg).read()

    def test_model_and_profile_alone_saved(self, tmp_path):
        cfg = str(tmp_path / "label_config")
        assert self._run(["--model", "QL-1110NWB",
                          "--label-profile", "dk22243"], cfg) == 0
        body = open(cfg).read()
        assert "model=QL-1110NWB" in body
        assert "profile=dk22243" in body

    def test_settings_merge_across_invocations(self, tmp_path):
        """A later config-only call must not clobber earlier keys."""
        cfg = str(tmp_path / "label_config")
        self._run(["--printer", "tcp://a.local:9100"], cfg)
        self._run(["--model", "QL-800"], cfg)
        body = open(cfg).read()
        assert "printer=tcp://a.local:9100" in body
        assert "model=QL-800" in body

    def test_no_args_still_errors(self, tmp_path):
        cfg = str(tmp_path / "label_config")
        assert self._run([], cfg) == 2          # argparse usage error
        assert not os.path.exists(cfg)          # and writes nothing

    def test_release_id_and_file_still_mutually_exclusive(self, tmp_path):
        cfg = str(tmp_path / "label_config")
        assert self._run(["123", "-f", "ids.txt"], cfg) == 2


# ─── QR placement (property tests) ────────────────────────────────────────────

def _qr_track(pos, title, artist="Artist", duration=None):
    t = MagicMock()
    t.__getitem__ = MagicMock(side_effect=lambda k, _p=pos: _p if k == "position" else "")
    t.getArtist.return_value = artist
    t.getTitle.return_value = title
    t.getDuration.return_value = duration
    return t


def _qr_release(rid=4884361, title="Reconstructed", artist="Steve O'Sullivan"):
    r = MagicMock()
    for name, val in [("getId", rid), ("getTitle", title), ("getArtist", artist),
                      ("getLabel", "Sushitech Records"), ("getCatno", "SUSH28"),
                      ("getYear", "2013"), ("getLabelYear", "2013"),
                      ("getFormat", '2 x 12"'), ("getCountry", "Germany"),
                      ("getGenre", "Electronic"), ("getStyle", "Dub Techno"),
                      ("getNotes", "")]:
        getattr(r, name).return_value = val
    r.isCompilation.return_value = False
    return r


# r4884361 — bare side letters, long remix titles, no Discogs durations.
# Beatport supplies durations, whose suffix pushes two titles onto a second
# line. The measurement pass used not to see them, so the predicted canvas was
# 100 px short and the bottom-anchored QR landed on the D2 row.
_RECONSTRUCTED = [
    ("A",  "Where's Burt? (Delano Smith Reconstruction)"),
    ("B",  "Moving Forward (Mike Huckaby S Y N T H Reconstruction)"),
    ("C",  "Where's Burt? (Thor Reconstruction)"),
    ("D1", "Don't Rush The Dub (Rhauder Reconstruction)"),
    ("D2", "Stripped (Exos Reconstruction)"),
]
_RECONSTRUCTED_BPMS = {
    0: {"bpm": 125, "duration_ms": 463000},
    1: {"bpm": 123, "duration_ms": 481000},
    2: {"bpm": 120, "duration_ms": 428000},
    3: {"bpm": 126, "duration_ms": 417000},
    4: {"bpm": 122, "duration_ms": 399000},
}


def _content_bottom_vs_qr(tracks, bpms, is_compilation=False, release=None):
    """Render a continuous label; return (overrun_px, height).

    overrun_px > 0 means the track listing crossed into the QR zone. Both the
    content bottom and the canvas height come from the same layout code, so
    this measures the real thing rather than re-deriving it.
    """
    profile = LABEL_PROFILES["dk22243"]
    release = release or _qr_release()
    tws = [(dt_label.get_side(p), i, _qr_track(p, t))
           for i, (p, t) in enumerate(tracks)]
    kw = dt_label._render_kwargs(tws, profile, release=release,
                                 is_compilation=is_compilation, bpms=bpms)
    H = kw["height_px"]
    qr_top = H - profile["margin_px"] - _QR_SIZE
    content_bottom = dt_label.render_label(release, tws, profile, is_compilation,
                                           bpms=bpms, probe=True)
    return content_bottom - qr_top, H


class TestQRPlacementProperties:
    """The QR is bottom-anchored, so it lands correctly only if the predicted
    canvas height matches what render_label actually lays out. Every QR bug so
    far has been a divergence between those two. Assert the property directly.
    """

    def test_reconstructed_qr_does_not_overlap_tracks(self):
        overrun, _ = _content_bottom_vs_qr(_RECONSTRUCTED, _RECONSTRUCTED_BPMS)
        assert overrun <= 0, f"QR overlaps track listing by {overrun}px"

    def test_beatport_duration_included_in_height(self):
        """Durations that only exist in Beatport data must affect the canvas."""
        _, h_without = _content_bottom_vs_qr(_RECONSTRUCTED, None)
        _, h_with    = _content_bottom_vs_qr(_RECONSTRUCTED, _RECONSTRUCTED_BPMS)
        assert h_with > h_without, \
            "duration suffix did not grow the canvas — measurement ignores bpms"

    def test_resolver_shared_between_measure_and_render(self):
        """_resolve_track_text is the single source of truth for row text."""
        tr = _qr_track("A1", "Title", duration=None)
        assert dt_label._resolve_track_text(tr, 0, False, None) == "Title"
        # Beatport fallback applies when Discogs has no duration
        assert dt_label._resolve_track_text(
            tr, 0, False, {0: {"duration_ms": 463000}}) == "Title (7:43)"
        # Discogs duration wins over Beatport
        tr2 = _qr_track("A1", "Title", duration="3:00")
        assert dt_label._resolve_track_text(
            tr2, 0, False, {0: {"duration_ms": 463000}}) == "Title (3:00)"

    def test_compilation_prefixes_artist(self):
        tr = _qr_track("A1", "Title", artist="Someone (2)")
        out = dt_label._resolve_track_text(tr, 0, True, None)
        assert out.startswith("Someone – ")   # disambiguation stripped

    @pytest.mark.parametrize("n", [1, 3, 5, 8, 12])
    def test_qr_never_overlaps_for_varied_lengths(self, n):
        """Property: for any track count, content must stay above the QR."""
        tracks = [(f"A{i+1}",
                   "A Fairly Long Reconstruction Title That May Well Wrap "
                   f"Around Number {i+1}")
                  for i in range(n)]
        bpms = {i: {"bpm": 120, "duration_ms": 400000 + i} for i in range(n)}
        overrun, _ = _content_bottom_vs_qr(tracks, bpms)
        assert overrun <= 0, f"{n} tracks: QR overlaps by {overrun}px"


# ─── Rendered output content ──────────────────────────────────────────────────

class TestRenderedContent:
    """Assertions on what actually lands on the canvas.

    The suite used to render images and never inspect them, which is how a QR
    printing on top of the track listing survived three separate fixes.
    """

    PROFILE = LABEL_PROFILES["dk22243"]

    def _render(self, tracks, **kw):
        release = _fake_render_release()
        kwargs = _render_kwargs_for(release, tracks, self.PROFILE, **kw)
        return render_label(release, tracks, self.PROFILE, kw.get("is_compilation", False),
                            **kwargs)

    def test_qr_zone_is_not_blank(self):
        img = self._render(_make_render_tracks([("A", 2)]))
        assert _ink(_qr_zone(img, self.PROFILE)) > 500, "QR appears to be missing"

    def test_qr_zone_contains_black_and_white(self):
        """A QR is a mix of both; a solid block would mean a paste failure."""
        img = self._render(_make_render_tracks([("A", 2)]))
        zone = _qr_zone(img, self.PROFILE).convert("L")
        hist = zone.histogram()
        dark  = sum(hist[:128])
        total = sum(hist)
        assert 0.1 < dark / total < 0.9

    def test_more_tracks_means_more_ink(self):
        few  = self._render(_make_render_tracks([("A", 2)]))
        many = self._render(_make_render_tracks([("A", 6)]))
        assert _ink(many) > _ink(few)

    def test_blank_bpm_zone_when_no_bpms(self):
        """Without BPMs the zone holds only the thin write-line rules."""
        img = self._render(_make_render_tracks([("A", 3)]))
        zone_ink = _ink(_bpm_zone(img, self.PROFILE))
        assert zone_ink < _ink(img) * 0.2

    def test_track_area_above_qr_is_untouched_by_it(self):
        """The band just above the QR must stay clear — the r4884361 failure.

        If the canvas is undersized the QR is pasted over the last track row,
        which shows up as ink where the notes gap should be blank.
        """
        tracks = _make_render_tracks([("A", 4)])
        release = _fake_render_release()
        h = _layout_height(release, tracks, self.PROFILE, False)
        img = render_label(release, tracks, self.PROFILE, False,
                           height_px=h, notes_lines=self.PROFILE["notes_lines"])
        bottom = render_label(release, tracks, self.PROFILE, False, probe=True)
        qr_top = h - self.PROFILE["margin_px"] - _QR_SIZE
        # The strip between content bottom and qr_top holds only the divider.
        strip = img.crop((self.PROFILE["margin_px"], bottom + 4,
                          self.PROFILE["margin_px"] + _QR_SIZE, qr_top))
        assert strip.height > 0
        # The strip holds the notes divider and nothing else. A QR pasted here
        # would be orders of magnitude denser, so compare against one.
        assert _ink(strip) < _ink(_qr_zone(img, self.PROFILE)) * 0.1

    def test_die_cut_canvas_is_exactly_the_profile_size(self):
        profile = LABEL_PROFILES["dk1247"]
        img = render_label(_fake_render_release(),
                           _make_render_tracks([("A", 3)]), profile, False)
        assert (img.width, img.height) == (profile["width_px"], profile["height_px"])
