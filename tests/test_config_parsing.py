"""Characterization tests for the ~/.discogstool key=value config format.

dt_label, dt_find and dt_server each parsed this format with their own
byte-identical copy of the same loop. These tests pin the *existing* behaviour
— quirks included — so the consolidation onto util.load_kv_config can be shown
to change nothing.

Every case here was captured from the pre-refactor implementation by running
it, not from reading it. If one of these ever needs to change, that is a
deliberate format decision, not a refactor.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util as _importlib_util
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(_ROOT, name))
    spec = _importlib_util.spec_from_loader(name, loader)
    mod = _importlib_util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


sys.path.insert(0, _ROOT)
import util  # noqa: E402


# Every parser that must agree on this format.
def _parsers():
    out = {"util": util.load_kv_config} if hasattr(util, "load_kv_config") else {}
    for name in ("dt_label", "dt_find"):
        mod = _load(name)
        out[name] = lambda p, _m=mod: _read_via(_m, p)
    return out


def _read_via(mod, path):
    """Call a module's load_config() with userfile redirected to `path`."""
    from unittest.mock import patch
    with patch.object(mod.util, "userfile", return_value=path):
        return mod.load_config()


PARSERS = _parsers()

# (name, file body, expected dict) — captured from the original implementation.
CASES = [
    ("duplicate_keys_last_wins",  "a=1\na=2\n",              {"a": "2"}),
    ("whitespace_stripped",       "  a  =  1  \n",           {"a": "1"}),
    ("line_without_equals",       "junk\na=1\n",             {"a": "1"}),
    ("indented_comment_ignored",  "   # c\na=1\n",           {"a": "1"}),
    ("trailing_hash_is_value",    "a=1 # not a comment\n",   {"a": "1 # not a comment"}),
    ("empty_value_kept",          "a=\n",                    {"a": ""}),
    ("empty_key_kept",            "=v\n",                    {"": "v"}),
    ("crlf_tolerated",            "a=1\r\nb=2\r\n",          {"a": "1", "b": "2"}),
    ("equals_in_value",           "a=x=y=z\n",               {"a": "x=y=z"}),
    ("blank_lines_skipped",       "\n\na=1\n\n",             {"a": "1"}),
    ("empty_file",                "",                        {}),
]


@pytest.mark.parametrize("parser_name", sorted(PARSERS))
@pytest.mark.parametrize("case_name,body,expected",
                         CASES, ids=[c[0] for c in CASES])
def test_config_format(parser_name, case_name, body, expected, tmp_path):
    """Every parser must produce identical output for the same file."""
    path = tmp_path / f"cfg_{case_name}"
    path.write_text(body)
    assert PARSERS[parser_name](str(path)) == expected


@pytest.mark.parametrize("parser_name", sorted(PARSERS))
def test_missing_file_is_empty(parser_name, tmp_path):
    assert PARSERS[parser_name](str(tmp_path / "does_not_exist")) == {}


def test_all_parsers_agree(tmp_path):
    """Cross-check: no parser may diverge from the others on any case."""
    for case_name, body, _expected in CASES:
        path = tmp_path / f"agree_{case_name}"
        path.write_text(body)
        results = {n: p(str(path)) for n, p in PARSERS.items()}
        distinct = {repr(v) for v in results.values()}
        assert len(distinct) == 1, f"{case_name}: parsers disagree -> {results}"
