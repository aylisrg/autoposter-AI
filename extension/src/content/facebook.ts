/**
 * Facebook content script — hardened selectors + success verification.
 *
 * This is the FRAGILE part of the whole project. Facebook's DOM changes often —
 * every selector here is treated as probably-broken in 6 months.
 *
 * Resilience strategy:
 * - Primary lookup: aria-label / role (localized dictionary for en/ru/es/de).
 * - Secondary: data-pagelet / data-visualcompletion containers.
 * - Text-content fallback for buttons.
 * - Every helper returns null on miss so the orchestrator can throw a typed error.
 *
 * Verification strategy:
 * - After "Post" click, wait for composer dialog to close.
 * - Then scan the feed for the first item whose text starts with our first line;
 *   extract its permalink href and return it as post_url.
 * - If we detect a "re-auth" / checkpoint / captcha dialog, throw { kind: "checkpoint" }.
 */

type PublishMsg = {
  type: "publish";
  text: string;
  image_url?: string | null;
  first_comment?: string | null;
};

type ListGroupsMsg = { type: "list_groups" };
type ListSuggestedMsg = { type: "list_suggested_groups" };
type SmokeMsg = { type: "smoke" };

type Msg = PublishMsg | ListGroupsMsg | ListSuggestedMsg | SmokeMsg;

chrome.runtime.onMessage.addListener((msg: Msg, _sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {
        case "publish": {
          const result = await publishPost(msg);
          sendResponse({ ok: true, ...result });
          break;
        }
        case "list_groups": {
          const groups = await listGroups();
          sendResponse({ ok: true, groups });
          break;
        }
        case "list_suggested_groups": {
          const groups = await listSuggestedGroups();
          sendResponse({ ok: true, groups });
          break;
        }
        case "smoke": {
          const report = await runSmoke();
          sendResponse({ ok: true, report });
          break;
        }
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      sendResponse({ ok: false, error });
    }
  })();
  // Keep the channel open for async response
  return true;
});

// ---------- Localized label dictionary ----------

const LABELS = {
  composerTrigger: [
    "write something",
    "create a post",
    "what's on your mind",
    "напишите что-нибудь",
    "что у вас нового",
    "escribe algo",
    "crea una publicación",
    "was machst du gerade",
    "erstelle einen beitrag",
  ],
  postButton: [
    "post",
    "publish",
    "опубликовать",
    "publicar",
    "posten",
    "veröffentlichen",
  ],
  photoVideoButton: [
    "photo/video",
    "photo",
    "фото/видео",
    "foto/video",
    "foto/vídeo",
    "foto",
  ],
  checkpoint: [
    "please re-enter your password",
    "we'll send a login code",
    "подтверждение безопасности",
    "confirm your identity",
  ],
} as const;

function detectLocale(): string {
  return (document.documentElement.lang || navigator.language || "en")
    .toLowerCase()
    .slice(0, 2);
}

function matchesLabel(value: string | null | undefined, set: readonly string[]): boolean {
  if (!value) return false;
  const lower = value.toLowerCase().trim();
  return set.some((needle) => lower.includes(needle));
}

// ---------- Publish ----------

