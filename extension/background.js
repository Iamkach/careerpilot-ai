// background.js — MV3 service worker. The ONLY place that ever holds the bridge token or
// attaches it to a request. content.js and panel.js never see it — they message this worker
// and it does the actual authenticated fetch against 127.0.0.1. See the epic's "Fetch
// location" decision (docs/backlog/step-15-application-prefill-extension.md): a service
// worker fetch avoids a CORS preflight for the auth header, and the token never enters a page
// that shares a DOM with the job site.

const DEFAULT_PORT = 8765;
const NATIVE_HOST_NAME = "com.careerpilot.bridge_host";

async function getConfig() {
  const { bridgePort, bridgeToken } = await chrome.storage.local.get(["bridgePort", "bridgeToken"]);
  return { port: bridgePort || DEFAULT_PORT, token: bridgeToken || "" };
}

// step-15j — on a "the fetch never got a response at all" failure (nothing listening on the
// port), ask the native-messaging host to start the bridge and hand back its token/port. Never
// fires on browser/OS startup or a timer — only from inside a bridge call already triggered by
// something the human did (opening the panel, a scan, a click), so the invocation stays
// session-scoped and human-triggered exactly like the epic's "never a daemon" decision assumed
// — only *who types `python run.py --serve`* changed, not what the process is.
async function ensureBridgeRunning() {
  const { port } = await getConfig();
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(
        NATIVE_HOST_NAME,
        { action: "ensure_started", port },
        (response) => {
          if (chrome.runtime.lastError) {
            // Distinct from "bridge unreachable": the extension was never pointed at
            // scripts/install_native_host.py's output, or the registered id doesn't match this
            // load — point the human at the install step, not a generic retry.
            resolve({ ok: false, reason: "native-host-missing",
                       detail: chrome.runtime.lastError.message });
            return;
          }
          if (!response || (response.status !== "started" && response.status !== "already_running")) {
            resolve({ ok: false, reason: "start-failed",
                       detail: (response && response.message) || "unknown native host error" });
            return;
          }
          const update = { bridgePort: response.port || port };
          if (response.token) update.bridgeToken = response.token;
          chrome.storage.local.set(update).then(() => resolve({ ok: true }));
        },
      );
    } catch (err) {
      // sendNativeMessage throws synchronously if the API itself is unavailable (e.g. the
      // "nativeMessaging" permission is missing) — treat identically to a missing host.
      resolve({ ok: false, reason: "native-host-missing", detail: String(err) });
    }
  });
}

async function _rawBridgeFetch(path, options = {}) {
  const { port, token } = await getConfig();
  const url = `http://127.0.0.1:${port}${path}`;
  const headers = Object.assign({}, options.headers || {}, { Authorization: `Bearer ${token}` });
  try {
    const res = await fetch(url, Object.assign({}, options, { headers }));
    const body = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, body };
  } catch (err) {
    return { ok: false, status: 0, body: { error: String(err) } };
  }
}

// On a status:0 (nothing answered at all — not an HTTP error), try to auto-start the bridge via
// the native host and retry the original request exactly once. Never loop: a second failure
// surfaces to the caller exactly as it would have before this story existed.
async function bridgeFetch(path, options = {}) {
  const result = await _rawBridgeFetch(path, options);
  if (result.status !== 0) return result;
  const ensured = await ensureBridgeRunning();
  if (!ensured.ok) {
    return { ok: false, status: 0,
             body: { error: ensured.detail, bridgeStartReason: ensured.reason } };
  }
  return _rawBridgeFetch(path, options);
}

// Like bridgeFetch(), but for a binary response (/resume) instead of JSON: reads the body as
// an ArrayBuffer and turns it into a plain byte array so it survives structured-clone across
// the runtime message back to content.js, and pulls filename/mime from the response headers
// (never from anything the content script supplied) since Content-Disposition is server-set
// from the resolved file path, not client input.
async function _rawBridgeFetchBinary(path) {
  const { port, token } = await getConfig();
  const url = `http://127.0.0.1:${port}${path}`;
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, status: res.status, body };
    }
    const buf = await res.arrayBuffer();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]*)"/.exec(cd);
    const filename = match ? match[1] : "resume";
    const mime = res.headers.get("Content-Type") || "application/octet-stream";
    return {
      ok: true, status: res.status,
      body: { bytes: Array.from(new Uint8Array(buf)), mime, filename },
    };
  } catch (err) {
    return { ok: false, status: 0, body: { error: String(err) } };
  }
}

async function bridgeFetchBinary(path) {
  const result = await _rawBridgeFetchBinary(path);
  if (result.status !== 0) return result;
  const ensured = await ensureBridgeRunning();
  if (!ensured.ok) {
    return { ok: false, status: 0,
             body: { error: ensured.detail, bridgeStartReason: ensured.reason } };
  }
  return _rawBridgeFetchBinary(path);
}

