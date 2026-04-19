# Install

Two ways to run this:

1. **Docker** — one command, most users.
2. **From source** — dev workflow, hot reload.

Either way you need a `.env` in the project root. Copy the template:

```sh
cp .env.example .env
# edit ANTHROPIC_API_KEY, GEMINI_API_KEY at minimum
```

## Option 1 — Docker

```sh
docker compose up -d --build
```

The backend listens on `http://localhost:8787`. The dashboard is not
containerised — run it locally:

```sh
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

The Chrome extension is still loaded as an unpacked extension (see below).

## Option 2 — From source

```sh
# Backend
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8787
```

```sh
# Dashboard
cd dashboard
npm install
npm run dev
```

```sh
# Chrome extension
cd extension
npm install
npm run build
# Then: chrome://extensions → Load unpacked → pick extension/dist
```

## First boot

1. Open `http://localhost:3000` → Profile page. Fill in name / description /
   tone / posting window. Save.
2. Targets page → add a Facebook group URL manually, OR let the extension
   sync (needs you to be logged into Facebook in Chrome).
3. Compose page → generate a post, schedule it.
4. Queue page → see the variants fan out; the scheduler publishes within the
   posting window.

## Environment variables

See `.env.example` for the full list; the ones you'll actually touch:

| Name | Purpose |
|------|---------|
| `ANTHROPIC_API_KEY` | Claude Sonnet / Haiku — required for content gen |
| `GEMINI_API_KEY` | Gemini Flash Image — optional, only if you want AI images |
| `META_APP_ID` / `META_APP_SECRET` | Meta Developer App — needed for Instagram/Threads |
| `META_REDIRECT_URI` | OAuth callback; default `http://localhost:8787/api/meta/oauth/callback` |
| `DASHBOARD_PIN` | Set to any 4–32 char string to gate the dashboard; empty = no auth |
| `FERNET_KEY` | 44-char urlsafe base64 Fernet key for at-rest encryption; auto-generated into `data/.fernet.key` if blank |
| `BACKUP_DIR` | Where daily zips land (default `data/backups`) |
| `BACKUP_KEEP_DAYS` | Retention (default 14) |
