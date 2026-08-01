from __future__ import annotations

import os
import json
import csv

DATA_DIRNAME = ".discogstool"


def datadir(create: bool = True) -> str:
    """Return ~/.discogstool, creating it on first use.

    Resolved per call rather than at import.  The path used to be a module
    constant computed at import time, which meant importing util created a
    directory as a side effect, and tests could not redirect it by setting
    HOME — the value was already baked in before the test ran.
    """
    path = os.path.expanduser(os.path.join("~", DATA_DIRNAME))
    if create and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


def __getattr__(name: str):
    """Lazily provide the historical `util.datapath` attribute.

    PEP 562 module __getattr__ — keeps `util.datapath` working for any caller
    while removing the import-time filesystem side effect.
    """
    if name == "datapath":
        return datadir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def userfile(fname: str) -> str:
    return os.path.join(datadir(), fname)


# ── key=value config files ────────────────────────────────────────────────────
# dt_label, dt_find and dt_server each had their own byte-identical copy of
# this parser.  The quirks below are load-bearing for existing config files and
# are pinned by tests/test_config_parsing.py.

def load_kv_config(path: str) -> dict[str, str]:
    """Read a `key=value` config file into a dict.

    Behaviour, unchanged from the three implementations this replaces:
      * missing file yields {}
      * blank lines, and lines whose first non-space character is '#', are skipped
      * lines without '=' are skipped
      * split on the *first* '=' only, so values may contain '='
      * key and value are stripped of surrounding whitespace
      * a '#' anywhere after the '=' is part of the value, not a comment
      * duplicate keys: the last occurrence wins
    """
    config: dict[str, str] = {}
    if not os.path.exists(path):
        return config
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config


def save_kv_config(path: str, config: dict, header: str | None = None) -> None:
    """Write a `key=value` config file, optionally with a leading comment."""
    with open(path, "w") as f:
        if header:
            f.write(f"# {header}\n")
        for k, v in config.items():
            f.write(f"{k}={v}\n")


def resolve_anthropic_key() -> str | None:
    """Return the Anthropic API key, or None if not configured.

    Checked in order: `anthropic_api_key` in ~/.discogstool/beatport_auth.json,
    then the ANTHROPIC_API_KEY environment variable.  This lookup previously
    existed in four places (dt_server twice, dt_find, beatport).
    """
    auth_file = userfile("beatport_auth.json")
    if os.path.exists(auth_file):
        try:
            with open(auth_file) as f:
                key = json.load(f).get("anthropic_api_key")
            if key:
                return key
        except (OSError, ValueError):
            pass   # unreadable or malformed — fall through to the env var
    return os.environ.get("ANTHROPIC_API_KEY") or None


def file_extension(path: str) -> str:
    _, ext = os.path.splitext(path)
    return ext[1:].lower()


def get_audio_files(basedir: str) -> list[str]:
    filelist: list[str] = []

    for root, dirs, files in os.walk(basedir):
        for fname in files:
            if fname.startswith("."):
                continue
            if file_extension(fname) in ["mp3", "m4a", "aac", "mp4", "aiff", "aif"]:
                filename = os.path.abspath(os.path.join(root, fname))
                try:
                    filelist.append(filename)
                except Exception as e:
                    print(("Failed to process", filename))
                    raise e

    return filelist


class CollectionInfo:
    releaseid: int
    collection: str
    date: str
    mcond: str
    scond: str
    notes: str

    def __init__(
        self,
        releaseid: int,
        collection: str,
        date: str,
        mcond: str,
        scond: str,
        notes: str,
    ) -> None:
        self.releaseid = releaseid
        self.collection = collection
        self.date = date
        self.mcond = mcond
        self.scond = scond
        self.notes = notes

# CSV format:
# catno, artist, title, label, format, rating, released, id, collection, date added
# media condition, sleeve condition, notes
def parse_collection_xml(path: str) -> list[CollectionInfo]:
    collection: list[CollectionInfo] = []

    with open(path, "r") as csvfile:
        reader = csv.reader(csvfile)
        next(reader)  # skip header row
        for line in reader:
            releaseid = int(line[7])

            # Items prior from 8 can be derived from the release object
            line = line[8:]

            coll, date, mcond, scond, notes = line
            ci = CollectionInfo(releaseid, coll, date, mcond, scond, notes)

            collection.append(ci)

    return collection