// step-15i — one unified per-tab session map, replacing the earlier separate lastPlanByTab/
// pendingPageIdByTab Maps (both were already tabId-keyed, so this is a consolidation, not a
// rebuild). Every tab the extension has ever heard from — organically scanned or launcher-
// opened — gets its own {pageId, plan, lastFetchedAt} entry, and every downstream handler
// reads/writes only its own tab's entry. DRAFTS_REQUEST/RESUME_META_REQUEST/RESUME_FETCH/
// CONFIRM_APPLIED below don't touch this map at all: they already carry an explicit page_id
// from the caller (panel.js/drafts.js's own resolved job_match), so they were correctly
// tab-scoped from the moment they were written — nothing to change there.
const sessionByTab = new Map();

// Soft cap on concurrently-*launcher-opened* sessions (step-15h's OPEN_JOB), configurable via
// options.html, default 5. This does NOT gate organic PLAN_REQUEST scans from a tab the human
// navigated to by hand — capping those would regress step-15c's read-only overlay on every
// site, for a guard that only exists to keep the launcher from opening more tabs than the human
// (or the panel's own session bookkeeping) can reasonably track. At the cap, OPEN_JOB is
// blocked with a message rather than evicting a session out from under an in-progress fill —
// losing a tracked plan silently is worse than making the human close a tab first.
const DEFAULT_SESSION_CAP = 5;

async function getSessionCap() {
  const { sessionCap } = await chrome.storage.local.get(["sessionCap"]);
  return sessionCap || DEFAULT_SESSION_CAP;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "PLAN_REQUEST") {
    const tabId = sender.tab && sender.tab.id;
    const session = tabId != null ? sessionByTab.get(tabId) : undefined;
    const pageId = session && session.pageId;
    // Consumed once, like the old pendingPageIdByTab: identify_job()'s rung 0 only needs to
    // fire on the first scan after a launcher navigation. A later re-scan (SPA re-render,
    // MutationObserver debounce) falls back to rung 1's URL match, which still finds the same
    // job — dropping this doesn't lose track of the tab's session, only the short-circuit.
    if (session && session.pageId != null) session.pageId = null;
    bridgeFetch("/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ live_url: message.liveUrl, dom: message.dom, page_id: pageId }),
    }).then((result) => {
      if (tabId != null) {
        const entry = sessionByTab.get(tabId) || {};
        entry.plan = result;
        entry.lastFetchedAt = Date.now();
        sessionByTab.set(tabId, entry);
      }
      sendResponse(result);
    });
    return true; // keep the message channel open for the async response
  }

  if (message && message.type === "GET_LAST_PLAN") {
    chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
      const tab = tabs[0];
      const session = tab ? sessionByTab.get(tab.id) : undefined;
      sendResponse((session && session.plan) || null);
    });
    return true;
  }

  if (message && message.type === "JOBS_READY_REQUEST") {
    bridgeFetch("/jobs/ready").then(sendResponse);
    return true;
  }

  if (message && message.type === "OPEN_JOB") {
    const job = message.job || {};
    (async () => {
      const cap = await getSessionCap();
      if (sessionByTab.size >= cap) {
        sendResponse({ ok: false, reason: "cap", cap });
        return;
      }
      const tab = await chrome.tabs.create({ url: job.url });
      if (tab.id != null && job.page_id) {
        sessionByTab.set(tab.id, { pageId: job.page_id, plan: null, lastFetchedAt: Date.now() });
        await chrome.sidePanel.setOptions({
          tabId: tab.id,
          path: `panel.html?page_id=${encodeURIComponent(job.page_id)}`,
        });
      }
      sendResponse({ ok: true });
    })();
    return true; // keep the message channel open for the async response
  }

  if (message && message.type === "RESUME_META_REQUEST") {
    bridgeFetch(`/resume/meta?page_id=${encodeURIComponent(message.pageId)}`).then(sendResponse);
    return true;
  }

  if (message && message.type === "RESUME_FETCH") {
    const qs = new URLSearchParams({
      page_id: message.pageId || "",
      accept: message.accept || "",
      live_url: message.liveUrl || "",
    });
    bridgeFetchBinary(`/resume?${qs.toString()}`).then(sendResponse);
    return true;
  }

  // step-15f — one AI call per free-text question, so it's deliberately its own message/route
  // rather than folded into PLAN_REQUEST (would block every fill on a 10-30s AI round-trip).
  if (message && message.type === "DRAFTS_REQUEST") {
    bridgeFetch("/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_id: message.pageId, plan: message.plan }),
    }).then(sendResponse);
    return true;
  }

  // step-15g — the ONLY status write this extension makes. confirmed_by is always the literal
  // "human" (never anything the caller supplies), so a bug in panel.js can't smuggle a
  // different value through this message; the real enforcement is server-side anyway
  // (autoapply_server.py's build_confirm_applied_response).
  if (message && message.type === "CONFIRM_APPLIED") {
    bridgeFetch("/confirm-applied", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_id: message.pageId, confirmed_by: "human" }),
    }).then(sendResponse);
    return true;
  }

  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  // A closed tab's in-memory session shouldn't linger and shouldn't count against the soft cap.
  sessionByTab.delete(tabId);
});

// Docked side panel, opened for whichever tab the toolbar icon was clicked from.
chrome.action.onClicked.addListener((tab) => {
  if (tab.id != null) chrome.sidePanel.open({ tabId: tab.id });
});
