"""Tests for the extension popup's status logic.

popup.js decides what the status line says purely from /progress payloads, so
it can be driven headlessly: tests/js/popup_harness.js stubs `document` and
`browser`, evaluates the real popup.js, and asserts the rendered status text
for a series of job states.

This exists because the status line has twice shown something stale — most
recently sitting on "Queued." while the label was already printing, because
the text was captured once from the POST response instead of derived from
live state. Assertions on real state transitions catch that class of bug.

Skipped when node isn't installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "js", "popup_harness.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_popup_status_transitions():
    result = subprocess.run(["node", _HARNESS], capture_output=True, text=True)
    assert result.returncode == 0, (
        "popup status transitions failed:\n"
        + result.stdout + result.stderr
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_popup_js_parses():
    """Guard against syntax errors reaching a signed build."""
    popup = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "firefox-ext", "popup.js")
    result = subprocess.run(["node", "--check", popup],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_background_js_parses():
    bg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "firefox-ext", "background.js")
    result = subprocess.run(["node", "--check", bg],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