async function publishPost(
  msg: PublishMsg,
): Promise<{ post_url?: string; post_id?: string }> {
  // 0. Fail fast if we're on a checkpoint / login screen.
  assertNotCheckpointed();

  // 1. Find the composer trigger ("Write something...").
  const trigger = await waitFor(() => findComposerTrigger(), 15000);
  if (!trigger) {
    throw new Error(
      `composer_trigger_not_found: locale=${detectLocale()} url=${location.pathname}`,
    );
  }
  simulateClick(trigger);

  // 2. Wait for the composer dialog + editor.
  const composer = await waitFor(() => findComposerEditor(), 10000);
  if (!composer) throw new Error("composer_editor_did_not_open");

  // 3. Paste text via clipboard simulation (most robust against React).
  composer.focus();
  await pasteText(composer, msg.text);

  // 4. Attach image if provided.
  if (msg.image_url) {
    await attachImage(msg.image_url);
  }

  // 5. Click "Post".
  const postBtn = await waitFor(() => findPostButton(), 10000);
  if (!postBtn) throw new Error("post_button_not_found_or_disabled");
  await sleep(600 + Math.random() * 900); // human-ish pause
  simulateClick(postBtn);

  // 6. Wait for the composer to close as first success signal.
  const closed = await waitFor(() => !findComposerEditor(), 25000);
  if (!closed) {
    assertNotCheckpointed();
    throw new Error("composer_did_not_close_after_post");
  }

  // 7. Try to find the freshly posted item by first-line match.
  const firstLine = msg.text.split("\n")[0].slice(0, 40);
  const permalink = await waitFor(() => findFreshPostPermalink(firstLine), 20000);

  // 8. Optional first comment — left as a TODO for M1+ (requires opening
  //    the comment composer on the fresh permalink).

  return { post_url: permalink ?? undefined };
}

// ---------- Selectors ----------

function findComposerTrigger(): HTMLElement | null {
  // Prefer elements inside the main group composer pagelet when available.
  const scopes: ParentNode[] = [
    document.querySelector('[data-pagelet^="GroupFeedComposer"]') ?? document,
    document,
  ];

  for (const scope of scopes) {
    const candidates = scope.querySelectorAll<HTMLElement>(
      '[role="button"][aria-label], [role="textbox"][aria-label]',
    );
    for (const el of candidates) {
      if (matchesLabel(el.getAttribute("aria-label"), LABELS.composerTrigger)) {
        return el;
      }
    }
  }
  // Text fallback: any element whose own text content is "Write something..."
  const els = document.querySelectorAll<HTMLElement>("span, div");
  for (const el of els) {
    if (el.children.length !== 0) continue;
    const txt = el.textContent?.trim();
    if (txt && matchesLabel(txt, LABELS.composerTrigger)) {
      // Climb up to a clickable parent.
      const btn = el.closest<HTMLElement>('[role="button"], [tabindex]');
      if (btn) return btn;
    }
  }
  return null;
}

function findComposerDialog(): HTMLElement | null {
  return document.querySelector<HTMLElement>('div[role="dialog"]');
}

function findComposerEditor(): HTMLElement | null {
  const dialog = findComposerDialog();
  if (!dialog) return null;
  const editors = dialog.querySelectorAll<HTMLElement>(
    '[contenteditable="true"][role="textbox"]',
  );
  return editors[0] ?? null;
}

function findPostButton(): HTMLElement | null {
  const dialog = findComposerDialog();
  if (!dialog) return null;
  const buttons = dialog.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") ?? b.textContent ?? "").trim();
    if (matchesLabel(label, LABELS.postButton)) {
      const disabled = b.getAttribute("aria-disabled");
      if (disabled === "true") continue;
      return b;
    }
  }
  return null;
}

function findPhotoVideoButton(): HTMLElement | null {
  const dialog = findComposerDialog();
  if (!dialog) return null;
  const buttons = dialog.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") ?? b.textContent ?? "").trim();
    if (matchesLabel(label, LABELS.photoVideoButton)) return b;
  }
  return null;
}

function assertNotCheckpointed(): void {
  const body = document.body?.innerText?.toLowerCase() ?? "";
  for (const needle of LABELS.checkpoint) {
    if (body.includes(needle)) {
      throw new Error(`checkpoint_detected: "${needle}"`);
    }
  }
}

// ---------- Success verification ----------

function findFreshPostPermalink(firstLine: string): string | null {
  if (!firstLine) return null;
  const needle = firstLine.toLowerCase();
  // FB feed items live under role=article. Permalinks look like `/groups/{id}/posts/{id}` or `/permalink/{id}`.
  const articles = document.querySelectorAll<HTMLElement>('div[role="article"]');
  for (const art of articles) {
    const text = (art.innerText || "").toLowerCase();
    if (!text.includes(needle)) continue;
    const link = art.querySelector<HTMLAnchorElement>(
      'a[href*="/posts/"], a[href*="/permalink/"], a[href*="/groups/"][href*="/permalink"]',
    );
    if (link?.href) return link.href;
  }
  return null;
}

