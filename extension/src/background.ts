/**
 * Background service worker.
 *
 * Responsibilities:
 * - Open and maintain a single WebSocket to ws://localhost:8787/ws/ext.
 * - Receive commands from backend (publish, list_groups).
 * - Forward them to the right facebook.com tab's content script via chrome.tabs.sendMessage.
 * - Relay the content script's response back over the WebSocket.
 *
 * Service workers in Manifest V3 can be killed at any time. We re-establish the WS
 * on wake via a heartbeat ping.
 */

const WS_URL = "ws://localhost:8787/ws/ext";
const RECONNECT_MS = 3000;

let ws: WebSocket | null = null;

function connect(): void {
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.warn("[autoposter-AI] WS connect error:", e);
    setTimeout(connect, RECONNECT_MS);
    return;
  }

  ws.onopen = () => console.log("[autoposter-AI] WS connected");
  ws.onclose = () => {
    console.log("[autoposter-AI] WS closed, reconnecting...");
    ws = null;
    setTimeout(connect, RECONNECT_MS);
  };
  ws.onerror = (e) => console.warn("[autoposter-AI] WS error:", e);

  ws.onmessage = async (event) => {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(event.data);
    } catch {
      console.warn("[autoposter-AI] bad JSON from backend");
      return;
    }

    const requestId = msg.request_id as string;
    try {
      const result = await routeCommand(msg);
      ws?.send(JSON.stringify({ request_id: requestId, ok: true, ...result }));
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      ws?.send(JSON.stringify({ request_id: requestId, ok: false, error }));
    }
  };
}

async function routeCommand(msg: Record<string, unknown>): Promise<Record<string, unknown>> {
  const type = msg.type as string;
  switch (type) {
    case "publish":
      return await handlePublish(msg);
    case "list_groups":
      return await handleListGroups(msg);
    case "list_suggested_groups":
      return await handleListSuggestedGroups(msg);
    case "fetch_metrics":
      return await handleFetchMetrics(msg);
    case "ping":
      return { pong: true };
    default:
      throw new Error(`Unknown command: ${type}`);
  }
}

async function handleFetchMetrics(
  msg: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const postUrl = msg.post_url as string;
  if (!postUrl) throw new Error("post_url required");
  const tab = await openOrFocusFacebookTab(postUrl);
  if (!tab.id) throw new Error("Could not obtain tab id");
  // Facebook's permalink pages need a beat to render reaction/comment counters.
  await sleep(3500);
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "fetch_metrics",
  });
  if (!response?.ok) throw new Error(response?.error || "failed to fetch metrics");
  return { metrics: response.metrics };
}

async function handlePublish(msg: Record<string, unknown>): Promise<Record<string, unknown>> {
  const targetUrl = msg.target_url as string;
  // Open or reuse a FB tab, then send the command to its content script
  const tab = await openOrFocusFacebookTab(targetUrl);
  if (!tab.id) throw new Error("Could not obtain tab id");
  // Give the content script a moment to load
  await sleep(1500);
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "publish",
    text: msg.text,
    image_url: msg.image_url,
    first_comment: msg.first_comment,
    humanizer: msg.humanizer,
  });
  if (!response?.ok) throw new Error(response?.error || "content script reported failure");
  return { post_url: response.post_url, post_id: response.post_id };
}

async function handleListGroups(_msg: Record<string, unknown>): Promise<Record<string, unknown>> {
  const tab = await openOrFocusFacebookTab("https://www.facebook.com/groups/joins");
  if (!tab.id) throw new Error("Could not obtain tab id");
  await sleep(2500);
  const response = await chrome.tabs.sendMessage(tab.id, { type: "list_groups" });
  if (!response?.ok) throw new Error(response?.error || "failed to list groups");
  return { groups: response.groups };
}

async function handleListSuggestedGroups(
  _msg: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  // Facebook's "Discover groups" feed. It lazy-loads a lot — we scroll a few times.
  const tab = await openOrFocusFacebookTab("https://www.facebook.com/groups/discover");
  if (!tab.id) throw new Error("Could not obtain tab id");
  await sleep(3000);
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "list_suggested_groups",
  });
  if (!response?.ok) throw new Error(response?.error || "failed to list suggested groups");
  return { groups: response.groups };
}

async function openOrFocusFacebookTab(url: string): Promise<chrome.tabs.Tab> {
  const tabs = await chrome.tabs.query({ url: ["*://*.facebook.com/*"] });
  if (tabs.length > 0) {
    const tab = tabs[0];
    if (tab.id && tab.url !== url) {
      await chrome.tabs.update(tab.id, { url, active: true });
    }
    return tab;
  }
  return chrome.tabs.create({ url, active: true });
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// Start
connect();
// Keep alive — Manifest V3 service worker heartbeat
setInterval(() => {
  if (ws?.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: "heartbeat" }));
    } catch {
      /* ignore */
    }
  }
}, 25000);
