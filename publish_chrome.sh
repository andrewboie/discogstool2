#!/usr/bin/env bash
# publish_chrome.sh — Upload and publish the Chrome extension to the Web Store.
#
# The Chrome counterpart of sign_extension.sh. Chrome has no equivalent of
# AMO's unlisted signing — Linux is the only platform where Chrome will install
# an extension hosted outside the Web Store — so an unlisted Web Store item is
# the way to get a signed, self-installable, auto-updating extension on macOS.
#
# One-time setup (see docs/chrome-webstore-setup.md):
#   1. $5 developer registration at chrome.google.com/webstore/devconsole
#   2. Enable 2-step verification on the Google account (required to publish)
#   3. Create the item ONCE by hand: upload a zip, fill in the Store listing and
#      Privacy tabs, set Visibility = Unlisted, and publish it manually.
#      The API cannot create an item, and it refuses to publish after a manual
#      visibility change until you have published once with that visibility.
#   4. Enable the Chrome Web Store API in a Google Cloud project, create an
#      OAuth client, and get a refresh token for the
#      https://www.googleapis.com/auth/chromewebstore scope.
#
# Credentials are stored in ~/.discogstool/cws_auth on first run.
#
# Usage:
#   ./publish_chrome.sh              # build, upload, publish
#   ./publish_chrome.sh --upload     # build and upload, don't submit for review
#   ./publish_chrome.sh --status     # report the item's current review state

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CWS_AUTH_FILE="${HOME}/.discogstool/cws_auth"
EXT_DIR="${SCRIPT_DIR}/chrome-ext"
DIST_DIR="${SCRIPT_DIR}/dist"

API="https://chromewebstore.googleapis.com/v2"
UPLOAD_API="https://chromewebstore.googleapis.com/upload/v2"
SCOPE="https://www.googleapis.com/auth/chromewebstore"

MODE="publish"
case "${1:-}" in
    --upload) MODE="upload" ;;
    --status) MODE="status" ;;
    "")       ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

# ── Credentials ───────────────────────────────────────────────────────────────