// ---------- Image attach ----------

async function attachImage(imageUrl: string): Promise<void> {
  // Fetch the image bytes from our local backend (or absolute URL).
  const full = imageUrl.startsWith("http")
    ? imageUrl
    : `http://localhost:8787${imageUrl.startsWith("/") ? imageUrl : `/${imageUrl}`}`;
  const resp = await fetch(full);
  if (!resp.ok) throw new Error(`fetch_image_failed: ${resp.status}`);
  const blob = await resp.blob();
  const ext = (blob.type.split("/")[1] || "png").split(";")[0];
  const file = new File([blob], `image.${ext}`, { type: blob.type || "image/png" });

  // First try: FB often renders the file input lazily only after you click
  // "Photo/Video". Attempt both paths with a short fallback.
  let input = document.querySelector<HTMLInputElement>(
    'div[role="dialog"] input[type="file"][accept*="image"]',
  );
  if (!input) {
    const pvBtn = findPhotoVideoButton();
    if (pvBtn) {
      simulateClick(pvBtn);
      await sleep(600);
    }
    input = await waitFor(
      () =>
        document.querySelector<HTMLInputElement>(
          'div[role="dialog"] input[type="file"][accept*="image"]',
        ),
      5000,
    );
  }
  if (!input) throw new Error("image_file_input_not_found");

  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));

  // Verify preview thumbnail actually rendered inside the dialog.
  const preview = await waitFor(
    () => document.querySelector<HTMLImageElement>('div[role="dialog"] img[src^="blob:"]'),
    8000,
  );
  if (!preview) throw new Error("image_preview_not_rendered");
}

// ---------- List groups ----------

function parseMemberCount(text: string): number | null {
  // FB renders "12K members", "1,234 участников", "2.4M members", etc.
  const m = text.match(/([\d.,]+)\s*([KkMm])?/);
  if (!m) return null;
  const raw = m[1].replace(/,/g, "");
  const n = parseFloat(raw);
  if (Number.isNaN(n)) return null;
  const suffix = (m[2] || "").toLowerCase();
  if (suffix === "k") return Math.round(n * 1000);
  if (suffix === "m") return Math.round(n * 1_000_000);
  return Math.round(n);
}

async function listGroups(): Promise<
  Array<{ url: string; name: string; role?: string }>
