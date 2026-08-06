// content.js — scrapes the live application form into the DOM-payload shape
// scripts/autoapply_server.py's _dom_to_schema() (step-15b) expects, asks background.js for a
// /plan, paints a read-only badge next to each text/select question, offers a one-click
// "Attach resume" control next to the file-upload question (step-15d), and — since step-15e —
// a single "Fill N ready fields" button that writes every status=="ready" field's value into
// the page ONLY on that explicit click, never on load or on plan-fetch. No essay text
// generation (step-15f), no Notion status button (step-15g). Never holds the bridge token —
// all bridge calls happen in background.js.
//
// LinkedIn/Indeed need no special-casing here: the bridge itself already rewrites every field
// on those channels to review_required with a "channel read-only" source (step-15b) and 403s
// GET /resume bytes there (step-15d), so the controls below render the same way regardless of
// site — proof the read-only enforcement lives server-side, not in this file.
//
// Attach is verify-don't-claim (autoapply_browser.py's rule #2, applied here too): after
// assigning the file, it reads input.files[0]?.name back and reports only what it actually
// observed — "attached (verified)" or "not attached" plus a Copy-path fallback. It never
// programmatically opens the OS file picker — that is user-gesture-gated and not scriptable.

(function () {
  const FIELD_SELECTOR = "input, select, textarea";
  const SKIP_TYPES = new Set(["hidden", "submit", "button", "reset", "image"]);

  function isVisible(el) {
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && el.offsetParent !== null;
  }

  function domTypeOf(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return "textarea";
    if (tag === "select") return "select";
    return (el.getAttribute("type") || "text").toLowerCase();
  }

  function labelFor(el) {
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor && byFor.textContent.trim()) return byFor.textContent.trim();
    }
    const wrapping = el.closest("label");
    if (wrapping) {
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll("input, select, textarea").forEach((n) => n.remove());
      const text = clone.textContent.trim();
      if (text) return text;
    }
    return el.getAttribute("aria-label") || el.getAttribute("placeholder") || "";
  }

  function isRequired(el, label) {
    return el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label);
  }

  // Groups fields by label text so a Greenhouse-style attachment + "paste resume text" textarea
  // pair lands in one question object, matching build_application_plan()'s existing dedup logic
  // (autoapply.py — one question, multiple fields under the same label).
  function scrapeForm() {
    const grouped = new Map(); // label -> {required, fields}
    const elementByName = new Map();
    let counter = 0;

    document.querySelectorAll(FIELD_SELECTOR).forEach((el) => {
      const domType = domTypeOf(el);
      if (SKIP_TYPES.has(domType)) return;
      // File inputs are routinely hidden (display:none/opacity:0) by every dropzone library
      // (Dropzone.js, react-dropzone, Uppy, Filestack) — Greenhouse/Ashby/Workday all still
      // render a real <input type=file> underneath. Visibility is a fine filter for text/select
      // fields but would drop the resume question entirely, so file inputs are exempted.
      if (domType !== "file" && !isVisible(el)) return;

      const label = labelFor(el) || `Field ${counter}`;
      const name = el.getAttribute("name") || el.id || `field_${counter}`;
      counter += 1;
      elementByName.set(name, el);

      const field = { name, domType };
      if (el.tagName.toLowerCase() === "select") {
        field.options = Array.from(el.options)
          .filter((o) => o.value !== "")
          .map((o) => ({ label: o.textContent.trim(), value: o.value }));
      }

      const entry = grouped.get(label) || { required: false, fields: [] };
      entry.required = entry.required || isRequired(el, label);
      entry.fields.push(field);
      grouped.set(label, entry);
    });

    const questions = Array.from(grouped.entries()).map(([label, { required, fields }]) => ({
      label, required, fields,
    }));

    return { dom: { title: document.title, questions }, elementByName };
  }

  // Field names the human has already clicked Fill for. Consulted by badgeFor() so the
  // "filled" state survives the next automatic re-scan — without this, the MutationObserver
  // below (which fires on the very DOM mutations a fill produces) re-runs paintBadges() within
  // ~800ms and wipes/rebuilds every badge straight from a freshly-fetched plan, which has no
  // notion of "a human already filled this" and would silently repaint it back to "ready".
  // Discovered live: the underlying fill was always correct, only this feedback was ephemeral.
  const filledFieldNames = new Set();
  // Same staleness problem, same fix, for the side panel's per-field Insert gesture
  // (step-15f) — kept as a separate set since "inserted" is a distinct, permanent state
  // (unlike "filled", it never reverts to "ready": an inserted essay stays review_required
  // forever, so without this set a re-scan would repaint it back to a plain "○ review").
  const insertedFieldNames = new Set();

  function badgeFor(field) {
    const span = document.createElement("span");
    const filled = filledFieldNames.has(field.name);
    const inserted = insertedFieldNames.has(field.name);
    const ready = field.status === "ready";
    const cls = inserted ? "cpai-badge--inserted"
      : filled ? "cpai-badge--filled"
      : ready ? "cpai-badge--ready" : "cpai-badge--review";
    span.className = `cpai-badge ${cls}`;
    span.textContent = inserted ? "✔ inserted — edit before submitting"
      : filled ? "✔ filled"
      : ready ? "✔ ready" : "○ review";
    span.title = field.source || "";
    return span;
  }

  function addCopyPathButton(wrap, absPath) {
    if (!absPath || wrap.querySelector(".cpai-copy-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cpai-copy-btn";
    btn.textContent = "Copy path";
    btn.title = absPath;
    btn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(absPath);
      btn.textContent = "Copied.";
      setTimeout(() => { btn.textContent = "Copy path"; }, 1500);
    });
    wrap.appendChild(btn);
  }

  // Tier 1: assign directly to the (possibly hidden) file input, then read back what actually
  // landed — never claim success from the assignment call alone.
  function setFileOnInput(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return !!(input.files && input.files[0] && input.files[0].name === file.name);
  }

  // Tier 2: some dropzone libraries (react-dropzone et al.) never read input.files at all —
  // they listen for a drop event on their own container and read event.dataTransfer.files.
  function synthesizeDrop(target, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    const opts = { bubbles: true, cancelable: true, dataTransfer: dt };
    ["dragenter", "dragover", "drop"].forEach((name) => {
      target.dispatchEvent(new DragEvent(name, opts));
    });
  }

  async function tryAttach(input, file) {
    if (setFileOnInput(input, file)) return true;
    const dropTarget =
      input.closest("[class*='dropzone'], [class*='drop-zone'], [class*='uppy']") ||
      input.parentElement || input;
    synthesizeDrop(dropTarget, file);
    await new Promise((resolve) => setTimeout(resolve, 150));
    return !!(input.files && input.files[0] && input.files[0].name === file.name);
  }

  function attachResume(input, field, pageId, wrap) {
    const badge = wrap.querySelector(".cpai-badge");
    badge.textContent = "Attaching…";
    chrome.runtime.sendMessage(
      {
        type: "RESUME_FETCH", pageId,
        accept: input.getAttribute("accept") || "",
        liveUrl: window.location.href,
      },
      async (result) => {
        if (!result || !result.ok) {
          badge.className = "cpai-badge cpai-badge--review";
          badge.textContent = "○ not attached";
          addCopyPathButton(wrap, field.value);
          return;
        }
        const { bytes, mime, filename } = result.body;
        const file = new File([new Uint8Array(bytes)], filename, { type: mime, lastModified: Date.now() });
        const attached = await tryAttach(input, file);
        if (attached) {
          badge.className = "cpai-badge cpai-badge--ready";
          badge.textContent = "✔ attached (verified)";
        } else {
          badge.className = "cpai-badge cpai-badge--review";
          badge.textContent = "○ not attached";
          addCopyPathButton(wrap, field.value);
        }
      },
    );
  }

  function attachControlFor(field, el, pageId, readOnly) {
    const wrap = document.createElement("span");
    wrap.className = "cpai-attach";
    const ready = field.status === "ready";
    const missing = field.source === "resume-missing";
    const badge = document.createElement("span");
    badge.className = `cpai-badge ${ready ? "cpai-badge--ready" : "cpai-badge--review"}`;
    badge.textContent = ready ? "resume ready"
      : readOnly ? "read-only channel"
      : missing ? "resume missing" : "○ review";
    wrap.appendChild(badge);

    if (ready && pageId) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cpai-attach-btn";
      btn.textContent = "Attach resume";
      btn.addEventListener("click", () => attachResume(el, field, pageId, wrap));
      wrap.appendChild(btn);
    } else if (pageId && !missing) {
      // Read-only channel (or any other non-ready case with a known job): no bytes to attach,
      // but /resume/meta is still allowed — offer the Copy-path fallback from there instead.
      chrome.runtime.sendMessage({ type: "RESUME_META_REQUEST", pageId }, (result) => {
        if (result && result.ok && result.body && result.body.abs_path) {
          addCopyPathButton(wrap, result.body.abs_path);
        }
      });
    }
    return wrap;
  }

  function paintBadges(plan, elementByName, pageId, readOnly) {
    document.querySelectorAll(".cpai-badge, .cpai-attach").forEach((b) => b.remove());
    (plan.fields || []).forEach((field) => {
      const el = elementByName.get(field.name);
      if (!el) return;
      const isFileField = field.type === "input_file" || field.type === "attachment";
      const node = isFileField ? attachControlFor(field, el, pageId, readOnly) : badgeFor(field);
      el.insertAdjacentElement("afterend", node);
    });
  }

  // ── step-15e: fill ready fields on click, never on load ──────────────────────
  //
  // Fill predicate mirrors autoapply_browser.py:155's `ready = [f for f in plan["fields"]
  // if f["status"] == "ready"]` exactly, so Layer 2 (Playwright) and Layer 3 (this file) agree
  // on what "ready" means without sharing code. LinkedIn/Indeed fields arrive pre-rewritten to
  // review_required by the bridge (step-15b), so they're excluded by this same filter with no
  // extra logic here — proof read-only enforcement doesn't need duplicating client-side.

  function isFillableFieldType(type) {
    return type !== "input_file" && type !== "attachment";
  }

  // Mirrors autoapply_browser.py:203's select_option(label=...) rule: True/False resolve to
  // the visible "Yes"/"No" option label, anything else matches on str(value) — kept identical
  // so a select/radio fills with the same choice the CLI/Layer-2 fill would have picked.
  function labelForValue(value) {
    if (value === true) return "Yes";
    if (value === false) return "No";
    return value == null ? "" : String(value);
  }

  function dispatchInputChange(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillSelect(select, value) {
    const target = labelForValue(value);
    const options = Array.from(select.options);
    const opt = options.find((o) => o.textContent.trim() === target)
      || options.find((o) => o.value === String(value));
    if (!opt) return false;
    select.value = opt.value;
    dispatchInputChange(select);
    return true;
  }

  // Radio buttons in a group share one `name`, so the single element scrapeForm() mapped for
  // this field.name isn't necessarily the one that needs checking — look up every sibling in
  // the group and pick the one whose own label/value matches the resolved answer.
  function fillRadioGroup(name, value) {
    const target = labelForValue(value).toLowerCase();
    const radios = Array.from(
      document.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`),
    );
    if (!radios.length) return null;
    const match = radios.find((r) => {
      const label = labelFor(r).trim().toLowerCase();
      return label === target || r.value.toLowerCase() === target
        || r.value === String(value);
    });
    if (!match) return false;
    match.checked = true;
    dispatchInputChange(match);
    return match;
  }

  function fillCheckbox(el, value) {
    el.checked = !!value;
    dispatchInputChange(el);
    return true;
  }

  function fillText(el, value) {
    el.value = value == null ? "" : String(value);
    dispatchInputChange(el);
    return true;
  }

  // Returns the element that actually received the value (so the caller can badge it), or
  // null/false if nothing could be filled.
  function fillField(field, elementByName) {
    if (!isFillableFieldType(field.type)) return null;
    const el = elementByName.get(field.name);
    if (!el) return null;
    const tag = el.tagName.toLowerCase();
    const domType = (el.getAttribute("type") || tag).toLowerCase();
    if (tag === "select") return fillSelect(el, field.value) ? el : null;
    if (domType === "radio") return fillRadioGroup(el.getAttribute("name") || field.name, field.value);
    if (domType === "checkbox") return fillCheckbox(el, field.value) ? el : null;
    return fillText(el, field.value) ? el : null;
  }

  function markFilled(fieldName, el) {
    filledFieldNames.add(fieldName);
    if (!el) return;
    const badge = el.nextElementSibling;
    if (badge && badge.classList && badge.classList.contains("cpai-badge")) {
      badge.className = "cpai-badge cpai-badge--filled";
      badge.textContent = "✔ filled";
    }
  }

  function runFill(plan, elementByName) {
    (plan.fields || []).forEach((field) => {
      if (field.status !== "ready" || !isFillableFieldType(field.type)) return;
      const filledEl = fillField(field, elementByName);
      if (filledEl) markFilled(field.name, filledEl);
    });
  }

  function ensureFillButton(plan, elementByName) {
    const existing = document.getElementById("cpai-fill-btn");
    const readyCount = (plan.fields || []).filter(
      (f) => f.status === "ready" && isFillableFieldType(f.type),
    ).length;
    if (!readyCount) {
      if (existing) existing.remove();
      return;
    }
    const btn = existing || document.createElement("button");
    btn.id = "cpai-fill-btn";
    btn.type = "button";
    btn.className = "cpai-fill-btn";
    btn.textContent = `Fill ${readyCount} ready field${readyCount === 1 ? "" : "s"}`;
    // Rebind on every scan so the closure captures the *current* plan/elementByName — never
    // wired to auto-fire; this only ever runs from the human's own click.
    btn.onclick = () => runFill(plan, elementByName);
    if (!existing) document.body.appendChild(btn);
  }

  // Last scan's element map, kept around so a later out-of-band message (the side panel's
  // per-field Insert gesture, step-15f) can locate a field without re-scraping the page.
  let lastElementByName = new Map();

  function runScan() {
    const { dom, elementByName } = scrapeForm();
    lastElementByName = elementByName;
    if (!dom.questions.length) return;
    chrome.runtime.sendMessage(
      { type: "PLAN_REQUEST", liveUrl: window.location.href, dom },
      (result) => {
        if (!result || !result.ok) return;
        const body = result.body;
        const pageId = body.job_match && body.job_match.page_id;
        const readOnly = body.channel === "linkedin" || body.channel === "indeed";
        paintBadges(body.plan, elementByName, pageId, readOnly);
        ensureFillButton(body.plan, elementByName);
      },
    );
  }

  // The side panel's per-field Insert gesture (step-15f) lands here as a plain "set this named
  // field's value" instruction — this file never generates or even reads AI text, it only
  // writes whatever string the human already reviewed and clicked Insert on, exactly like any
  // other write in this file. Text/textarea only: the fields this ever targets are always
  // free-text (case (e) in _resolve_field's ordering), never select/radio/checkbox/file.
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "CPAI_INSERT_FIELD_VALUE") return false;
    const el = lastElementByName.get(message.name);
    if (!el) {
      sendResponse({ ok: false, error: "field not found on page" });
      return false;
    }
    fillText(el, message.value);
    insertedFieldNames.add(message.name);
    const badge = el.nextElementSibling;
    if (badge && badge.classList && badge.classList.contains("cpai-badge")) {
      badge.className = "cpai-badge cpai-badge--inserted";
      badge.textContent = "✔ inserted — edit before submitting";
    }
    sendResponse({ ok: true });
    return false;
  });

  // Run once after the page settles, then again after DOM mutations quiet down — SPA-heavy ATS
  // boards (Greenhouse/Ashby/Workday) often render the real form well after document_idle. A
  // short trailing-edge debounce keeps a burst of mutations from POSTing /plan on every tick.
  let debounceHandle = null;
  const observer = new MutationObserver(() => {
    clearTimeout(debounceHandle);
    debounceHandle = setTimeout(runScan, 800);
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  }

  setTimeout(runScan, 500);
})();
