// content.js — scrapes the live application form into the DOM-payload shape
// scripts/autoapply_server.py's _dom_to_schema() (step-15b) expects, asks background.js for a
// /plan, paints a read-only badge next to each text/select question, and — since step-15d —
// offers a one-click "Attach resume" control next to the file-upload question. NO TEXT/SELECT
// FILL CODE HERE — that's step-15e. No essay text generation (step-15f), no Notion status
// button (step-15g). Never holds the bridge token — all bridge calls happen in background.js.
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

  function badgeFor(field) {
    const span = document.createElement("span");
    const ready = field.status === "ready";
    span.className = `cpai-badge ${ready ? "cpai-badge--ready" : "cpai-badge--review"}`;
    span.textContent = ready ? "✔ ready" : "○ review";
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

  function runScan() {
    const { dom, elementByName } = scrapeForm();
    if (!dom.questions.length) return;
    chrome.runtime.sendMessage(
      { type: "PLAN_REQUEST", liveUrl: window.location.href, dom },
      (result) => {
        if (!result || !result.ok) return;
        const body = result.body;
        const pageId = body.job_match && body.job_match.page_id;
        const readOnly = body.channel === "linkedin" || body.channel === "indeed";
        paintBadges(body.plan, elementByName, pageId, readOnly);
      },
    );
  }

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
