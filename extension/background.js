// background.js — MV3 service worker. The ONLY place that ever holds the bridge token or
// attaches it to a request. content.js and panel.js never see it — they message this worker
// and it does the actual authenticated fetch against 127.0.0.1. See the epic's "Fetch
// location" decision (docs/backlog/step-15-application-prefill-extension.md): a service
// worker fetch avoids a CORS preflight for the auth header, and the token never enters a page
// that shares a DOM with the job site.
//
// Read-only through step-15c: /plan and /resume/meta only. Resume bytes (/resume, for the
// content script's DataTransfer attach) land in step-15d. Still no text/select field fill, no
// drafts, no confirm-applied — those are step-15e/f/g.

const DEFAULT_PORT = 8765;

async function getConfig() {
  const { bridgePort, bridgeToken } = await chrome.storage.local.get(["bridgePort", "bridgeToken"]);
  return { port: bridgePort || DEFAULT_PORT, token: bridgeToken || "" };
}

async function bridgeFetch(path, options = {}) {
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

// Like bridgeFetch(), but for a binary response (/resume) instead of JSON: reads the body as
// an ArrayBuffer and turns it into a plain byte array so it survives structured-clone across
// the runtime message back to content.js, and pulls filename/mime from the response headers
// (never from anything the content script supplied) since Content-Disposition is server-set
// from the resolved file path, not client input.
async function bridgeFetchBinary(path) {
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

// Last /plan result per tab, so the docked side panel (a separate document from content.js)
// can read the same state the content script just fetched, without re-scraping the page
// itself. Single entry per tab is deliberate: running several tabs concurrently with their own
// tracked state is step-15i's job, not this story's.
const lastPlanByTab = new Map();

// page_id known ahead of navigation from the job-list launcher's OPEN_JOB click — carried into
// that tab's first PLAN_REQUEST so identify_job()'s rung 0 short-circuits straight to the job,
// skipping the candidate pool. Cleared once consumed so a later reused tab (nav elsewhere)
// doesn't keep pinning the wrong job.
const pendingPageIdByTab = new Map();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "PLAN_REQUEST") {
    const tabId = sender.tab && sender.tab.id;
    const pageId = tabId != null ? pendingPageIdByTab.get(tabId) : undefined;
    if (tabId != null && pageId != null) pendingPageIdByTab.delete(tabId);
    bridgeFetch("/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ live_url: message.liveUrl, dom: message.dom, page_id: pageId }),
    }).then((result) => {
      if (tabId != null) lastPlanByTab.set(tabId, result);
      sendResponse(result);
    });
    return true; // keep the message channel open for the async response
  }

  if (message && message.type === "GET_LAST_PLAN") {
    chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
      const tab = tabs[0];
      sendResponse(tab ? lastPlanByTab.get(tab.id) || null : null);
    });
    return true;
  }

  if (message && message.type === "JOBS_READY_REQUEST") {
    bridgeFetch("/jobs/ready").then(sendResponse);
    return true;
  }

  if (message && message.type === "OPEN_JOB") {
    const job = message.job || {};
    chrome.tabs.create({ url: job.url }).then((tab) => {
      if (tab.id != null && job.page_id) {
        pendingPageIdByTab.set(tab.id, job.page_id);
        chrome.sidePanel.setOptions({
          tabId: tab.id,
          path: `panel.html?page_id=${encodeURIComponent(job.page_id)}`,
        });
      }
    });
    return false;
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

  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  lastPlanByTab.delete(tabId);
  pendingPageIdByTab.delete(tabId);
});

// Docked side panel, opened for whichever tab the toolbar icon was clicked from.
chrome.action.onClicked.addListener((tab) => {
  if (tab.id != null) chrome.sidePanel.open({ tabId: tab.id });
});