load_creds() {
    if [[ -f "$CWS_AUTH_FILE" ]]; then
        while IFS='=' read -r key value; do
            [[ -z "$key" || "$key" == \#* ]] && continue
            [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
            printf -v "$key" '%s' "$value"
        done < "$CWS_AUTH_FILE"
    fi
}

save_creds() {
    mkdir -p "$(dirname "$CWS_AUTH_FILE")"
    cat > "$CWS_AUTH_FILE" <<EOF
CWS_CLIENT_ID=${CWS_CLIENT_ID}
CWS_CLIENT_SECRET=${CWS_CLIENT_SECRET}
CWS_REFRESH_TOKEN=${CWS_REFRESH_TOKEN}
CWS_PUBLISHER_ID=${CWS_PUBLISHER_ID}
CWS_ITEM_ID=${CWS_ITEM_ID}
EOF
    chmod 600 "$CWS_AUTH_FILE"
    echo "  Credentials saved to ${CWS_AUTH_FILE}"
}

load_creds

if [[ -z "${CWS_CLIENT_ID:-}"     || -z "${CWS_CLIENT_SECRET:-}" ||
      -z "${CWS_REFRESH_TOKEN:-}" || -z "${CWS_PUBLISHER_ID:-}"  ||
      -z "${CWS_ITEM_ID:-}" ]]; then
    echo "Chrome Web Store credentials not found."
    echo "See docs/chrome-webstore-setup.md for how to obtain each of these."
    echo ""
    read -rp "OAuth client ID:      " CWS_CLIENT_ID
    read -rp "OAuth client secret:  " CWS_CLIENT_SECRET
    read -rp "OAuth refresh token:  " CWS_REFRESH_TOKEN
    read -rp "Publisher ID:         " CWS_PUBLISHER_ID
    read -rp "Extension (item) ID:  " CWS_ITEM_ID
    echo ""
    save_creds
fi

ITEM_URL="${API}/publishers/${CWS_PUBLISHER_ID}/items/${CWS_ITEM_ID}"

# ── Helpers ───────────────────────────────────────────────────────────────────

# Pull a value out of a JSON response without requiring jq.
json_get() {
    python3 -c '
import json, sys
data = json.load(sys.stdin)
for key in sys.argv[1].split("."):
    if isinstance(data, dict):
        data = data.get(key)
    else:
        data = None
    if data is None:
        break
print(data if data is not None else "")
' "$1"
}

show_errors() {
    python3 -c '
import json, sys
d = json.load(sys.stdin)
for err in d.get("itemError") or []:
    print("  " + (err.get("error_detail") or err.get("errorDetail") or str(err)))
if "error" in d:
    e = d["error"]
    print("  %s: %s" % (e.get("status", "error"), e.get("message", "")))
'
}

access_token() {
    local resp
    resp="$(curl -sS "https://oauth2.googleapis.com/token" \
        -d "client_id=${CWS_CLIENT_ID}" \
        -d "client_secret=${CWS_CLIENT_SECRET}" \
        -d "refresh_token=${CWS_REFRESH_TOKEN}" \
        -d "grant_type=refresh_token")"
    local token
    token="$(printf '%s' "$resp" | json_get access_token)"
    if [[ -z "$token" ]]; then
        echo "Failed to obtain an access token:" >&2
        printf '%s\n' "$resp" >&2
        echo "" >&2
        echo "A refresh token is revoked if unused for 6 months, or if the" >&2
        echo "OAuth consent screen is still in Testing mode (7-day expiry)." >&2
        echo "Delete ${CWS_AUTH_FILE} and re-run to re-enter credentials." >&2
        exit 1
    fi
    printf '%s' "$token"
}

# ── Status only ───────────────────────────────────────────────────────────────

TOKEN="$(access_token)"

if [[ "$MODE" == "status" ]]; then
    echo "Fetching status for item ${CWS_ITEM_ID}…"
    curl -sS -H "Authorization: Bearer ${TOKEN}" \
         -X GET "${ITEM_URL}:fetchStatus" |
        python3 -m json.tool
    exit 0
fi

# ── Build and package ─────────────────────────────────────────────────────────

"${SCRIPT_DIR}/build_ext.sh" chrome

VERSION="$(python3 -c "import json;print(json.load(open('${EXT_DIR}/manifest.json'))['version'])")"
mkdir -p "$DIST_DIR"
ZIP="${DIST_DIR}/discogs-label-printer-chrome-${VERSION}.zip"
rm -f "$ZIP"

# The manifest must sit at the archive root, so zip the directory contents.
( cd "$EXT_DIR" && zip -qr "$ZIP" . -x '.*' )
echo "Packaged $(basename "$ZIP") ($(du -h "$ZIP" | cut -f1))"

# ── Upload ────────────────────────────────────────────────────────────────────

echo "Uploading version ${VERSION}…"
UPLOAD_RESP="$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
    -X POST -T "$ZIP" "${UPLOAD_API}/publishers/${CWS_PUBLISHER_ID}/items/${CWS_ITEM_ID}:upload")"

STATE="$(printf '%s' "$UPLOAD_RESP" | json_get uploadState)"

# A large package may still be processing; poll until it settles.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ "$STATE" == "IN_PROGRESS" || "$STATE" == "UPLOAD_IN_PROGRESS" ]] || break
    echo "  upload in progress…"
    sleep 5
    UPLOAD_RESP="$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
        -X GET "${ITEM_URL}:fetchStatus")"
    STATE="$(printf '%s' "$UPLOAD_RESP" | json_get uploadState)"
done

if [[ "$STATE" != "SUCCESS" ]]; then
    echo "Upload failed (uploadState=${STATE:-unknown}):" >&2
    printf '%s' "$UPLOAD_RESP" | show_errors >&2
    echo "" >&2
    echo "The most common cause is forgetting to bump \"version\" in" >&2
    echo "ext/chrome/manifest.json — the store rejects a re-used version." >&2
    exit 1
fi
echo "  uploaded OK"

if [[ "$MODE" == "upload" ]]; then
    echo ""
    echo "Uploaded but not submitted. Publish from the dashboard, or re-run"
    echo "without --upload to submit for review."
    exit 0
fi

# ── Publish ───────────────────────────────────────────────────────────────────
# The item keeps whatever visibility is configured in the dashboard, so an
# unlisted item stays unlisted. Note that unlisted items are still reviewed.

echo "Submitting for review…"
PUB_RESP="$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Length: 0" -X POST "${ITEM_URL}:publish")"

PUB_STATUS="$(printf '%s' "$PUB_RESP" | python3 -c '
import json, sys
d = json.load(sys.stdin)
s = d.get("status")
print(",".join(s) if isinstance(s, list) else (s or ""))
')"

case "$PUB_STATUS" in
    *OK*)
        echo "  submitted — review pending"
        ;;
    "")
        echo "Publish failed:" >&2
        printf '%s' "$PUB_RESP" | show_errors >&2
        exit 1
        ;;
    *)
        echo "  publish returned: ${PUB_STATUS}"
        printf '%s' "$PUB_RESP" | show_errors
        ;;
esac

echo ""
echo "Version ${VERSION} submitted."
echo "  Dashboard: https://chrome.google.com/webstore/devconsole/"
echo "  Install:   https://chrome.google.com/webstore/detail/${CWS_ITEM_ID}"
echo ""
echo "Unlisted items are reviewed like public ones, so it will not be"
echo "installable until review completes. Check with: ./publish_chrome.sh --status"
