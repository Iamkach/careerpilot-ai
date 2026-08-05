# Non-goals

- **Automated submit on LinkedIn/Indeed, ever, at any automation level.** LinkedIn §8.2 and Indeed
  prohibit automated applying and flag it behaviorally. `manual_adapter`/read-only answer sheet
  only — hard rule, not a phase to eventually cross.
- **Captcha-solving as part of the default path.** Semi-auto treats a captcha as the designed
  human-handoff point. A paid solver would be a fully-hands-off-only, opt-in, per-user-keyed
  extra, flagged as higher ToS risk — not built here.
- **Guessing work-authorization, sponsorship, salary, or any yes/no eligibility answer.** These
  come from `APPLICATION_PROFILE` only; anything unmapped routes to human review. A code-level
  validator enforces this, not the prompt.
- **LLM-guessing EEO/demographic answers.** Default to "Decline to self-identify" unless the user
  set an explicit preference.
- **Rushing Phase 3 (deliberate submit) ahead of real fill-path usage data.** Deferred by choice —
  see end-goal.md.
- **A per-ATS Playwright adapter for Ashby/Workday/custom, for the interactive case.** Superseded
  by `spec/application-prefill-extension/`, which covers the same gap with one code path instead
  of a per-ATS adapter. The Playwright/agentic route (Phase 4) stays relevant only for unattended
  runs.
- **Resolving the true apply-form destination behind a LinkedIn/Indeed posting** (scenario 8,
  "external redirect"). Measured and found not to feed the shipped Layer 2 — see problem.md's
  "Why the tracker is starved of ATS-fillable rows." Not worth doing on its own.
