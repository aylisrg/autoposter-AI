/**
 * Facebook content script.
 *
 * This is the FRAGILE part of the whole project. Facebook's DOM changes often —
 * every selector here should be treated as probably-broken in 6 months and needs
 * a test harness to verify before each deploy.
 *
 * Strategy:
 * - Use aria-label and role attributes where possible (more stable than class names).
 * - Fall back to text matching ("Write something...", "Post") which survives class churn.
 * - Always simulate real user input events (input, change, pointerdown/up, click)
 *   because React's synthetic event system ignores programmatic .value = x.
 */

type PublishMsg = {
  type: "publish";
  text: string;
  image_url?: string | null;
  first_comment?: string | null;
};

type ListGroupsMsg = { type: "list_groups" };

type Msg = PublishMsg | ListGroupsMsg;

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
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      sendResponse({ ok: false, error });
    }
  })();
  // Keep the channel open for async response
  return true;
});

// ---------- Publish ----------

async function publishPost(msg: PublishMsg): Promise<{ post_url?: string; post_id?: string }> {
  // 1. Find the composer trigger ("Write something...")
  const trigger = await waitFor(() => findComposerTrigger(), 15000);
  if (!trigger) throw new Error("Composer trigger not found — is this a group/profile page?");
  simulateClick(trigger);

  // 2. Wait for the composer dialog
  const composer = await waitFor(() => findComposerEditor(), 10000);
  if (!composer) throw new Error("Composer editor did not open");

  // 3. Paste text via clipboard simulation (most robust against React)
  composer.focus();
  await pasteText(composer, msg.text);

  // 4. Attach image if provided (fetch → File → attach input)
  if (msg.image_url) {
    await attachImage(msg.image_url);
  }

  // 5. Click "Post"
  const postBtn = await waitFor(() => findPostButton(), 10000);
  if (!postBtn) throw new Error("Post button not found");
  await sleep(500 + Math.random() * 800); // human-ish pause
  simulateClick(postBtn);

  // 6. Wait for the composer to close as success signal
  await waitFor(() => !findComposerEditor(), 20000);

  // 7. Optional first comment — after post appears
  // Left as a TODO: find the freshly posted item and click its comment field
  return {};
}

// ---------- Selectors ----------

function findComposerTrigger(): HTMLElement | null {
  // Common patterns: role="button" with aria-label starting with "Write" or "Create"
  const candidates = document.querySelectorAll<HTMLElement>(
    '[role="button"][aria-label], [role="textbox"][aria-label]'
  );
  for (const el of candidates) {
    const label = (el.getAttribute("aria-label") || "").toLowerCase();
    if (
      label.includes("write something") ||
      label.includes("create a post") ||
      label.includes("what's on your mind") ||
      label.includes("напишите что-нибудь") // ru locale
    ) {
      return el;
    }
  }
  return null;
}

function findComposerEditor(): HTMLElement | null {
  // The text area inside the open composer dialog
  const editors = document.querySelectorAll<HTMLElement>(
    'div[role="dialog"] [contenteditable="true"][role="textbox"]'
  );
  return editors[0] || null;
}

function findPostButton(): HTMLElement | null {
  const dialog = document.querySelector('div[role="dialog"]');
  if (!dialog) return null;
  const buttons = dialog.querySelectorAll<HTMLElement>('[role="button"]');
  for (const b of buttons) {
    const label = (b.getAttribute("aria-label") || b.textContent || "").trim().toLowerCase();
    if (label === "post" || label === "опубликовать" || label === "publish") {
      if (!b.hasAttribute("aria-disabled") || b.getAttribute("aria-disabled") === "false") {
        return b;
      }
    }
  }
  return null;
}

// ---------- Image attach ----------

async function attachImage(imageUrl: string): Promise<void> {
  // Fetch the image bytes from our local backend
  const full = imageUrl.startsWith("http") ? imageUrl : `http://localhost:8787/static/${imageUrl}`;
  const resp = await fetch(full);
  if (!resp.ok) throw new Error(`Failed to fetch image: ${resp.status}`);
  const blob = await resp.blob();
  const file = new File([blob], "image.png", { type: blob.type || "image/png" });

  // Find the file input inside the composer dialog. FB hides it — aria-label often says "Photo/Video"
  const input = await waitFor(
    () =>
      document.querySelector<HTMLInputElement>(
        'div[role="dialog"] input[type="file"][accept*="image"]'
      ),
    5000
  );
  if (!input) throw new Error("Image file input not found");

  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));

  // Wait for preview to render
  await sleep(2000);
}

// ---------- List groups ----------

async function listGroups(): Promise<Array<{ url: string; name: string; role?: string }>> {
  // The /groups/joins page lists groups the user belongs to.
  // This is a best-effort scrape — returns whatever we can find on the current viewport.
  const results: Array<{ url: string; name: string }> = [];
  const seen = new Set<string>();
  const links = document.querySelectorAll<HTMLAnchorElement>('a[href*="/groups/"]');
  for (const a of links) {
    const href = a.href;
    const m = href.match(/\/groups\/([^/?#]+)/);
    if (!m) continue;
    const url = `https://www.facebook.com/groups/${m[1]}`;
    if (seen.has(url)) continue;
    const text = a.textContent?.trim();
    if (!text || text.length < 2 || text.length > 200) continue;
    seen.add(url);
    results.push({ url, name: text });
  }
  return results;
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
  // ContentEditable with React fiber — clipboard paste is the most reliable path
  el.focus();
  const dt = new DataTransfer();
  dt.setData("text/plain", text);
  const evt = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
  el.dispatchEvent(evt);
  // Fallback: execCommand still works in most browsers for contenteditable
  if (!el.textContent?.includes(text.slice(0, 20))) {
    document.execCommand("insertText", false, text);
  }
  // Human-like typing delay jitter
  await sleep(300 + Math.random() * 500);
}

function waitFor<T>(
  predicate: () => T | null | undefined | false,
  timeoutMs: number
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

console.log("[autoposter-AI] content script loaded");
