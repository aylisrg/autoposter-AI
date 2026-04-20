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

type HumanizerConfig = {
  typing_wpm_min: number;
  typing_wpm_max: number;
  mistake_rate: number;
  pause_between_sentences_ms_min: number;
  pause_between_sentences_ms_max: number;
  mouse_path_curvature: number;
  idle_scroll_before_post_sec_min: number;
  idle_scroll_before_post_sec_max: number;
};

const DEFAULT_HUMANIZER: HumanizerConfig = {
  typing_wpm_min: 35,
  typing_wpm_max: 70,
  mistake_rate: 0.02,
  pause_between_sentences_ms_min: 250,
  pause_between_sentences_ms_max: 900,
  mouse_path_curvature: 0.35,
  idle_scroll_before_post_sec_min: 3,
  idle_scroll_before_post_sec_max: 12,
};

type PublishMsg = {
  type: "publish";
  text: string;
  image_url?: string | null;
  first_comment?: string | null;
  humanizer?: HumanizerConfig | null;
};

type ListGroupsMsg = { type: "list_groups" };
type ListSuggestedMsg = { type: "list_suggested_groups" };
type FetchMetricsMsg = { type: "fetch_metrics" };
type SmokeMsg = { type: "smoke" };
type CsPingMsg = { type: "cs_ping" };

type Msg =
  | PublishMsg
  | ListGroupsMsg
  | ListSuggestedMsg
  | FetchMetricsMsg
  | SmokeMsg
  | CsPingMsg;

