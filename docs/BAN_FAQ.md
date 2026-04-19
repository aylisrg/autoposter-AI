# Ban FAQ — Facebook Groups

Facebook's automated anti-spam heuristics flag accounts that look bot-like.
The project includes a Humanizer layer to reduce that, but zero risk is
impossible. Read this before using the tool against a real account.

## What triggers bans

Roughly in order of impact:

1. **Identical text across many groups** — biggest signal. Spintax on every
   variant helps; a single copy-paste across 50 groups is the fastest ban.
2. **Suspicious velocity** — posting in 20 groups inside an hour looks like a
   script. Default min/max delay is 120–300s between variants; don't
   lower it.
3. **Fresh account** — accounts younger than 6 months or with no activity
   history get flagged harder.
4. **Aged content** — re-posting the exact same image across groups is a
   spam signal. Use AI image gen or rotate uploads.
5. **Network-level signals** — VPNs, datacenter IPs, or logging in from a
   country different from your account's usual. The extension runs in YOUR
   browser, so this is only an issue if you use a VPN.
6. **Group admin reports** — some admins instantly report non-members or
   posts that don't match the group rules. The TargetAgent's relevance
   score helps filter these.

## What the Humanizer does

- Random delays (120–300s default) between variants
- Per-variant spintax — no two groups see the same text
- Character-by-character typing with realistic WPM and occasional typos
- Bezier mouse movement before clicks
- Idle scroll before opening the composer
- Smart pause: 3 failures in a row → 2h cool-down
- Shadow-ban heuristics: detects "your post isn't visible to other members"
  banners and pauses automatically
- Session health: checkpoint / captcha / 2FA detection → immediate stop

## What it does NOT do

- Does not rotate IPs (bad idea for FB)
- Does not spoof user-agent (worse than leaving it alone)
- Does not post while you're actively using the account in another tab —
  it waits for idle

## Recommended settings

- **Personal throwaway account** — 3–5 groups total, posts_per_day=2, 6h+
  posting window. Expect a soft-ban within 2–4 weeks; that's normal.
- **Business page cross-post** — lower risk, but still don't exceed
  posts_per_day=10.
- **Instagram / Threads** — the Meta Graph API is the legitimate path. No
  humanization needed; respect the published rate limits (200 API calls/hour
  per user for IG v21.0).

## If you get flagged

1. STOP the scheduler. `/humanizer` → toggle Smart Pause.
2. Log in manually, browse normally for a few days, engage with 5–10
   posts.
3. When the account looks healthy again, restart with posts_per_day=1 for
   a week.
4. If you get a permanent ban: it is NOT recoverable via this tool. Create
   a new account and learn from the mistake. Don't reuse the same
   throwaway for the new test.

## Legal

Automating posts to Facebook Groups violates the Facebook Terms of Service.
This project is for personal, educational, research use. Using it against
accounts / groups you don't own or run at your own risk.
