# Architecture

Self-hosted AI poster: three local processes talk over HTTP and WebSocket.

## System diagram

```
┌────────────────┐     HTTP      ┌──────────────────┐     WebSocket    ┌──────────────────┐
│   Dashboard    │ ──────────▶  │   Backend (API)  │ ◀─────────────▶ │ Chrome extension │
│   Next.js 15   │               │    FastAPI       │                  │  Manifest V3     │
│  :3000         │               │   :8787          │                  │  content script  │
└────────────────┘               └────────┬─────────┘                  └────────┬─────────┘
                                          │                                       │
                    ┌─────────────────────┼─────────────────────┐                 │
                    ▼                     ▼                     ▼                 ▼
             ┌────────────┐        ┌────────────┐        ┌────────────┐   ┌──────────────┐
             │  SQLite    │        │ APScheduler│        │ AI layer   │   │ Facebook DOM │
             │  + media   │        │ jobs       │        │ Claude /   │   │ (composer)   │
             └────────────┘        └────────────┘        │ Gemini     │   └──────────────┘
                                                         └────────────┘
```

Instagram / Threads publish via Meta Graph API (no extension). Facebook Groups use the extension bridge.

## Components

| Path | Role |
|------|------|
| `backend/` | FastAPI app: REST, WebSocket bridge, scheduler, agents, platforms, SQLite |
| `dashboard/` | Next.js UI: profile, plans, queue, targets, media, analytics, humanizer |
| `extension/` | Chrome MV3: connect to backend WS, drive Facebook composer (type, attach, post) |
| `docs/` | Install, troubleshooting, ban FAQ, this architecture note |

### Backend layout (`backend/app/`)

- `main.py` — lifespan (DB init, scheduler start/stop), middleware, router mount
- `api/` — HTTP routes (`posts`, `plans`, `targets`, `media`, `analytics`, OAuth, …)
- `db/` — SQLAlchemy models + session
- `scheduler/` — APScheduler jobs (publish due posts, metrics, analyst cron)
- `agents/` — Planner, TargetAgent, Analyst
- `platforms/` — `Platform` ABC + Facebook / Instagram / Threads / LinkedIn + registry
- `ai/` — prompts, writer, few-shot store
- `ws/` — extension WebSocket hub
- `security.py` — PIN gate, Fernet at-rest secrets
- `observability.py` — structlog request IDs, `/metrics`

## Agent map

| Agent | Module | Input | Output |
|-------|--------|-------|--------|
| **Planner** | `agents/planner.py` | BusinessProfile, period, goals | `ContentPlan` + `PlanSlot` rows (post types, topic briefs, media hints) |
| **TargetAgent** | `agents/targets.py` | Discovered groups/pages + BusinessProfile | relevance scores, reasoning, optional target lists |
| **Analyst** | `agents/analyst.py` | Recent posts + `PostMetrics` | weekly insight report, hypotheses for optimizer |
| **Writer** (service) | `ai/` | PlanSlot / post type + few-shot examples | post text (and optional image via Gemini) |

Human-in-the-loop: generated posts land in review queue; approve / edit / reject before schedule.

## Data flow (happy path)

1. **Profile** — user fills BusinessProfile (tone, windows, post-type ratios) via dashboard → `api/business_profile`.
2. **Plan** — `POST /api/plans/generate` runs PlannerAgent → slots in SQLite.
3. **Media** — optional upload to `api/media`; AI tags; attach to slots.
4. **Compose / generate** — Writer fills slot text (spintax variants per target).
5. **Review** — queue UI → approve → status becomes scheduled.
6. **Publish** — APScheduler job picks `scheduled_for ≤ now`:
   - Facebook → WebSocket command to extension → DOM post → result logged.
   - IG / Threads → Meta Graph create_media → publish.
7. **Metrics** — collector scrapes / Graph Insights → `PostMetrics`.
8. **Learn** — Analyst weekly cron; thumbs-up posts feed few-shot store for the next Writer runs.

## Platforms

```
platforms/base.py          Platform ABC (publish, list_targets, adapt_content)
platforms/registry.py      id → implementation
platforms/facebook.py      Extension bridge (WS)
platforms/instagram.py     Meta Graph
platforms/threads.py       Meta Threads API
platforms/linkedin*.py     LinkedIn paths
platforms/meta_graph.py    Shared Graph client
```

Content is adapted per platform (length, hashtags, carousel vs single).

## Trust boundaries

- All traffic is localhost by default; dashboard PIN optional (`DASHBOARD_PIN`).
- Tokens / cookies encrypted at rest with Fernet (`FERNET_KEY` or auto file under `data/`).
- Extension only talks to the configured backend origin; Facebook session stays in the user’s browser.
- No multi-tenant isolation — single-operator design.

## Related docs

- [INSTALL.md](./INSTALL.md) — Docker and from-source setup
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) — extension, OAuth, scheduler
- [BAN_FAQ.md](./BAN_FAQ.md) — humanizer and Facebook risk
- [ROADMAP.md](./ROADMAP.md) — milestones M0–M8
