# M0 verification checklist

Manual end-to-end test that proves the Foundation Hardening milestone is done.
Run through this before tagging M0 complete.

## 0. Prereqs

- Python 3.11+ and Node 20+ installed.
- `.env` exists at repo root with `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` filled.
- Throwaway Facebook account logged in (not your primary one).
- Chrome / Chromium browser with Developer mode on at `chrome://extensions`.

## 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/                      # 11 tests should pass
uvicorn app.main:app --port 8787
```

Expected:
- Log lines include `Scheduler started (tick = 30s)`.
- `curl http://localhost:8787/healthz` → `{"ok":true,...}`.
- `curl http://localhost:8787/api/status` → `scheduler_running:true`, `extension_connected:false`.

## 2. Dashboard

```bash
cd dashboard
npm install
npm run dev                        # http://localhost:3000
```

Open http://localhost:3000 → redirects to `/profile`.

- [ ] Yellow Facebook-ToS warning banner visible.
- [ ] Save a minimal profile (name + description) → "Saved." message.
- [ ] Status bar shows `Backend v0.1.0`, `Scheduler: running`.

## 3. Extension

```bash
cd extension
npm install
npm run build
```

Then in Chrome:
1. `chrome://extensions` → Developer mode ON → "Load unpacked" → pick `extension/dist/`.
2. Click the extension icon → popup shows `Backend: OK — extension linked` within ~3s.
3. Dashboard status bar flips to `Extension: connected`.

## 4. Add a target

- Dashboard → Targets → paste a FB group URL you moderate (or a test group) → Add.
- Confirm row appears with status `active`.
- (Optional) Open a facebook.com tab → Extension popup → "Run FB selector smoke test"
  → JSON report should have `composer_trigger: true` on a group page.

## 5. Compose + Publish now

- Dashboard → Compose.
- Post type `informative`, topic hint `"smoke test: ignore"`.
- Click **Generate text (Claude)**. Wait ~4–8s → text appears in the textarea.
- Select your target → **Publish now**.
- Expected:
  - `"1/1 posted"` message.
  - Dashboard → Queue → post status `posted`, variant row has an `open` link.
  - Open the link → verify the post is actually live in the FB group.

## 6. Schedule flow

- Compose → type "scheduled smoke test" in textarea → select target → set
  "Schedule for" = now + 2 min → click **Schedule**.
- Expected within ~2 min 30 s:
  - Backend log shows `[scheduler.jobs] Sleeping ... s before next variant` lines.
  - Queue → post flips from `scheduled` to `posting` to `posted`.
  - Post visible in FB group.

## 7. Feedback

- Queue → thumbs up a post → `POST /api/feedback` 201 in network tab.

## 8. Failure paths we should handle gracefully

- Disable extension → Compose → Publish now → dashboard shows error "Extension not connected".
- Unplug internet → Compose → Generate → dashboard shows the Anthropic error clearly.

## Done when

Boxes 1–7 tick. Failure path (8) produces a readable error, not a crash.
Commit & push; open M1 tickets.
