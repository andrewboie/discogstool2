/**
 * background.js — Extension background page for the Discogs Label Printer.
 *
 * Responsibilities:
 *  1. Enable/disable the browser action (toolbar button) based on whether the
 *     active tab is a Discogs release page (URL matches RELEASE_URL).
 *  2. Register a right-click context menu item ("Print Label") on Discogs
 *     release links, so labels can be printed without opening the popup.
 *  3. Send print requests to dt_server via POST http://localhost:{port}/print.
 *
 * Communication with dt_server:
 *  - All requests go to http://localhost:{port}/ where port defaults to 5679
 *    and is persisted in browser.storage.local under the key "port".
 *  - The context menu handler reads the stored profile/split/preview settings
 *    and sends the same JSON body as the popup's print button.
 */

// Show/enable the browser action only on Discogs release pages.
// URL pattern: discogs.com/release/DIGITS or discogs.com/*/release/DIGITS

const RELEASE_URL = /discogs\.com\/(?:[^/]+\/)?release\/(\d+)/;
const DISCOGS_URL  = /discogs\.com/;
const DEFAULT_PORT = 5679;
const STORAGE_KEYS = ["port", "profile", "split", "hide_bpm", "preview"];

function updateAction(tabId, url) {
  if (url && DISCOGS_URL.test(url)) {
    browser.browserAction.enable(tabId);
  } else {
    browser.browserAction.disable(tabId);
  }
}

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url !== undefined) {
    updateAction(tabId, changeInfo.url);
  }
});

browser.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await browser.tabs.get(tabId);
  updateAction(tabId, tab.url);
});

// Disable on all tabs at startup; they'll re-enable via onActivated.
browser.tabs.query({}).then(tabs => {
  for (const tab of tabs) {
    updateAction(tab.id, tab.url);
  }
});

// ── Context menu: right-click a Discogs release link to print ─────────────────

browser.menus.create({
  id: "print-label",
  title: "Print Label",
  contexts: ["link"],
  targetUrlPatterns: [
    "*://*.discogs.com/*/release/*",
    "*://*.discogs.com/release/*",
  ],
});

browser.menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "print-label") return;

  const m = RELEASE_URL.exec(info.linkUrl);
  if (!m) return;
  const releaseId = m[1];

  const stored  = await browser.storage.local.get(STORAGE_KEYS);
  const port    = stored.port    || DEFAULT_PORT;
  const profile = stored.profile || "dk1247";
  const split   = stored.split   || false;
  const hideBpm = stored.hide_bpm || false;
  const preview = stored.preview || false;

  // Print jobs are queued server-side and return immediately, so this no
  // longer needs a two-minute timeout. Preview still runs synchronously
  // because the response carries the PNG URLs we need to open.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), preview ? 30_000 : 10_000);
  try {
    const resp = await fetch(`http://localhost:${port}/print`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        release_id: releaseId, profile, preview, split, discs: null,
        hide_bpm: hideBpm,
      }),
      signal: controller.signal,
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(data.message || `Server error ${resp.status}`);
    }
    if (preview && data.preview_urls?.length) {
      for (const url of data.preview_urls) {
        browser.tabs.create({ url: `http://localhost:${port}${url}` });
      }
    } else if (!preview) {
      // Don't claim it printed — it's only queued at this point. The badge
      // and the popup's stage list report what actually happens next.
      pollUntilIdle();
    }
  } catch (err) {
    const msg = err.name === "AbortError"
      ? `Request timed out — is dt_server running on port ${port}?`
      : err.message || String(err);
    console.error("Print Label context menu error:", err);
    notify("Print failed", msg, true);
  } finally {
    clearTimeout(timer);
  }
});

function notify(title, message, isError = false) {
  browser.notifications.create({
    type:    "basic",
    iconUrl: isError ? "icons/icon-48.png" : "icons/icon-48.png",
    title,
    message,
  });
}

// ── Toolbar badge ─────────────────────────────────────────────────────────────
// Shows queue depth while work is outstanding, and a failure count afterwards.
// Polling only runs while something is active so an idle browser stays quiet.

const BADGE_POLL_MS = 1000;
let badgeTimer = null;
let lastFailures = 0;

async function refreshBadge() {
  const stored = await browser.storage.local.get(["port"]);
  const port   = stored.port || DEFAULT_PORT;

  let data;
  try {
    const resp = await fetch(`http://localhost:${port}/progress`,
                             { signal: AbortSignal.timeout(2000) });
    data = await resp.json();
  } catch {
    // Server gone: clear the badge and stop polling until the next print.
    setBadge("", "#666");
    stopPolling();
    return;
  }

  if (data.depth > 0) {
    setBadge(String(data.depth), "#d6844a");
    return true;                       // keep polling
  }

  if (data.failures > 0) {
    setBadge(String(data.failures), "#e06060");
    // Notify once per new failure rather than on every poll.
    if (data.failures > lastFailures) {
      const failed = (data.recent || []).find(j => j.state === "error");
      notify("Print failed", failed?.error || "A print job failed.", true);
    }
    lastFailures = data.failures;
    stopPolling();
    return false;
  }

  lastFailures = 0;
  setBadge("", "#666");
  stopPolling();
  return false;
}

function setBadge(text, colour) {
  browser.browserAction.setBadgeText({ text });
  if (text) {
    browser.browserAction.setBadgeBackgroundColor({ color: colour });
  }
}

function pollUntilIdle() {
  if (badgeTimer !== null) return;     // already polling
  refreshBadge();
  badgeTimer = setInterval(refreshBadge, BADGE_POLL_MS);
}

function stopPolling() {
  if (badgeTimer !== null) {
    clearInterval(badgeTimer);
    badgeTimer = null;
  }
}

// The popup posts its own print requests, so listen for those too and start
// the badge poll on its behalf.
browser.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "job-queued") pollUntilIdle();
});

// Pick up anything already running when the browser starts.
refreshBadge();
