// drafts.js — the interactive draft panel (step-15f). Renders one AI-drafted answer per
// free-text question for the human to read, edit, and insert — a separate gesture per field,
// never triggered by the main Fill button (step-15e's content.js, which contains no "draft"
// logic at all — see that file's own note and the grep test in tests/test_autoapply_notion.py).
//
// Loaded alongside panel.js in panel.html; runs in the same document/global scope but keeps its
// own state so the two files stay independently greppable. Never holds the bridge token — every
// bridge call goes through background.js exactly like panel.js's.

const CPAI_DRAFT_SOURCE = "free-text (human writes/reviews)";

function cpaiDraftTargets(plan) {
  return ((plan && plan.fields) || []).filter((f) => f.source === CPAI_DRAFT_SOURCE);
}

function cpaiActiveTabId(cb) {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    cb(tabs[0] ? tabs[0].id : null);
  });
}

function renderDraftRow(field, tabId) {
  const row = document.createElement("div");
  row.className = "cpai-draft-row";

  const label = document.createElement("div");
  label.className = "cpai-draft-label";
  label.textContent = field.label || field.name;
  row.appendChild(label);

  const textarea = document.createElement("textarea");
  textarea.className = "cpai-draft-text";
  textarea.value = field.draft || "";
  row.appendChild(textarea);

  const insertBtn = document.createElement("button");
  insertBtn.type = "button";
  insertBtn.textContent = "Insert";
  // Insert writes exactly the (possibly human-edited) textarea contents — never the original
  // AI draft unconditionally — and only into this one field. content.js re-badges it
  // "inserted — edit before submitting"; this button never claims the field is done.
  insertBtn.addEventListener("click", () => {
    if (tabId == null) return;
    insertBtn.disabled = true;
    chrome.tabs.sendMessage(
      tabId,
      { type: "CPAI_INSERT_FIELD_VALUE", name: field.name, value: textarea.value },
      (result) => {
        insertBtn.disabled = false;
        insertBtn.textContent = result && result.ok ? "Inserted" : "Insert failed — retry";
      },
    );
  });
  row.appendChild(insertBtn);

  return row;
}

function renderDrafts(plan, tabId) {
  const list = document.getElementById("drafts-list");
  list.innerHTML = "";
  const targets = cpaiDraftTargets(plan).filter((f) => f.draft);
  if (!targets.length) {
    const empty = document.createElement("div");
    empty.textContent = "No drafted answers yet — click Load draft answers.";
    list.appendChild(empty);
    return;
  }
  targets.forEach((field) => list.appendChild(renderDraftRow(field, tabId)));
}

function loadDrafts() {
  const btn = document.getElementById("load-drafts-btn");
  const resetBtn = () => {
    btn.disabled = false;
    btn.textContent = "Load draft answers";
  };
  btn.disabled = true;
  btn.textContent = "Drafting…";
  chrome.runtime.sendMessage({ type: "GET_LAST_PLAN" }, (planResult) => {
    const jobMatch = planResult && planResult.ok && planResult.body.job_match;
    const pageId = jobMatch && jobMatch.page_id;
    if (!pageId) {
      resetBtn();
      return;
    }
    cpaiActiveTabId((tabId) => {
      chrome.runtime.sendMessage(
        { type: "DRAFTS_REQUEST", pageId, plan: planResult.body.plan },
        (result) => {
          resetBtn();
          if (!result || !result.ok) return;
          renderDrafts(result.body.plan, tabId);
        },
      );
    });
  });
}

function refreshDraftsSection() {
  const section = document.getElementById("drafts-section");
  chrome.runtime.sendMessage({ type: "GET_LAST_PLAN" }, (planResult) => {
    if (!planResult || !planResult.ok) {
      section.hidden = true;
      return;
    }
    const jobMatch = planResult.body.job_match;
    const matched = jobMatch && (jobMatch.status === "known" || jobMatch.status === "matched");
    section.hidden = !(matched && cpaiDraftTargets(planResult.body.plan).length > 0);
  });
}

document.getElementById("load-drafts-btn").addEventListener("click", loadDrafts);

refreshDraftsSection();
setInterval(refreshDraftsSection, 2000);
