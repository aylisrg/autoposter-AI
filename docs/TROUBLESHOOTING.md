# Troubleshooting

## Backend won't start

- `sqlite3.OperationalError: unable to open database file` → `./data/`
  doesn't exist. `mkdir -p data` in the project root.
- `ModuleNotFoundError: No module named 'cryptography'` → you're outside the
  venv. `source backend/.venv/bin/activate`.
- Port 8787 already in use → `lsof -iTCP:8787`, kill the culprit (likely a
  previous `uvicorn`).

## Dashboard shows "Authentication required"

You set `DASHBOARD_PIN` in `.env`. Click the login box in the top nav and
enter the same value. If you forgot the PIN, edit `.env` and restart the
backend.

## Meta OAuth callback fails

- Check that `META_REDIRECT_URI` matches EXACTLY what's listed in your
  Facebook Developer App → Facebook Login → Settings → Valid OAuth Redirect
  URIs. A trailing slash is enough to break it.
- The Meta App must have the `instagram_content_publish`,
  `instagram_basic`, `pages_show_list`, `pages_read_engagement`,
  `threads_content_publish`, `threads_basic`, and `threads_manage_insights`
  permissions granted.
- Instagram: the account MUST be a Business account connected to a
  Facebook Page. Personal IG accounts can't publish via the Graph API.
- Threads: the API is still evolving; if `list_pages` returns no accounts,
  set `THREADS_USER_ID` manually in `.env` after grabbing it from the
  Graph API Explorer.

## Chrome extension can't find the composer

Facebook rewrites its DOM frequently. The extension ships three layers of
fallback (`aria-label` → `data-pagelet` → role-based). If all three fail,
load the extension popup and click **"Run smoke test"** — it'll log which
selectors miss.

## Scheduler doesn't publish

- Look at `/healthz` — is `scheduler_running: true`?
- Check the humanizer Smart Pause status in `/humanizer` — a string of
  failures triggers a cool-down. Click "Resume now" to override.
- Blackout dates: `/humanizer` → Blackout list.
- Daily rate limit: `MAX_POSTS_PER_DAY` in `.env` (default 50).

## "Instagram requires a publicly-reachable image_url"

The Meta Graph API fetches images server-side. A URL under
`http://localhost:8787/static/...` works only from your machine. For IG
specifically, expose the image via:

- An `ngrok http 8787` tunnel (quick but rotates)
- A CDN upload (Cloudinary / ImageKit — both have free tiers)
- A signed S3 URL

The upload endpoint returns a relative path; the dashboard Compose page has
a "Host this image publicly" helper that hits ngrok if you have it running.

## Weekly Analyst reports are always empty

The Analyst needs at least one `PostMetrics` row to run. Collect metrics
first via `/analytics → Collect metrics` (or wait for the hourly tick).

## Logs

Structured logs go to stdout. Each line has a `rid=<8-hex>` request id you
can grep across the file. Prometheus counters live at `/metrics`.
