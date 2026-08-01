# Chrome Web Store setup (one time)

`publish_chrome.sh` automates upload and publish, but the item itself and the
API credentials have to be created by hand first. This is that process.

Chrome has no equivalent of AMO's unlisted signing: [Linux is the only platform
where Chrome will install an extension hosted outside the Web
Store](https://developer.chrome.com/docs/extensions/how-to/distribute/host-on-linux).
On macOS an **unlisted** Web Store item is the only way to get a signed,
self-installable, auto-updating extension.

**Unlisted still means reviewed.** Google applies [the same review process to
Public, Unlisted and Private
items](https://developer.chrome.com/docs/webstore/cws-dashboard-distribution).
Unlisted only means it isn't listed in search — anyone with the URL can install
it.

---

## 1. Developer account

1. Go to the [Developer Dashboard](https://chrome.google.com/webstore/devconsole/).
2. Pay the one-time **$5** registration fee.
3. **Enable 2-step verification** on the Google account. Publishing is blocked
   without it, and the error you get otherwise doesn't say so clearly.

Note your **Publisher ID** from **Publisher → Settings**.

## 2. Create the item by hand

The API can update an existing item but cannot create one, so the first upload
is manual.

```bash
./build_ext.sh chrome
cd chrome-ext && zip -r ../dist/first-upload.zip . -x '.*'
```

In the dashboard: **Add new item** → upload that zip. Then fill in:

- **Store listing** — name, description, at least one screenshot (1280×800 or
  640×400), and a 128×128 icon.
- **Privacy** — a single purpose description, and a justification for each
  permission. For this extension:

  | Permission | Justification |
  |---|---|
  | `host_permissions` on localhost | Sends print jobs to `dt_server`, which runs on the user's own machine. No remote server is contacted. |
  | `activeTab` / `tabs` | Reads the Discogs release ID from the current tab's URL. |
  | `contextMenus` | Adds a "Print Label" item to Discogs release links. |
  | `notifications` | Reports print failures. |
  | `storage` | Persists the server port and label preferences locally. |
  | `alarms` | Refreshes the toolbar badge while a print job is queued. |

  Declare that no user data is collected or transmitted — the extension only
  talks to `http://localhost`.

- **Distribution** — set **Visibility: Unlisted**.

Then **publish it manually, once.** This matters: the API [refuses to publish
after a manual visibility change until you have published once with that
visibility](https://developer.chrome.com/docs/webstore/using-api). Skip this and
`publish_chrome.sh` fails in a way that doesn't obviously point at the cause.

Note the **Item ID** from the item's dashboard URL.

## 3. API credentials

1. [Google Cloud Console](https://console.developers.google.com) → create or
   select a project.
2. Search for and enable the **Chrome Web Store API**.
3. **OAuth consent screen** → External → fill in app name, support email and
   developer contact → add your own address under **Test users**.
4. **Credentials** → Create credentials → **OAuth client ID** → *Web
   application* → add `https://developers.google.com/oauthplayground` as an
   authorised redirect URI. Keep the client ID and secret.
5. Open the [OAuth Playground](https://developers.google.com/oauthplayground):
   - Settings (gear) → **Use your own OAuth credentials** → paste ID and secret.
   - In "Input your own scopes" enter
     `https://www.googleapis.com/auth/chromewebstore`.
   - **Authorize APIs**, sign in with the account that *owns the Web Store
     item* — this can differ from the account that owns the Cloud project.
   - **Exchange authorization code for tokens** → copy the **refresh token**.

> If the OAuth consent screen is left in **Testing** mode, refresh tokens expire
> after 7 days and publishing starts failing with an opaque auth error. Publish
> the consent screen (or accept re-issuing the token weekly).

## 4. First run

```bash
./publish_chrome.sh
```

It prompts for the client ID, client secret, refresh token, publisher ID and
item ID, then saves them to `~/.discogstool/cws_auth` with mode 600.

---

## Routine releases

```bash
# bump "version" in BOTH ext/chrome/manifest.json and ext/firefox/manifest.json
./publish_chrome.sh          # build, upload, submit for review
./publish_chrome.sh --status # check review state
./publish_chrome.sh --upload # upload without submitting
```

A test asserts the two manifests keep the same version, so they can't drift.

**Gotchas**

- Re-using a version number is rejected. Bump it first.
- Review takes anywhere from minutes to several days; the extension is not
  installable until it passes.
- Localhost host permissions sometimes attract reviewer questions. The
  justification above — a local helper process, nothing sent off-machine — is
  the honest answer.