chrome.runtime.onMessage.addListener((msg: Msg, _sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {
        case "cs_ping": {
          // Readiness probe from background.ts — answer synchronously-ish.
          sendResponse({ ok: true });
          break;
        }
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
        case "fetch_metrics": {
          const metrics = await scrapePostMetrics();
          sendResponse({ ok: true, metrics });
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
  commentButton: [
    "comment",
    "leave a comment",
    "комментировать",
    "написать комментарий",
    "comentar",
    "kommentieren",
  ],
  commentComposer: [
    "write a comment",
    "write a public comment",
    "напишите комментарий",
    "escribe un comentario",
    "schreibe einen kommentar",
  ],
  checkpoint: [
    "please re-enter your password",
    "we'll send a login code",
    "подтверждение безопасности",
    "confirm your identity",
  ],
  // FB renders a prominent CTA when the current user is NOT a member of the
  // group they're viewing. The composer is hidden in that case, so matching
  // this label gives us a clearer error than "composer_trigger_not_found".
  joinGroup: [
    "join group",
    "join this group",
    "ask to join",
    "request to join",
    "вступить в группу",
    "запросить вступление",
    "unirse al grupo",
    "solicitar unirse",
    "gruppe beitreten",
    "beitritt anfragen",
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
): Promise<{ post_url?: string; post_id?: string; comment_warning?: string }> {
  // 0. Fail fast if we're on a checkpoint / login screen.
  assertNotCheckpointed();

  const hz: HumanizerConfig = { ...DEFAULT_HUMANIZER, ...(msg.humanizer || {}) };

  // Warm-up: idle scroll before interacting — a human reads the feed first.
  await humanIdleScroll(hz);

  // 1. Find the composer trigger ("Write something...").
  const trigger = await waitFor(() => findComposerTrigger(), 15000);
  if (!trigger) {
    // Most common cause: user isn't a member of the group. FB hides the
    // composer entirely and shows a "Join group" CTA instead. Surface that
    // as a specific, actionable error so the dashboard can explain.
    if (isGroupPage() && findJoinGroupButton()) {
      throw new Error(
        "not_a_group_member: this account isn't a member of the group — join it first (or accept the pending request)",
      );
    }
    throw new Error(
      `composer_trigger_not_found: locale=${detectLocale()} url=${location.pathname}`,
    );
  }
  await humanHover(trigger, hz);
  simulateClick(trigger);

  // 2. Wait for the composer dialog + editor.
  const composer = await waitFor(() => findComposerEditor(), 10000);
  if (!composer) throw new Error("composer_editor_did_not_open");

  // 3. Type text character-by-character with humanizer pacing.
  composer.focus();
  await humanType(composer, msg.text, hz);

  // 4. Attach image if provided.
  if (msg.image_url) {
    await attachImage(msg.image_url);
  }

  // 5. Click "Post".
  const postBtn = await waitFor(() => findPostButton(), 10000);
  if (!postBtn) throw new Error("post_button_not_found_or_disabled");
  await humanHover(postBtn, hz);
  await sleep(600 + Math.random() * 900); // final hesitation
  simulateClick(postBtn);

  // 6. Wait for the composer to close as first success signal.
  const closed = await waitFor(() => !findComposerEditor(), 25000);
  if (!closed) {
    assertNotCheckpointed();
    throw new Error("composer_did_not_close_after_post");
  }

  // 7. Try to find the freshly posted item by first-line match.
  const firstLine = msg.text.split("\n")[0].slice(0, 40);
  const article = await waitFor(() => findFreshPostArticle(firstLine), 20000);
  const permalink = article ? extractPermalink(article) : null;

  // 8. Optional first comment. Best-effort — if the comment flow fails we
  //    surface a warning but still consider the publish successful, because
  //    the post itself already committed.
  let comment_warning: string | undefined;
  if (msg.first_comment && msg.first_comment.trim()) {
    if (!article) {
      comment_warning = "first_comment_skipped_no_article";
    } else {
      try {
        await addFirstComment(article, msg.first_comment, hz);
      } catch (err) {
        comment_warning =
          err instanceof Error ? err.message : String(err);
      }
    }
  }

  return {
    post_url: permalink ?? undefined,
    comment_warning,
  };
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

function isGroupPage(): boolean {
  return /^\/groups\/[^/]+/.test(location.pathname);
}

function findJoinGroupButton(): HTMLElement | null {
  // Search only visible role=button elements — FB sometimes keeps stale DOM
  // nodes from previous navigations; restricting to the main scope avoids
  // false positives from a cached page preview.
  const scope =
    document.querySelector<HTMLElement>('[role="main"]') ?? document.body;
  const buttons = scope.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") ?? b.textContent ?? "").trim();
    if (matchesLabel(label, LABELS.joinGroup)) return b;
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

function findFreshPostArticle(firstLine: string): HTMLElement | null {
  if (!firstLine) return null;
  const needle = firstLine.toLowerCase();
  // FB feed items live under role=article. Match by innerText.
  const articles = document.querySelectorAll<HTMLElement>('div[role="article"]');
  for (const art of articles) {
    const text = (art.innerText || "").toLowerCase();
    if (!text.includes(needle)) continue;
    return art;
  }
  return null;
}

function extractPermalink(article: HTMLElement): string | null {
  // Permalinks look like `/groups/{id}/posts/{id}` or `/permalink/{id}`.
  const link = article.querySelector<HTMLAnchorElement>(
    'a[href*="/posts/"], a[href*="/permalink/"], a[href*="/groups/"][href*="/permalink"]',
  );
  return link?.href ?? null;
}

// ---------- First comment ----------

async function addFirstComment(
  article: HTMLElement,
  text: string,
  hz: HumanizerConfig,
): Promise<void> {
  article.scrollIntoView({ behavior: "smooth", block: "center" });
  await sleep(600 + Math.random() * 600);

  // The comment composer is often already rendered inline; if not, clicking
  // the article's Comment button lazy-mounts it.
  let editor = findCommentEditor(article);
  if (!editor) {
    const btn = findCommentButton(article);
    if (!btn) throw new Error("comment_button_not_found");
    await humanHover(btn, hz);
    simulateClick(btn);
    editor = await waitFor(() => findCommentEditor(article), 8000);
  }
  if (!editor) throw new Error("comment_editor_did_not_open");

  editor.focus();
  await humanType(editor, text, hz);
  await sleep(400 + Math.random() * 600);

  // FB comment submit: Enter inside the textbox. We send a full keydown chain
  // so React commits the comment. A fallback path clicks an explicit submit
  // button if one exists (some FB surfaces render a paper-plane icon).
  editor.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "Enter",
      code: "Enter",
      keyCode: 13,
      which: 13,
      bubbles: true,
      cancelable: true,
    }),
  );
  editor.dispatchEvent(
    new KeyboardEvent("keyup", {
      key: "Enter",
      code: "Enter",
      keyCode: 13,
      which: 13,
      bubbles: true,
    }),
  );

  // Verify: the editor should empty within a few seconds.
  const empty = await waitFor(
    () => !editor!.textContent?.includes(text.slice(0, 20)),
    8000,
  );
  if (!empty) {
    const submit = findCommentSubmitButton(article);
    if (submit) {
      simulateClick(submit);
      const empty2 = await waitFor(
        () => !editor!.textContent?.includes(text.slice(0, 20)),
        6000,
      );
      if (!empty2) throw new Error("comment_submit_did_not_clear_editor");
    } else {
      throw new Error("comment_submit_no_effect");
    }
  }
}

function findCommentButton(article: HTMLElement): HTMLElement | null {
  const buttons = article.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") ?? b.textContent ?? "").trim();
    if (matchesLabel(label, LABELS.commentButton)) return b;
  }
  return null;
}

function findCommentEditor(article: HTMLElement): HTMLElement | null {
  // 1) Match by aria-label (most robust when FB localizes).
  const labeled = article.querySelectorAll<HTMLElement>(
    '[contenteditable="true"][role="textbox"][aria-label]',
  );
  for (const el of labeled) {
    if (matchesLabel(el.getAttribute("aria-label"), LABELS.commentComposer)) {
      return el;
    }
  }
  // 2) Fallback: any contenteditable textbox inside the article (post
  //    editor is already closed at this point, so anything remaining is the
  //    comment composer).
  return article.querySelector<HTMLElement>(
    '[contenteditable="true"][role="textbox"]',
  );
}

function findCommentSubmitButton(article: HTMLElement): HTMLElement | null {
  const buttons = article.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") ?? "").toLowerCase();
    if (label.includes("comment") && (label.includes("post") || label.includes("submit"))) {
      return b;
    }
    if (label === "comment" || label === "отправить" || label === "enviar") {
      return b;
    }
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

// ---------- Post metrics scraping ----------

type ScrapedMetrics = {
  likes: number;
  comments: number;
  shares: number;
  reach: number | null;
};

function parseCount(text: string): number | null {
  if (!text) return null;
  // Strip commas; match the first number with optional K/M suffix.
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

/**
 * Scrape engagement counters off a permalink page.
 *
 * FB constantly reshuffles markup, so we look for any of:
 * - `aria-label` strings matching "123 reactions", "12 comments", "3 shares"
 * - role="button" elements whose text starts with digits + "comments/shares"
 *
 * We return zeros for things we couldn't find (rather than throwing) — the
 * backend records a sparse row and tries again next window.
 */
async function scrapePostMetrics(): Promise<ScrapedMetrics> {
  // Give the page one more beat for async counters to hydrate.
  await sleep(800);

  const result: ScrapedMetrics = {
    likes: 0,
    comments: 0,
    shares: 0,
    reach: null,
  };

  const labelPatterns: Array<{ key: keyof ScrapedMetrics; rx: RegExp }> = [
    { key: "likes", rx: /(?:^|\s)([\d.,]+[KkMm]?)\s*(?:reactions?|likes?|reactions and|реакци|likes)/i },
    { key: "comments", rx: /([\d.,]+[KkMm]?)\s*(?:comments?|комментари|comentarios?)/i },
    { key: "shares", rx: /([\d.,]+[KkMm]?)\s*(?:shares?|поделились|compartidos?)/i },
  ];

  const allText = new Set<string>();
  // aria-label carries the canonical counts on reaction/comment/share buttons.
  document
    .querySelectorAll<HTMLElement>("[aria-label]")
    .forEach((el) => {
      const v = el.getAttribute("aria-label");
      if (v) allText.add(v);
    });
  // role=button / role=link elements often have the visible count as textContent.
  document
    .querySelectorAll<HTMLElement>('[role="button"], [role="link"], span')
    .forEach((el) => {
      const t = el.textContent?.trim() || "";
      if (t && t.length < 80) allText.add(t);
    });

  for (const pattern of labelPatterns) {
    for (const t of allText) {
      const m = t.match(pattern.rx);
      if (m) {
        const n = parseCount(m[1]);
        if (n !== null && n > result[pattern.key]) {
          // Highest match wins — FB sometimes renders both "123" and "123 reactions"
          // in different positions; we want the explicit count.
          (result as unknown as Record<string, number>)[pattern.key] = n;
          break;
        }
      }
    }
  }

  return result;
}

// ---------- Smoke test (popup-triggered) ----------

type SmokeReport = {
  locale: string;
  url: string;
  is_group_page: boolean;
  is_logged_in: boolean;
  checkpoint_detected: boolean;
  is_group_member: boolean | null;
  composer_trigger: boolean;
  composer_editor_when_open: boolean;
  post_button_when_open: boolean;
  photo_video_button_when_open: boolean;
  comment_button_on_article: boolean;
  comment_editor_on_article: boolean;
  groups_detected: number;
  articles_detected: number;
  warnings: string[];
};

async function runSmoke(): Promise<SmokeReport> {
  const warnings: string[] = [];
  const url = location.href;
  const path = location.pathname;
  const isGroupPage = /^\/groups\/[^/]+/.test(path);

  // Checkpoint detection without throwing (runSmoke must never throw).
  let checkpoint = false;
  try {
    assertNotCheckpointed();
  } catch {
    checkpoint = true;
    warnings.push("checkpoint_detected");
  }

  // Logged-in heuristic: FB renders a "Your profile" shortcut for logged-in
  // users; logged-out pages redirect to /login.
  const isLoggedIn = !/login|checkpoint/i.test(path);

  if (!isGroupPage) {
    warnings.push(
      `not_on_group_page: open facebook.com/groups/<id> before smoke (current=${path})`,
    );
  }

  // Membership: only meaningful if we're actually on a group page. Composer
  // presence is the positive signal; Join button presence is the negative.
  let isMember: boolean | null = null;
  if (isGroupPage) {
    const hasComposer = !!findComposerTrigger();
    const hasJoin = !!findJoinGroupButton();
    if (hasComposer) isMember = true;
    else if (hasJoin) isMember = false;
  }

  const report: SmokeReport = {
    locale: detectLocale(),
    url,
    is_group_page: isGroupPage,
    is_logged_in: isLoggedIn,
    checkpoint_detected: checkpoint,
    is_group_member: isMember,
    composer_trigger: !!findComposerTrigger(),
    composer_editor_when_open: false,
    post_button_when_open: false,
    photo_video_button_when_open: false,
    comment_button_on_article: false,
    comment_editor_on_article: false,
    groups_detected: (await listGroups()).length,
    articles_detected: document.querySelectorAll('div[role="article"]').length,
    warnings,
  };

  if (isGroupPage && isMember === false) {
    warnings.push(
      "not_a_group_member: posting will fail — join the group (or accept pending request) first",
    );
  } else if (!report.composer_trigger && isGroupPage && !checkpoint) {
    warnings.push("composer_trigger_missing: selectors may be stale");
  }

  // If we can find the trigger, open the composer and probe inner controls.
  const trigger = findComposerTrigger();
  if (trigger) {
    simulateClick(trigger);
    await sleep(1500);
    report.composer_editor_when_open = !!findComposerEditor();
    report.post_button_when_open = !!findPostButton();
    report.photo_video_button_when_open = !!findPhotoVideoButton();
    if (!report.composer_editor_when_open) {
      warnings.push("composer_editor_not_found_after_open");
    }
    if (!report.post_button_when_open) {
      warnings.push("post_button_not_found_after_open");
    }
    // Try to close
    const dialog = findComposerDialog();
    dialog
      ?.querySelector<HTMLElement>('[aria-label="Close"], [aria-label="Закрыть"]')
      ?.click();
  }

  // Probe comment wiring on whichever article is currently visible.
  const firstArticle = document.querySelector<HTMLElement>('div[role="article"]');
  if (firstArticle) {
    report.comment_button_on_article = !!findCommentButton(firstArticle);
    report.comment_editor_on_article = !!findCommentEditor(firstArticle);
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

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function randInt(min: number, max: number): number {
  return Math.floor(rand(min, max + 1));
}

// ---------- Humanizer helpers ----------

async function humanIdleScroll(hz: HumanizerConfig): Promise<void> {
  const durSec = rand(
    hz.idle_scroll_before_post_sec_min,
    hz.idle_scroll_before_post_sec_max,
  );
  const end = Date.now() + durSec * 1000;
  while (Date.now() < end) {
    // Small irregular scrolls, occasional pauses — mimics "reading".
    window.scrollBy({
      top: Math.random() < 0.15 ? -randInt(80, 250) : randInt(120, 420),
      behavior: "smooth",
    });
    await sleep(randInt(600, 1800));
  }
}

async function humanHover(target: HTMLElement, hz: HumanizerConfig): Promise<void> {
  // Simulate a bezier-curve mouse approach without actually moving the OS
  // cursor (we can't). We dispatch mousemove/mouseover events along the path,
  // which is enough to unlock hover states / analytics FB relies on.
  const rect = target.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;

  const endX = rect.left + rect.width / 2;
  const endY = rect.top + rect.height / 2;
  const startX = endX + (Math.random() - 0.5) * 400;
  const startY = endY + (Math.random() - 0.5) * 400;
  // Control points bend the path.
  const curve = hz.mouse_path_curvature;
  const cx = (startX + endX) / 2 + (Math.random() - 0.5) * 200 * curve;
  const cy = (startY + endY) / 2 + (Math.random() - 0.5) * 200 * curve;

  const steps = randInt(12, 28);
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    // Quadratic bezier
    const x = (1 - t) * (1 - t) * startX + 2 * (1 - t) * t * cx + t * t * endX;
    const y = (1 - t) * (1 - t) * startY + 2 * (1 - t) * t * cy + t * t * endY;
    const evt = new MouseEvent("mousemove", {
      clientX: x,
      clientY: y,
      bubbles: true,
      cancelable: true,
      view: window,
    });
    document.elementFromPoint(x, y)?.dispatchEvent(evt);
    await sleep(randInt(8, 24));
  }
  target.dispatchEvent(
    new MouseEvent("mouseover", {
      clientX: endX,
      clientY: endY,
      bubbles: true,
      view: window,
    }),
  );
}

const QWERTY_NEIGHBORS: Record<string, string> = {
  a: "sqwz",
  b: "vghn",
  c: "xdfv",
  d: "serfcx",
  e: "wrdsf",
  f: "drtgvc",
  g: "ftyhbv",
  h: "gyujnb",
  i: "uojkl",
  j: "huikmn",
  k: "jiolm",
  l: "kop",
  m: "njk",
  n: "bhjm",
  o: "iklp",
  p: "ol",
  q: "was",
  r: "edft",
  s: "awdxz",
  t: "rfgy",
  u: "yhji",
  v: "cfgb",
  w: "qase",
  x: "zsdc",
  y: "tghu",
  z: "asx",
};

function typoFor(ch: string): string {
  const lower = ch.toLowerCase();
  const neighbors = QWERTY_NEIGHBORS[lower];
  if (!neighbors) return ch;
  const pick = neighbors[randInt(0, neighbors.length - 1)];
  return ch === lower ? pick : pick.toUpperCase();
}

async function humanType(
  el: HTMLElement,
  text: string,
  hz: HumanizerConfig,
): Promise<void> {
  el.focus();
  // Convert WPM to ms-per-char. Avg word = 5 chars.
  const wpm = rand(hz.typing_wpm_min, hz.typing_wpm_max);
  const avgMsPerChar = 60_000 / (wpm * 5);

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    // Occasional typo + correction
    if (/[a-zA-Z]/.test(ch) && Math.random() < hz.mistake_rate) {
      const wrong = typoFor(ch);
      insertChar(el, wrong);
      await sleep(avgMsPerChar * rand(0.8, 1.5));
      // Backspace correction
      insertBackspace(el);
      await sleep(avgMsPerChar * rand(0.3, 0.8));
    }
    insertChar(el, ch);
    // Variance per-char: +/- 50% around avg.
    let delay = avgMsPerChar * rand(0.5, 1.5);
    if (ch === "." || ch === "!" || ch === "?" || ch === "\n") {
      delay += rand(
        hz.pause_between_sentences_ms_min,
        hz.pause_between_sentences_ms_max,
      );
    }
    await sleep(delay);
  }
  // Verify — fall back to whole-text paste if somehow the editor didn't receive it.
  if (!el.textContent?.includes(text.slice(0, 20))) {
    await pasteText(el, text);
  }
}

function insertChar(el: HTMLElement, ch: string): void {
  // Fire key events so React/FB's composer validates content.
  el.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
  if (ch === "\n") {
    document.execCommand("insertLineBreak", false);
  } else {
    document.execCommand("insertText", false, ch);
  }
  el.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
  el.dispatchEvent(new InputEvent("input", { data: ch, bubbles: true }));
}

function insertBackspace(el: HTMLElement): void {
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }));
  document.execCommand("delete", false);
  el.dispatchEvent(new KeyboardEvent("keyup", { key: "Backspace", bubbles: true }));
  el.dispatchEvent(new InputEvent("input", { inputType: "deleteContentBackward", bubbles: true }));
}

console.log("[autoposter-AI] content script loaded", { locale: detectLocale() });
