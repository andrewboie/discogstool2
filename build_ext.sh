#!/usr/bin/env bash
# build_ext.sh — Assemble the browser extensions from shared sources.
#
# Everything except manifest.json is shared:
#
#   ext/shared/   popup.html, popup.js, background.js, icons/
#   ext/firefox/  manifest.json  (MV2, background page)
#   ext/chrome/   manifest.json  (MV3, service worker)
#
# Output directories are generated and gitignored — edit ext/, never the build
# output, or your change is lost on the next run.
#
#   firefox-ext/  → loaded by sign_extension.sh / about:debugging
#   chrome-ext/   → chrome://extensions → Load unpacked
#
# Usage:
#   ./build_ext.sh            # build both
#   ./build_ext.sh firefox    # build one
#   ./build_ext.sh chrome

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED="${SCRIPT_DIR}/ext/shared"

build() {
    local browser="$1"
    local src="${SCRIPT_DIR}/ext/${browser}"
    local out="${SCRIPT_DIR}/${browser}-ext"

    if [[ ! -f "${src}/manifest.json" ]]; then
        echo "Error: no manifest for '${browser}' at ${src}/manifest.json" >&2
        return 1
    fi

    # web-ext caches its AMO upload id here; a clean rebuild would drop it and
    # force a fresh upload record, so carry it across.
    local uuid_cache=""
    if [[ -f "${out}/.amo-upload-uuid" ]]; then
        uuid_cache="$(mktemp)"
        cp "${out}/.amo-upload-uuid" "$uuid_cache"
    fi

    # Rebuild from scratch so a file deleted from ext/shared doesn't linger in
    # the output and get shipped.
    rm -rf "$out"
    mkdir -p "$out"

    if [[ -n "$uuid_cache" ]]; then
        mv "$uuid_cache" "${out}/.amo-upload-uuid"
    fi

    cp "${SHARED}/popup.html" "${SHARED}/popup.js" "${SHARED}/background.js" "$out/"
    cp -R "${SHARED}/icons" "$out/icons"
    cp "${src}/manifest.json" "$out/manifest.json"

    local version
    version="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" \
               "${out}/manifest.json")"
    echo "  ${browser}-ext/  manifest v${version}"
}

targets=("$@")
if [[ ${#targets[@]} -eq 0 ]]; then
    targets=(firefox chrome)
fi

echo "Building from ext/shared:"
for t in "${targets[@]}"; do
    build "$t"
done

echo
echo "Firefox: ./sign_extension.sh   (or about:debugging → Load Temporary Add-on)"
echo "Chrome:  chrome://extensions → Developer mode → Load unpacked → chrome-ext/"
