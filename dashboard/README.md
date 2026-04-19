# autoposter-AI dashboard

Next.js 15 + Tailwind + shadcn-style UI. Localhost-only, no auth in v1.

## Run

```bash
npm install
npm run dev      # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` if the backend isn't at `http://localhost:8787`.

## Pages

| Path | Purpose |
|------|---------|
| `/profile` | Business profile (singleton). Tone / length / emoji / posting window. |
| `/targets` | Add / remove / sync targets (FB group URLs). |
| `/compose` | Generate via Claude, attach image, publish now or schedule. |
| `/queue` | All posts with per-variant status, thumbs up/down, delete. |

The yellow banner on `/profile` is the Facebook ToS warning — do not remove.