> {
  const results: Array<{ url: string; name: string }> = [];
  const seen = new Set<string>();
  const links = document.querySelectorAll<HTMLAnchorElement>(
    'a[href*="/groups/"]',
  );
  for (const a of links) {
    const href = a.href;
    const m = href.match(/\/groups\/([^/?#]+)/);
    if (!m) continue;
    // Skip "join", "search", "feed", "create" etc. — pseudo-pages, not real groups.
    if (/^(joins|feed|search|create|discover)$/.test(m[1])) continue;
    const url = `https://www.facebook.com/groups/${m[1]}`;
    if (seen.has(url)) continue;
    const text = a.textContent?.trim();
    if (!text || text.length < 2 || text.length > 200) continue;
    seen.add(url);
    results.push({ url, name: text });
  }
  return results;
}

// ---------- Suggested groups ----------

type ScrapedSuggestedGroup = {
  url: string;
  external_id: string;
  name: string;
  member_count?: number;
  description?: string;
  category?: string;
};

async function listSuggestedGroups(): Promise<ScrapedSuggestedGroup[]> {
  // FB's discover page lazy-loads — scroll a few times to pull in more cards.
  for (let i = 0; i < 6; i++) {
    window.scrollBy({ top: window.innerHeight, behavior: "instant" as ScrollBehavior });
    await sleep(700);
  }

  // Each card tends to have a heading-link to the group, a member count line,
  // and (sometimes) a description paragraph. We key off the anchor to
  // `/groups/<id>/` inside the main discovery area.
  const anchors = document.querySelectorAll<HTMLAnchorElement>(
    'a[href*="/groups/"][role="link"]',
  );
  const byUrl = new Map<string, ScrapedSuggestedGroup>();

  for (const a of anchors) {
    const m = a.href.match(/\/groups\/([^/?#]+)\/?/);
    if (!m) continue;
    const slug = m[1];
    if (/^(joins|feed|search|create|discover)$/.test(slug)) continue;
    const url = `https://www.facebook.com/groups/${slug}`;

    const name = (a.textContent || "").trim();
    if (!name || name.length < 2 || name.length > 200) continue;

    // Climb to the closest card container to grab member_count + description.
    const card =
      a.closest<HTMLElement>('[role="article"], [data-visualcompletion="ignore-dynamic"]') ??
      a.parentElement?.parentElement ??
      null;

    let member_count: number | undefined;
    let description: string | undefined;
    if (card) {
      const text = card.innerText || "";
      const lines = text
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);
      for (const line of lines) {
        if (!member_count && /member|участник|miembro|mitglied/i.test(line)) {
          const parsed = parseMemberCount(line);
          if (parsed != null) member_count = parsed;
        }
        if (!description && line.length > 40 && line !== name) {
          description = line.slice(0, 500);
        }
      }
    }

    const existing = byUrl.get(url);
    if (!existing || (!existing.description && description)) {
      byUrl.set(url, {
        url,
        external_id: url,
        name,
        member_count,
        description,
      });
    }
  }

  return [...byUrl.values()];
}

// ---------- Smoke test (popup-triggered) ----------

async function runSmoke(): Promise<{
  locale: string;
  url: string;
  composer_trigger: boolean;
  composer_editor_when_open: boolean;
  post_button_when_open: boolean;
  photo_video_button_when_open: boolean;
  groups_detected: number;
}> {
  const report = {
    locale: detectLocale(),
    url: location.href,
    composer_trigger: !!findComposerTrigger(),
    composer_editor_when_open: false,
    post_button_when_open: false,
    photo_video_button_when_open: false,
    groups_detected: (await listGroups()).length,
  };

  // If we can find the trigger, open the composer and probe inner controls.
  const trigger = findComposerTrigger();
  if (trigger) {
    simulateClick(trigger);
    await sleep(1500);
    report.composer_editor_when_open = !!findComposerEditor();
    report.post_button_when_open = !!findPostButton();
    report.photo_video_button_when_open = !!findPhotoVideoButton();
    // Try to close
    const dialog = findComposerDialog();
    dialog
      ?.querySelector<HTMLElement>('[aria-label="Close"], [aria-label="Закрыть"]')
      ?.click();
  }
  return report;
}

// ---------- Utils ----------

function simulateClick(el: HTMLElement): void {
  const opts = { bubbles: true, cancelable: true, view: window };
  el.dispatchEvent(new PointerEvent("pointerdown", opts));
  el.dispatchEvent(new MouseEvent("mousedown", opts));
  el.dispatchEvent(new PointerEvent("pointerup", opts));
  el.dispatchEvent(new MouseEvent("mouseup", opts));
  el.dispatchEvent(new MouseEvent("click", opts));
}

async function pasteText(el: HTMLElement, text: string): Promise<void> {
  el.focus();
  const dt = new DataTransfer();
  dt.setData("text/plain", text);
  const evt = new ClipboardEvent("paste", {
    clipboardData: dt,
    bubbles: true,
    cancelable: true,
  });
  el.dispatchEvent(evt);
  if (!el.textContent?.includes(text.slice(0, 20))) {
    document.execCommand("insertText", false, text);
  }
  await sleep(300 + Math.random() * 500);
}

function waitFor<T>(
  predicate: () => T | null | undefined | false,
  timeoutMs: number,
): Promise<T | null> {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      const v = predicate();
      if (v) return resolve(v as T);
      if (Date.now() - start > timeoutMs) return resolve(null);
      setTimeout(tick, 200);
    };
    tick();
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

console.log("[autoposter-AI] content script loaded", { locale: detectLocale() });
