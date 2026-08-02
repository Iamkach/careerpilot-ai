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
      chrome.runtime.sendMessage({ type: "OPEN_JOB", job });
    });
    el.appendChild(row);
  });
}

function loadJobList() {
  const jobMatchEl = document.getElementById("job-match");
  const jobListEl = document.getElementById("job-list");
  jobMatchEl.textContent = "Ready to apply:";
  jobListEl.hidden = false;
  chrome.runtime.sendMessage({ type: "JOBS_READY_REQUEST" }, (result) => {
    if (!result || !result.ok) {
      jobMatchEl.textContent = "Bridge unreachable — is `python run.py --serve` running?";
      jobListEl.hidden = true;
      return;
    }
    renderJobList(result.body.jobs || []);
  });
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

  if (!planResult) {
    loadJobList();
    return;
  }
  if (!planResult.ok) {
    jobMatchEl.textContent = "Bridge unreachable — is `python run.py --serve` running?";
    return;
  }

  const { job_match: jobMatch, channel } = planResult.body;
  if (jobMatch.status === "known" || jobMatch.status === "matched") {
    const suffix = channel ? ` (${channel})` : "";
    jobMatchEl.textContent = `${jobMatch.job.company} — ${jobMatch.job.title}${suffix}`;
    loadResumeMeta(jobMatch.page_id);
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

refresh();
setInterval(refresh, 2000);
