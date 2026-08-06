// panel.js — the docked side panel. Shows the matched job (or the rung-3 candidate list when
// identify_job() came back ambiguous), the tailored resume's filename, and a Copy-path button
// using the /resume/meta abs_path field — no file bytes cross the wire in this story (that's
// step-15d). Never holds the bridge token itself: every bridge call is a message to
// background.js, which is the only place the token/fetch actually happens.

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function renderCandidates(candidates) {
  const el = document.getElementById("candidates");
  el.hidden = false;
  el.innerHTML = "";
  candidates.forEach((c) => {
    const row = document.createElement("div");
    row.textContent = `${c.company || "(unknown company)"} — ${c.title || "(untitled)"}`;
    el.appendChild(row);
  });
}

function loadResumeMeta(pageId) {
  chrome.runtime.sendMessage({ type: "RESUME_META_REQUEST", pageId }, (result) => {
    const section = document.getElementById("resume-section");
    if (!result || !result.ok) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    setText("resume-filename", result.body.filename);
    section.dataset.absPath = result.body.abs_path;
  });
}

function renderJobList(jobs) {
  const el = document.getElementById("job-list");
  el.hidden = false;
  el.innerHTML = "";
  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.textContent = "No jobs at Resume Tailored right now.";
    el.appendChild(empty);
    return;
  }
  jobs.forEach((job) => {
    const row = document.createElement("div");
    const title = document.createElement("span");
    title.className = "cpai-title";
    title.textContent = `${job.company || "(unknown company)"} — ${job.title || "(untitled)"}`;
    const score = document.createElement("span");
    score.className = "cpai-score";
    score.textContent = job.score != null ? String(job.score) : "";
    row.appendChild(title);
    row.appendChild(score);
    row.addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "OPEN_JOB", job }, (result) => {
        // step-15i: the launcher's soft cap on concurrently-tracked sessions. Not silently
        // ignored — tell the human to close a tracked tab before opening another.
        if (result && result.ok === false && result.reason === "cap") {
          const jobMatchEl = document.getElementById("job-match");
          jobMatchEl.textContent =
            `Already tracking ${result.cap} session${result.cap === 1 ? "" : "s"} — `
            + "close one of those tabs before opening another from this list.";
        }
      });
    });
    el.appendChild(row);
  });
}

// step-15j — small state machine replacing the two hardcoded "is `python run.py --serve`
// running?" strings. background.js's bridgeFetch() already tried the native-messaging
// auto-start once before this ever runs (see its own retry-once contract); this only decides
// which message to show for however that attempt came out.
function bridgeUnreachableText(result) {
  const reason = result && result.body && result.body.bridgeStartReason;
  if (reason === "native-host-missing") {
    return "Native host not installed — run `python scripts/install_native_host.py "
      + "--extension-id <id>` (see Settings), or paste a token there manually.";
  }
  if (reason === "start-failed") {
    const detail = result.body.error ? ` (${result.body.error})` : "";
    return `Bridge auto-start failed${detail} — start it yourself with `
      + "`python run.py --serve`.";
  }
  return "Bridge unreachable — is `python run.py --serve` running?";
}

function loadJobList() {
  const jobMatchEl = document.getElementById("job-match");
  const jobListEl = document.getElementById("job-list");
  jobMatchEl.textContent = "Ready to apply:";
  jobListEl.hidden = false;
  chrome.runtime.sendMessage({ type: "JOBS_READY_REQUEST" }, (result) => {
    if (!result || !result.ok) {
      jobMatchEl.textContent = bridgeUnreachableText(result);
      jobListEl.hidden = true;
      return;
    }
    renderJobList(result.body.jobs || []);
  });
}

// step-15g — the confirm button only ever appears once a job is actually resolved
// (known/matched), and only carries the page_id the panel itself resolved — never a value
// content.js or any page script supplied.
function showConfirmApplied(pageId) {
  const section = document.getElementById("confirm-applied-section");
  section.hidden = false;
  section.dataset.pageId = pageId;
  setText("confirm-applied-status", "");
}

function hideConfirmApplied() {
  const section = document.getElementById("confirm-applied-section");
  section.hidden = true;
  delete section.dataset.pageId;
}

function render(planResult) {
  const jobMatchEl = document.getElementById("job-match");
  const resumeSection = document.getElementById("resume-section");
  const candidatesEl = document.getElementById("candidates");
  const jobListEl = document.getElementById("job-list");
  resumeSection.hidden = true;
  candidatesEl.hidden = true;
  candidatesEl.innerHTML = "";
  jobListEl.hidden = true;
  jobListEl.innerHTML = "";
  hideConfirmApplied();

  if (!planResult) {
    loadJobList();
    return;
  }
  if (!planResult.ok) {
    jobMatchEl.textContent = bridgeUnreachableText(planResult);
    return;
  }

  const { job_match: jobMatch, channel } = planResult.body;
  if (jobMatch.status === "known" || jobMatch.status === "matched") {
    const suffix = channel ? ` (${channel})` : "";
    jobMatchEl.textContent = `${jobMatch.job.company} — ${jobMatch.job.title}${suffix}`;
    loadResumeMeta(jobMatch.page_id);
    showConfirmApplied(jobMatch.page_id);
  } else if (jobMatch.status === "ambiguous") {
    jobMatchEl.textContent = "Multiple possible matches — pick one:";
    renderCandidates(jobMatch.candidates);
  } else {
    jobMatchEl.textContent = "No Notion match for this page.";
  }
}

function refresh() {
  chrome.runtime.sendMessage({ type: "GET_LAST_PLAN" }, render);
}

document.getElementById("copy-path-btn").addEventListener("click", async () => {
  const path = document.getElementById("resume-section").dataset.absPath;
  if (!path) return;
  await navigator.clipboard.writeText(path);
  setText("copy-status", "Copied.");
  setTimeout(() => setText("copy-status", ""), 1500);
});

// step-15g — one explicit gesture, one job, no auto-trigger from anywhere else in this file.
document.getElementById("confirm-applied-btn").addEventListener("click", () => {
  const section = document.getElementById("confirm-applied-section");
  const pageId = section.dataset.pageId;
  if (!pageId) return;
  const btn = document.getElementById("confirm-applied-btn");
  btn.disabled = true;
  setText("confirm-applied-status", "Confirming…");
  chrome.runtime.sendMessage({ type: "CONFIRM_APPLIED", pageId }, (result) => {
    btn.disabled = false;
    if (result && result.ok) {
      setText("confirm-applied-status", "✔ Marked Applied in Notion.");
    } else {
      const err = (result && result.body && result.body.error) || "confirm failed";
      setText("confirm-applied-status", `✗ ${err}`);
    }
  });
});

refresh();
setInterval(refresh, 2000);
